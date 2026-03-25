#!/usr/bin/env python3
"""
Viral Brand Video Pipeline — Generate branded short videos from viral references.

Usage:
  python3 pipeline.py run   --brand-ref LABEL.jpg --brand-config brand.json --input VIDEO.mp4 --output OUT/
  python3 pipeline.py batch --brand-ref LABEL.jpg --brand-config brand.json --input-dir VIDEOS/ --output OUT/
  python3 pipeline.py screen --brand-ref LABEL.jpg --input-dir VIDEOS/

Environment:
  VBV_GEMINI_API   Gemini endpoint (default: https://generativelanguage.googleapis.com)
  VBV_GEMINI_KEY   Gemini API key
  VBV_KLING_API    Kling endpoint
  VBV_KLING_KEY    Kling API key
"""

import argparse
import base64
import json
import os
import random
import re
import subprocess
import sys
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─── Configuration ───

GEMINI_API = os.environ.get("VBV_GEMINI_API", "")
GEMINI_KEY = os.environ.get("VBV_GEMINI_KEY", "")
KLING_API  = os.environ.get("VBV_KLING_API", "https://api.vectorengine.ai")
KLING_KEY  = os.environ.get("VBV_KLING_KEY", "")
GPT_IMG_API = os.environ.get("VBV_GPT_IMG_API", "https://api.vectorengine.ai")
GPT_IMG_KEY = os.environ.get("VBV_GPT_IMG_KEY", "")

DEFAULT_FONT = "/System/Library/Fonts/STHeiti Medium.ttc"

# ─── Prompt variation pools ───

CAMERAS = [
    "Camera slowly pushes forward.",
    "Camera holds still with natural sway.",
    "Camera drifts right with slow pan.",
    "Camera subtle crane upward.",
    "Camera gentle pull back.",
    "Camera slow orbit left.",
    "Camera static with micro-tremor.",
]
LIGHTINGS = [
    "Warm amber candlelight.",
    "Soft golden hour light.",
    "Neon-tinted warm glow.",
    "Dim moody tungsten with deep shadows.",
    "Warm string light bokeh.",
    "Cool blue ambient with warm key light.",
    "Firelight flicker on surfaces.",
]
ATMOSPHERES = [
    "Cozy intimate atmosphere.",
    "Melancholic peaceful ambiance.",
    "Relaxed late-night vibe.",
    "Cinematic shallow focus.",
    "Quiet contemplative mood.",
    "Dreamy soft-focus haze.",
    "Raw emotional solitude.",
]

DEDUP_COLORS = {
    "golden":  "eq=brightness=0.02:saturation=1.15:gamma_r=1.08:gamma_g=1.02:gamma_b=0.9",
    "warm":    "eq=brightness=0.02:saturation=1.1:gamma_r=1.05:gamma_b=0.95",
    "moody":   "eq=brightness=-0.03:saturation=0.95:contrast=1.1",
    "amber":   "eq=brightness=0.01:saturation=1.2:gamma_r=1.1:gamma_g=0.98:gamma_b=0.85",
    "cool":    "eq=brightness=0.0:saturation=1.05:gamma_r=0.95:gamma_b=1.08",
    "neutral": "eq=brightness=0.01:saturation=1.0",
    "vintage": "eq=brightness=-0.02:saturation=0.85:gamma_r=1.05:gamma_g=1.0:gamma_b=0.9",
    "vivid":   "eq=brightness=0.03:saturation=1.25:gamma_r=1.02:gamma_b=0.92",
}

BRAND_PROMPTS = {
    "static": (
        "Image 1 is the target brand label. Image 2 is the scene.\n"
        "Find the LARGEST/MOST VISIBLE bottle and replace its label with the brand from Image 1.\n"
        "The replacement must be clearly visible — match label size, curvature, perspective.\n"
        "Keep everything else identical. Photorealistic result."
    ),
    "pouring": (
        "Image 1 is the target brand label. Image 2 shows a pouring scene.\n"
        "Replace the brand/label on the bottle that is pouring with the brand from Image 1.\n"
        "Keep the pouring action exactly as-is. Only modify the brand on the container."
    ),
    "handheld": (
        "Image 1 is the target brand label. Image 2 shows hands holding drinks.\n"
        "If a bottle is visible anywhere in the scene, replace its label with Image 1's brand.\n"
        "If only glasses are visible, place a small branded bottle naturally on the nearest surface.\n"
        "Match the scene's lighting and perspective."
    ),
}

SUBTITLE_STYLES = [
    {"fontsize": 36, "color": "white", "border": "black"},
    {"fontsize": 34, "color": "#FFFAF0", "border": "#1a1a1a"},
    {"fontsize": 38, "color": "#FFF8E7", "border": "#2D2D2D"},
    {"fontsize": 36, "color": "#FFE4C4", "border": "#1a1a1a"},
    {"fontsize": 34, "color": "white", "border": "#333333"},
    {"fontsize": 38, "color": "#FAFAD2", "border": "black"},
]


# ═══════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════

def http_session():
    s = requests.Session()
    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=10)))
    return s


def get_duration(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def kling_duration(ref_dur):
    if ref_dur <= 6: return "5"
    elif ref_dur <= 11: return "10"
    else: return "15"


def upload_catbox(fpath, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post("https://catbox.moe/user/api.php",
                files={"fileToUpload": open(fpath, "rb")},
                data={"reqtype": "fileupload"}, timeout=120)
            url = r.text.strip()
            if url.startswith("http"):
                return url
        except:
            time.sleep(5)
    raise Exception("Catbox upload failed")


def load_brand_config(path):
    """Load brand config JSON with defaults."""
    defaults = {
        "name": "Brand",
        "product": "Product",
        "container": "glass_bottle",
        "hashtag_anchor": "#Brand",
        "scenes": [],
        "emotion_tags": {
            "emo":     ["#深夜emo", "#情绪出口", "#治愈系"],
            "solo":    ["#微醺", "#一个人喝酒", "#独处", "#解压"],
            "relax":   ["#深夜小酌", "#解压好物", "#微醺时刻"],
            "social":  ["#朋友聚会", "#小酌", "#周末"],
            "default": ["#微醺", "#深夜小酌", "#一个人喝酒"],
        },
        "trend_tags": ["#情绪稳定", "#成年人的快乐", "#夜晚", "#生活"],
        "subtitle_adaptations": {},
    }
    if path and os.path.exists(path):
        with open(path) as f:
            user = json.load(f)
        defaults.update(user)
    return defaults


# ═══════════════════════════════════════════
# Gemini API helpers
# ═══════════════════════════════════════════

def gpt_image_edit(prompt, image_path, retries=3):
    """Edit image via GPT-Image-1 (VCE .ai endpoint). Returns raw bytes or None."""
    for attempt in range(retries):
        try:
            with open(image_path, "rb") as f:
                resp = requests.post(
                    f"{GPT_IMG_API}/v1/images/edits",
                    headers={"Authorization": f"Bearer {GPT_IMG_KEY}"},
                    files={"image": ("frame.jpg", f, "image/jpeg")},
                    data={"model": "gpt-image-1-all", "prompt": prompt, "size": "1024x1024"},
                    timeout=120,
                )
            d = resp.json()
            if "data" in d and d["data"]:
                item = d["data"][0]
                if "b64_json" in item:
                    return base64.b64decode(item["b64_json"])
                elif "url" in item:
                    return requests.get(item["url"], timeout=60).content
            print(f"    ⚠️ GPT-Image attempt {attempt+1}: {str(d)[:120]}")
        except Exception as e:
            print(f"    ⚠️ GPT-Image attempt {attempt+1}: {e}")
        time.sleep(min(15 * (2 ** attempt), 60))
    return None


def gemini_api(content, retries=3, model="gemini-3.1-flash-image-preview"):
    for attempt in range(retries):
        try:
            headers = {"Authorization": f"Bearer {GEMINI_KEY}", "Content-Type": "application/json"}
            body = {"model": model,
                    "messages": [{"role": "user", "content": content}]}
            r = http_session().post(f"{GEMINI_API}/v1/chat/completions",
                                    headers=headers, json=body, timeout=120)
            d = r.json()
            if "choices" not in d:
                print(f"    ⚠️ API attempt {attempt+1}: {str(d)[:100]}")
                # Exponential backoff: 15, 30, 60, 60, 60...
                time.sleep(min(15 * (2 ** attempt), 60))
                continue
            return d["choices"][0]["message"].get("content", "")
        except Exception as e:
            print(f"    ⚠️ API attempt {attempt+1}: {e}")
            time.sleep(min(15 * (2 ** attempt), 60))
    return None


def gemini_edit(prompt, *image_paths, retries=3):
    content = []
    labels = ["[Reference]", "[Image to edit]", "[Image 3]", "[Image 4]"]
    for i, p in enumerate(image_paths):
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = "png" if str(p).endswith(".png") else "jpeg"
        if len(image_paths) > 1 and i < len(labels):
            content.append({"type": "text", "text": labels[i]})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}})
    content.append({"type": "text", "text": prompt})

    cv = gemini_api(content, retries=retries)
    if cv is None:
        return None

    if isinstance(cv, list):
        for part in cv:
            if part.get("type") == "image_url":
                iu = part["image_url"]["url"]
                if iu.startswith("data:"):
                    return base64.b64decode(iu.split(",", 1)[1])
                return requests.get(iu, timeout=60).content
    elif isinstance(cv, str):
        m = re.search(r'data:image/\w+;base64,([A-Za-z0-9+/=]+)', cv)
        if m:
            return base64.b64decode(m.group(1))
    return None


def gemini_json(prompt, *image_paths, retries=3):
    content = []
    for p in image_paths:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = "png" if str(p).endswith(".png") else "jpeg"
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}})
    content.append({"type": "text", "text": prompt})

    cv = gemini_api(content, retries=retries)
    if cv is None:
        return {}

    text = cv if isinstance(cv, str) else " ".join(p.get("text", "") for p in cv if p.get("type") == "text")
    depth = 0
    start = -1
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0: start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i+1])
                except:
                    continue
    return {}


# ═══════════════════════════════════════════
# Phase 1: Analyze + Screen + Feasibility
# ═══════════════════════════════════════════

def analyze_and_screen(video_path, vid_id, brand_ref, brand_config):
    duration = get_duration(video_path)

    info_r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "stream=width,height",
        "-of", "csv=p=0", str(video_path)], capture_output=True, text=True)
    dims = info_r.stdout.strip().split(",")
    width, height = (int(dims[0]), int(dims[1])) if len(dims) >= 2 else (0, 0)

    frames_b64 = []
    for ratio in [0.1, 0.4, 0.8]:
        ts = duration * ratio
        fpath = f"/tmp/vbv_{vid_id}_{ratio}.jpg"
        subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-ss", str(ts),
            "-frames:v", "1", "-q:v", "2", "-vf", "scale=512:-1", fpath], capture_output=True)
        with open(fpath, "rb") as f:
            frames_b64.append(base64.b64encode(f.read()).decode())

    with open(brand_ref, "rb") as f:
        brand_b64 = base64.b64encode(f.read()).decode()

    container = brand_config.get("container", "glass_bottle")

    content = [
        {"type": "text", "text": "[Brand Reference]"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{brand_b64}"}},
    ]
    for i, b64 in enumerate(frames_b64):
        content.append({"type": "text", "text": f"[Frame {i+1}]"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    content.append({"type": "text", "text": f"""Analyze this {duration:.1f}s product video. Brand container is {container}.
Image 1 is the brand reference we want to put on the bottles/products.

Output JSON with THREE sections — analysis, screening, AND brand feasibility:
{{
  "scene": "brief description",
  "scene_type": "static|pouring|handheld",
  "camera_movement": "...",
  "lighting": "...",
  "product_placement": "...",
  "original_subtitle": "text visible in the video, if any",
  "i2v_prompt": "2-3 sentence English prompt for i2v. Camera motion, lighting, atmosphere. NO brand names. NO Chinese.",
  "negative_prompt": "...",
  "screening": {{
    "overlay_coverage_pct": 0-100,
    "overlay_types": ["watermark", "subtitle", "username"],
    "overlay_texts": ["exact text..."],
    "has_face": false,
    "face_coverage_pct": 0,
    "verdict": "PASS|WARN|REJECT",
    "reject_reasons": []
  }},
  "brand_feasibility": {{
    "bottle_size": 0-10,
    "label_visibility": 0-10,
    "bottle_count": 0-10,
    "lighting": 0-10,
    "obstruction": 0-10,
    "overall_score": 0-10,
    "verdict": "FEASIBLE|RISKY|NOT_FEASIBLE",
    "reason": "one line"
  }}
}}

Screening: overlay>40%→REJECT, face>30%→REJECT
Feasibility: overall<4=NOT_FEASIBLE, 4-6=RISKY, >6=FEASIBLE"""})

    # Use pro model for analysis (text-only task, more reliable than flash-image)
    cv = gemini_api(content, retries=3, model="gemini-3.1-pro-preview")
    analysis = _parse_json(cv) if cv else {}

    if not analysis.get("scene"):
        # Retry with flash-image as fallback
        cv = gemini_api(content, retries=2)
        analysis = _parse_json(cv) if cv else {}

    if not analysis.get("scene"):
        # Analysis failed → ASSUME watermarks exist (safe default).
        print(f"    ⚠️ Analysis fallback (API parse failed) — assuming watermarks present")
        analysis = {
            "scene": "product scene (fallback)", "scene_type": "static",
            "camera_movement": "slow push", "lighting": "warm",
            "product_placement": "on table", "original_subtitle": "",
            "i2v_prompt": "Cinematic product scene. Camera slowly pushes forward. Warm ambient lighting.",
            "negative_prompt": "rapid movement, text, watermark",
            "screening": {
                "verdict": "WARN",
                "overlay_coverage_pct": 15,
                "overlay_types": ["watermark", "subtitle"],
                "overlay_texts": ["(analysis failed — assuming overlays present)"],
                "analysis_failed": True,
            },
            "brand_feasibility": {"overall_score": 5, "verdict": "RISKY", "reason": "analysis unavailable"},
        }

    analysis["duration"] = duration
    analysis["resolution"] = f"{width}x{height}"

    scr = analysis.get("screening", {})
    if min(width, height) < 480:
        scr["verdict"] = "REJECT"
        scr.setdefault("reject_reasons", []).append(f"Resolution too low ({width}x{height})")
    if duration < 3:
        scr["verdict"] = "REJECT"
        scr.setdefault("reject_reasons", []).append(f"Too short ({duration:.1f}s)")
    analysis["screening"] = scr

    return analysis


def _parse_json(cv):
    text = cv if isinstance(cv, str) else " ".join(p.get("text", "") for p in cv if p.get("type") == "text")
    depth = 0
    start = -1
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0: start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i+1])
                except:
                    continue
    return {}


# ═══════════════════════════════════════════
# Phase 2: Watermark removal
# ═══════════════════════════════════════════

def remove_watermarks(vid_id, frame_path, screening, out_dir, force=False):
    """
    Remove ALL text overlays from a frame. Three-step strategy:
    
    Step 1: Gemini inpaint — ALWAYS runs. Removes all visible text/watermarks/subtitles.
            Does NOT depend on Phase 1 analysis. Uses the raw frame directly.
    Step 2: Verify — check if text remains. If yes, retry with specific targets.
    Step 3: ffmpeg crop — ALWAYS runs on top of Step 1 result. Removes platform logo zones.
    """
    clean_path = str(out_dir / f"{vid_id}_clean.png")
    working_frame = frame_path

    # ── Step 1: Text removal (ALWAYS runs — independent of analysis) ──
    # Dual-image mode: pass same frame twice to bypass VCE single-image bug.
    clean_data = None
    print(f"  🧹 Step 1: Gemini text removal (dual-image)...")
    clean_data = gemini_edit(
        "Remove ALL Chinese text overlays, subtitles, and watermarks from the second image. "
        "Keep everything else. Fill removed areas with background.",
        frame_path, frame_path,
        retries=5
    )

    if clean_data and len(clean_data) > 10000:
        with open(clean_path, "wb") as f:
            f.write(clean_data)
        print(f"  ✅ Inpaint: {len(clean_data)//1024}KB")
        working_frame = clean_path

        # ── Step 2: Verify and retry if needed ──
        print(f"  🔍 Step 2: Verifying...")
        time.sleep(3)
        qc = gemini_json(
            "Check this image for ANY remaining overlay text (subtitles, watermarks, platform logos, user IDs). "
            "Do NOT count text physically printed on product labels/bottles. "
            "JSON: {\"has_overlay_text\":true/false, \"remaining\":[\"exact text...\"], \"locations\":[\"where...\"]}",
            clean_path
        )

        if qc.get("has_overlay_text"):
            remaining = qc.get("remaining", [])
            print(f"  ⚠️ Residue: {remaining}")
            # Retry with specific targets
            if remaining:
                print(f"  🔄 Retry: targeting specific text...")
                time.sleep(5)
                targets = ", ".join(remaining[:3])
                retry_data = gemini_edit(
                    f"Remove these texts from the second image: {targets}. Fill with background.",
                    clean_path, clean_path,
                )
                if retry_data and len(retry_data) > 10000:
                    retry_path = str(out_dir / f"{vid_id}_clean2.png")
                    with open(retry_path, "wb") as f:
                        f.write(retry_data)
                    print(f"  ✅ Retry: {len(retry_data)//1024}KB")
                    working_frame = retry_path
        else:
            print(f"  ✅ Verified clean")
    else:
        print(f"  ⚠️ Inpaint failed (no output or too small)")
        # Even if inpaint fails, we still have crop below

    # ── Step 3: ffmpeg crop — ALWAYS runs ──
    # If inpaint succeeded: light crop (top 12% + bottom 5%) for logo zones only
    # If inpaint failed: aggressive crop (top 35% + bottom 5%) to cover subtitle zone too
    inpaint_succeeded = (working_frame != frame_path)
    if inpaint_succeeded:
        crop_top, crop_keep = 0.12, 0.83
        print(f"  🔧 Step 3: ffmpeg crop (top 12% + bottom 5% — light, inpaint handled text)...")
    else:
        crop_top, crop_keep = 0.35, 0.60
        print(f"  🔧 Step 3: ffmpeg crop (top 35% + bottom 5% — aggressive, inpaint failed)...")

    crop_path = str(out_dir / f"{vid_id}_cropped.png")
    subprocess.run([
        "ffmpeg", "-y", "-i", working_frame, "-vf",
        f"crop=iw:ih*{crop_keep}:0:ih*{crop_top},scale=720:1280:force_original_aspect_ratio=decrease,"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black",
        "-q:v", "1", crop_path
    ], capture_output=True)

    if os.path.exists(crop_path) and os.path.getsize(crop_path) > 10000:
        print(f"  ✅ Cropped: {os.path.getsize(crop_path)//1024}KB")
        return crop_path

    if working_frame != frame_path:
        return working_frame

    print(f"  ⚠️ All steps failed, using original")
    return frame_path


# ═══════════════════════════════════════════
# Phase 3: Brand frame edit
# ═══════════════════════════════════════════

def edit_brand_frame(vid_id, clean_frame, analysis, brand_ref, out_dir):
    scene_type = analysis.get("scene_type", "static")
    prompt = BRAND_PROMPTS.get(scene_type, BRAND_PROMPTS["static"])
    placement = analysis.get("product_placement", "on table")
    prompt += f"\nProduct placement: {placement}."

    branded_path = str(out_dir / f"{vid_id}_branded.png")
    brand_data = gemini_edit(prompt, brand_ref, clean_frame)
    if brand_data and len(brand_data) > 10000:
        with open(branded_path, "wb") as f:
            f.write(brand_data)
        return branded_path
    return None


# ═══════════════════════════════════════════
# Phase 4: Brand QC
# ═══════════════════════════════════════════

def qc_branded_frame(vid_id, branded_path, brand_config):
    brand_name = brand_config.get("name", "brand")
    qc = gemini_json(
        f"Check this image:\n"
        f"1. Is the brand '{brand_name}' or its label visible on any bottle/product?\n"
        f"2. Are there ANY remaining watermarks, logos, or text overlays?\n"
        f"JSON: {{\"brand_visible\":true/false, \"brand_confidence\":0-10, "
        f"\"has_watermark_residue\":true/false, \"watermark_details\":[\"...\"], "
        f"\"overall_pass\":true/false}}",
        branded_path
    )
    return qc


# ═══════════════════════════════════════════
# Phase 4.5: First-frame background variation
# ═══════════════════════════════════════════

# Background variation presets — each creates a visually distinct scene
# while keeping the product/bottle identical
BG_VARIATIONS = [
    {
        "name": "original",
        "prompt": None,  # skip — use branded frame as-is
    },
    {
        "name": "warm_wood",
        "prompt": (
            "Edit ONLY the background/surface in this image. "
            "Change the table/surface to warm dark wood grain. "
            "Add soft warm candlelight reflections. "
            "Keep ALL bottles, glasses, and products EXACTLY the same — same position, same label, same lighting on the product. "
            "Only the background and surface material should change."
        ),
    },
    {
        "name": "marble_bar",
        "prompt": (
            "Edit ONLY the background/surface. "
            "Change to a dark marble bar counter with subtle veining. "
            "Add a blurred bar shelf with colored bottles in the far background. "
            "Keep ALL products/bottles EXACTLY the same — same position, same label, same angle."
        ),
    },
    {
        "name": "outdoor_evening",
        "prompt": (
            "Edit ONLY the background. "
            "Change to an outdoor evening terrace scene — string lights overhead, blurred city lights in distance. "
            "Keep the surface/table and ALL products EXACTLY the same."
        ),
    },
    {
        "name": "cozy_fabric",
        "prompt": (
            "Edit ONLY the background/surface. "
            "Change the surface to a dark linen or velvet fabric texture. "
            "Background becomes a cozy dim room with warm bokeh lights. "
            "Keep ALL bottles and products EXACTLY the same."
        ),
    },
    {
        "name": "concrete_industrial",
        "prompt": (
            "Edit ONLY the background/surface. "
            "Change to a raw concrete surface with industrial aesthetic. "
            "Background: exposed brick wall, dim Edison bulbs. "
            "Keep ALL products EXACTLY the same."
        ),
    },
    {
        "name": "rainy_window",
        "prompt": (
            "Edit ONLY the background. "
            "Add a rain-streaked window behind the scene with blurred neon reflections. "
            "Keep the surface and ALL products EXACTLY the same."
        ),
    },
    {
        "name": "bookshelf",
        "prompt": (
            "Edit ONLY the background. "
            "Change background to a dim bookshelf with warm reading lamp glow. "
            "Keep surface and ALL products EXACTLY the same."
        ),
    },
    {
        "name": "neon_bar",
        "prompt": (
            "Edit ONLY the background. "
            "Add neon signs (warm amber/red tones) glowing in the blurred background. "
            "Dark moody bar atmosphere. "
            "Keep ALL products EXACTLY the same."
        ),
    },
]


def vary_first_frame(vid_id, branded_path, out_dir, variation_name=None):
    """
    Generate a background-varied version of the branded frame.
    The product stays identical; only background/surface changes.

    This is the most effective anti-duplicate layer because it creates
    genuinely different visual content that passes content-similarity checks.
    """
    if variation_name:
        var = next((v for v in BG_VARIATIONS if v["name"] == variation_name), None)
    else:
        # Random selection, excluding "original"
        var = random.choice([v for v in BG_VARIATIONS if v["prompt"]])

    if not var or not var["prompt"]:
        print(f"  🖼️ Background: original (no variation)")
        return branded_path, "original"

    print(f"  🖼️ Background variation: {var['name']}...")
    varied_path = str(out_dir / f"{vid_id}_bg_{var['name']}.png")

    varied_data = gemini_edit(var["prompt"], branded_path)
    if varied_data and len(varied_data) > 10000:
        with open(varied_path, "wb") as f:
            f.write(varied_data)
        print(f"  ✅ {len(varied_data)//1024}KB")
        return varied_path, var["name"]

    print(f"  ⚠️ Variation failed, using original")
    return branded_path, "original"


# ═══════════════════════════════════════════
# Phase 5: Prompt variation
# ═══════════════════════════════════════════

def vary_prompt(base_prompt):
    cam = random.choice(CAMERAS)
    light = random.choice(LIGHTINGS)
    atmos = random.choice(ATMOSPHERES)
    return f"{base_prompt.rstrip('.')}. {cam} {light} {atmos}"


# ═══════════════════════════════════════════
# Phase 6: Kling i2v
# ═══════════════════════════════════════════

def submit_kling(vid_id, frame_url, prompt, neg_prompt, duration):
    headers = {"Authorization": f"Bearer {KLING_KEY}", "Content-Type": "application/json"}
    full_neg = (neg_prompt or "blurry, text") + ", watermark, overlay text, subtitle, Chinese characters"

    # VCE uses flat format (image_url at top level); ablai uses image_list.
    # Try flat first, then image_list as fallback.
    flat_body = {
        "model_name": "kling-v3-omni",
        "prompt": prompt,
        "negative_prompt": full_neg,
        "aspect_ratio": "9:16",
        "duration": kling_duration(duration),
        "image_url": frame_url,
    }
    list_body = {
        "model_name": "kling-v3-omni",
        "prompt": prompt,
        "negative_prompt": full_neg,
        "aspect_ratio": "9:16",
        "duration": kling_duration(duration),
        "image_list": [{"image_url": frame_url, "type": "first_frame"}],
    }

    for label, body in [("flat", flat_body), ("list", list_body)]:
        try:
            r = http_session().post(f"{KLING_API}/kling/v1/videos/omni-video", headers=headers, json=body, timeout=60)
            d = r.json()
            tid = d.get("data", {}).get("task_id")
            if tid:
                return tid
            print(f"  ⚠️ {vid_id} submit ({label}): {str(d)[:120]}")
        except Exception as e:
            print(f"  ⚠️ {vid_id} submit ({label}): {e}")
    return None


def poll_kling(vid_id, task_id, out_dir, timeout_s=600):
    headers = {"Authorization": f"Bearer {KLING_KEY}"}
    session = http_session()

    for _ in range(timeout_s // 5):
        try:
            r = session.get(f"{KLING_API}/kling/v1/videos/omni-video/{task_id}", headers=headers, timeout=60)
            d = r.json()
            status = d.get("data", {}).get("task_status", "?")

            if status == "succeed":
                url = d["data"]["task_result"]["videos"][0]["url"]
                raw = str(out_dir / f"{vid_id}_raw.mp4")
                with open(raw, "wb") as f:
                    f.write(requests.Session().get(url, timeout=180).content)

                base_mp4 = str(out_dir / f"{vid_id}_base.mp4")
                subprocess.run(["ffmpeg", "-y", "-i", raw, "-c:v", "libx264", "-crf", "23",
                    "-preset", "fast", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
                    "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black",
                    base_mp4], capture_output=True)

                sz = os.path.getsize(base_mp4) // 1024
                dur = get_duration(base_mp4)
                return {"ok": True, "path": base_mp4, "size_kb": sz, "duration": dur}
            elif status == "failed":
                msg = d.get("data", {}).get("task_status_msg", "")
                return {"ok": False, "error": msg}
        except:
            pass
        time.sleep(5)

    return {"ok": False, "error": "timeout"}


# ═══════════════════════════════════════════
# Phase 7: Dedup
# ═══════════════════════════════════════════

def dedup_video(vid_id, video_path, out_dir):
    color_name = random.choice(list(DEDUP_COLORS.keys()))
    color_filter = DEDUP_COLORS[color_name]
    speed = round(random.uniform(0.95, 1.05), 3)
    cx, cy = random.randint(0, 8), random.randint(0, 8)
    crf = random.randint(21, 25)
    gop = random.randint(24, 72)

    deduped = str(out_dir / f"{vid_id}_deduped.mp4")
    filters = (
        f"setpts={1/speed}*PTS,"
        f"{color_filter},"
        f"crop={720-cx*2}:{1280-cy*2}:{cx}:{cy},"
        f"scale=720:1280:flags=lanczos"
    )
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path, "-vf", filters,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
        "-pix_fmt", "yuv420p", "-g", str(gop), "-an",
        "-movflags", "+faststart", deduped
    ], capture_output=True)

    info = {"color": color_name, "speed": speed, "crop": (cx, cy), "crf": crf, "gop": gop}
    return deduped, info


# ═══════════════════════════════════════════
# Phase 8: Audio
# ═══════════════════════════════════════════

def extract_and_mix_audio(vid_id, generated_video, reference_video, out_dir):
    gen_dur = get_duration(generated_video)

    ref_audio = f"/tmp/vbv_{vid_id}_ref_audio.wav"
    subprocess.run(["ffmpeg", "-y", "-i", reference_video, "-vn", "-ar", "44100", "-ac", "2", ref_audio],
                   capture_output=True)

    if not os.path.exists(ref_audio) or os.path.getsize(ref_audio) < 1000:
        print(f"  ⚠️ No audio in reference")
        return generated_video

    bgm_audio = f"/tmp/vbv_{vid_id}_bgm.wav"
    pitch_shift = round(random.uniform(0.92, 1.08), 3)

    subprocess.run([
        "ffmpeg", "-y", "-i", ref_audio, "-af",
        f"pan=stereo|c0=c0-0.5*c1|c1=c1-0.5*c0,"
        f"highpass=f=60,lowpass=f=12000,"
        f"asetrate=44100*{pitch_shift},aresample=44100,"
        f"loudnorm=I=-20:LRA=7:TP=-1",
        bgm_audio
    ], capture_output=True)

    if not os.path.exists(bgm_audio) or os.path.getsize(bgm_audio) < 1000:
        subprocess.run([
            "ffmpeg", "-y", "-i", ref_audio, "-af",
            f"asetrate=44100*{pitch_shift},aresample=44100,loudnorm=I=-20:LRA=7:TP=-1",
            bgm_audio
        ], capture_output=True)

    fitted_audio = f"/tmp/vbv_{vid_id}_fitted.wav"
    bgm_dur = get_duration(bgm_audio) if os.path.exists(bgm_audio) else 0

    if bgm_dur >= gen_dur:
        subprocess.run([
            "ffmpeg", "-y", "-i", bgm_audio, "-t", str(gen_dur),
            "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={gen_dur-1}:d=1",
            fitted_audio
        ], capture_output=True)
    else:
        loops = int(gen_dur / max(bgm_dur, 1)) + 1
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", str(loops), "-i", bgm_audio,
            "-t", str(gen_dur),
            "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={gen_dur-1}:d=1",
            fitted_audio
        ], capture_output=True)

    if not os.path.exists(fitted_audio) or os.path.getsize(fitted_audio) < 1000:
        return generated_video

    output = str(out_dir / f"{vid_id}_with_audio.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", generated_video, "-i", fitted_audio,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-movflags", "+faststart", output
    ], capture_output=True)

    if os.path.exists(output) and os.path.getsize(output) > 10000:
        print(f"  🎵 pitch={pitch_shift}x | -20dB | fade in/out")
        return output

    return generated_video


# ═══════════════════════════════════════════
# Phase 9: Copy engine
# ═══════════════════════════════════════════

def generate_copy(vid_id, original_subtitle, scene_desc, brand_config):
    anchor = brand_config.get("hashtag_anchor", "#Brand")
    emotion_tags = brand_config.get("emotion_tags", {})
    trend_tags = brand_config.get("trend_tags", ["#情绪稳定", "#成年人的快乐"])
    adaptations = brand_config.get("subtitle_adaptations", {})

    if not original_subtitle:
        original_subtitle = "独自喝酒的夜晚"

    # Classify emotion
    emotion_cat = "default"
    if any(w in original_subtitle for w in ["情绪", "不稳定", "emo", "糟糕", "难过"]):
        emotion_cat = "emo"
    elif any(w in original_subtitle for w in ["一个人", "独", "自己"]):
        emotion_cat = "solo"
    elif any(w in original_subtitle for w in ["放松", "解压", "奖励", "犒劳"]):
        emotion_cat = "relax"
    elif any(w in original_subtitle for w in ["朋友", "一起", "聚"]):
        emotion_cat = "social"

    tags = emotion_tags.get(emotion_cat, emotion_tags.get("default", ["#微醺"]))
    selected = random.sample(tags, min(3, len(tags)))
    selected += random.sample(trend_tags, min(2, len(trend_tags)))
    tag_str = "".join(selected) + anchor

    # Adapt subtitle
    subtitle = original_subtitle
    for key, val in adaptations.items():
        if key in original_subtitle:
            subtitle = val
            break
    if len(subtitle) > 20:
        subtitle = subtitle[:18] + "..."

    # Title hooks
    brand_name = brand_config.get("name", "Brand")
    product = brand_config.get("product", "product")
    hooks = [
        f"有些话说不出口 就让酒替你说{tag_str}",
        f"今天也辛苦了 值得这一杯{tag_str}",
        f"成年人的解压方式 不过一瓶{product}{tag_str}",
        f"夜深了 给自己倒一杯{tag_str}",
        f"不需要理由 只是想喝一杯{tag_str}",
    ]

    comments = [
        f"搜【{product}】这个真的太适合深夜喝了",
        f"搜【{brand_name}】被种草了🍺",
        f"搜【{brand_name}】第一次喝到这个味道",
    ]

    return {
        "scene_id": vid_id,
        "subtitle": subtitle,
        "title": random.choice(hooks),
        "comment_guide": random.choice(comments),
        "emotion": emotion_cat,
        "original_subtitle": original_subtitle,
    }


# ═══════════════════════════════════════════
# Phase 10: Subtitle overlay
# ═══════════════════════════════════════════

def overlay_subtitle(vid_id, video_path, subtitle_text, out_dir, font_path=None):
    from PIL import Image, ImageDraw, ImageFont

    font_path = font_path or DEFAULT_FONT

    tmp_dir = f"/tmp/vbv_{vid_id}_frames"
    os.makedirs(tmp_dir, exist_ok=True)
    for f in os.listdir(tmp_dir):
        os.remove(os.path.join(tmp_dir, f))

    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-q:v", "2", f"{tmp_dir}/f%04d.jpg"],
                   capture_output=True)

    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "stream=r_frame_rate",
        "-of", "csv=p=0", video_path], capture_output=True, text=True)
    try:
        fn, fd = map(int, r.stdout.strip().split("\n")[0].split("/"))
        fps = fn / fd
    except:
        fps = 24.0

    style = random.choice(SUBTITLE_STYLES)
    try:
        font = ImageFont.truetype(font_path, style["fontsize"])
    except:
        font = ImageFont.load_default()

    frames = sorted([f"{tmp_dir}/{f}" for f in os.listdir(tmp_dir) if f.endswith(".jpg")])
    delay_frames = int(fps * 0.5)

    for i, fp in enumerate(frames):
        if i < delay_frames:
            continue
        img = Image.open(fp)
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), subtitle_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (img.width - tw) // 2
        y = int(img.height * 0.35)

        for dx in [-2, -1, 0, 1, 2]:
            for dy in [-2, -1, 0, 1, 2]:
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), subtitle_text, font=font, fill=style["border"])
        draw.text((x, y), subtitle_text, font=font, fill=style["color"])
        img.save(fp, quality=95)

    has_audio = "Audio" in subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_streams", "-select_streams", "a", video_path],
        capture_output=True, text=True
    ).stdout

    final = str(out_dir / f"{vid_id}_final.mp4")

    if has_audio:
        tmp_audio = f"/tmp/vbv_{vid_id}_audio.aac"
        subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-c:a", "copy", tmp_audio],
                       capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-framerate", str(fps), "-i", f"{tmp_dir}/f%04d.jpg",
            "-i", tmp_audio, "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-movflags", "+faststart", final
        ], capture_output=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-framerate", str(fps), "-i", f"{tmp_dir}/f%04d.jpg",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", final
        ], capture_output=True)

    return final


# ═══════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════

def run_pipeline(video_path, brand_ref, brand_config, out_dir, font_path=None, force=False):
    """Run full pipeline on a single video. Returns result dict."""
    vid_id = Path(video_path).stem[:10]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Pipeline: {vid_id}")
    print(f"{'='*60}")

    # Phase 1
    print(f"\n  Phase 1: Analyze + Screen + Feasibility")
    first_frame = str(out_dir / f"{vid_id}_ref.jpg")
    subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-ss", "0.5",
        "-frames:v", "1", "-q:v", "1", first_frame], capture_output=True)

    analysis = analyze_and_screen(str(video_path), vid_id, brand_ref, brand_config)
    scr = analysis.get("screening", {})
    feas = analysis.get("brand_feasibility", {})

    print(f"    Scene: {analysis.get('scene', '?')[:50]}")
    print(f"    Screen: {scr.get('verdict', '?')} | Feasible: {feas.get('verdict', '?')} ({feas.get('overall_score', 0)}/10)")

    if scr.get("verdict") == "REJECT" and not force:
        return {"status": "rejected", "reason": "screening", "analysis": analysis}
    if feas.get("verdict") == "NOT_FEASIBLE" and not force:
        return {"status": "rejected", "reason": "brand_infeasible", "analysis": analysis}

    time.sleep(3)

    # Phase 2
    print(f"  Phase 2: Watermark Removal")
    clean = remove_watermarks(vid_id, first_frame, scr, out_dir)
    time.sleep(3)

    # Phase 3
    print(f"  Phase 3: Brand Frame Edit")
    branded = edit_brand_frame(vid_id, clean, analysis, brand_ref, out_dir)
    if not branded:
        return {"status": "failed", "fail_step": "brand_edit", "analysis": analysis}
    print(f"    ✅ {os.path.getsize(branded)//1024}KB")
    time.sleep(3)

    # Phase 4
    print(f"  Phase 4: Brand QC")
    qc = qc_branded_frame(vid_id, branded, brand_config)
    print(f"    Brand: {'✅' if qc.get('brand_visible') else '❌'} ({qc.get('brand_confidence', 0)}/10)")

    if not qc.get("overall_pass") and not qc.get("brand_visible"):
        print(f"    🔄 Retrying...")
        time.sleep(5)
        branded = edit_brand_frame(vid_id, clean, analysis, brand_ref, out_dir)
    time.sleep(3)

    # Phase 4.5: Background variation
    print(f"  Phase 4.5: Background Variation")
    varied_frame, bg_name = vary_first_frame(vid_id, branded, out_dir)
    time.sleep(3)

    # Phase 5 + 6
    print(f"  Phase 5-6: Prompt Variation + Kling i2v")
    varied = vary_prompt(analysis.get("i2v_prompt", "Cinematic product scene. Warm lighting."))
    frame_url = upload_catbox(varied_frame)
    tid = submit_kling(vid_id, frame_url, varied, analysis.get("negative_prompt", ""), analysis["duration"])
    if not tid:
        return {"status": "failed", "fail_step": "kling_submit", "analysis": analysis}

    print(f"    🎬 Task: {tid} ({kling_duration(analysis['duration'])}s)")
    result = poll_kling(vid_id, tid, out_dir)
    if not result["ok"]:
        return {"status": "failed", "fail_step": "kling_generate", "error": result["error"]}
    print(f"    ✅ {result['size_kb']}KB, {result['duration']:.1f}s")

    # Phase 7
    print(f"  Phase 7: Dedup")
    deduped, dedup_info = dedup_video(vid_id, result["path"], out_dir)

    # Phase 8
    print(f"  Phase 8: Audio")
    with_audio = extract_and_mix_audio(vid_id, deduped, str(video_path), out_dir)

    # Phase 9
    print(f"  Phase 9: Copy Engine")
    copy = generate_copy(vid_id, analysis.get("original_subtitle", ""), analysis.get("scene", ""), brand_config)
    print(f"    Subtitle: {copy['subtitle']}")
    print(f"    Title: {copy['title'][:60]}...")

    # Phase 10
    print(f"  Phase 10: Subtitle Overlay")
    final = overlay_subtitle(vid_id, with_audio, copy["subtitle"], out_dir, font_path)
    print(f"    ✅ {os.path.getsize(final)//1024}KB")

    dedup_info["background"] = bg_name

    return {
        "status": "complete",
        "final_path": final,
        "copy": copy,
        "dedup_info": dedup_info,
        "brand_qc": qc,
        "video": result,
        "analysis": analysis,
    }


def main():
    parser = argparse.ArgumentParser(description="Viral Brand Video Pipeline")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Process a single video")
    p_run.add_argument("--brand-ref", required=True, help="Brand reference image")
    p_run.add_argument("--brand-config", help="Brand config JSON")
    p_run.add_argument("--input", required=True, help="Input video")
    p_run.add_argument("--output", default="output", help="Output directory")
    p_run.add_argument("--font", help="Font path for subtitles")

    # batch
    p_batch = sub.add_parser("batch", help="Process all videos in a directory")
    p_batch.add_argument("--brand-ref", required=True)
    p_batch.add_argument("--brand-config")
    p_batch.add_argument("--input-dir", required=True)
    p_batch.add_argument("--output", default="output")
    p_batch.add_argument("--font")

    # screen
    p_screen = sub.add_parser("screen", help="Screen videos without generating")
    p_screen.add_argument("--brand-ref", required=True)
    p_screen.add_argument("--brand-config")
    p_screen.add_argument("--input-dir", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if not GEMINI_API or not GEMINI_KEY:
        print("❌ Set VBV_GEMINI_API and VBV_GEMINI_KEY")
        sys.exit(1)
    if args.command != "screen" and (not KLING_API or not KLING_KEY):
        print("❌ Set VBV_KLING_API and VBV_KLING_KEY")
        sys.exit(1)

    brand_config = load_brand_config(getattr(args, "brand_config", None))

    if args.command == "run":
        result = run_pipeline(args.input, args.brand_ref, brand_config,
                              args.output, getattr(args, "font", None))
        print(f"\n📦 Result: {result['status']}")
        if result["status"] == "complete":
            print(f"   Video: {result['final_path']}")
            print(f"   Title: {result['copy']['title']}")

    elif args.command == "batch":
        videos = sorted(Path(args.input_dir).glob("*.mp4"))
        print(f"🎬 Batch: {len(videos)} videos")
        results = {}
        for vf in videos:
            vid_id = vf.stem[:10]
            r = run_pipeline(str(vf), args.brand_ref, brand_config,
                             args.output, getattr(args, "font", None))
            results[vid_id] = r
            if r["status"] == "complete":
                # Remove large nested data for JSON serialization
                r.pop("analysis", None)

        with open(str(Path(args.output) / "batch_results.json"), "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n📊 Results saved to {args.output}/batch_results.json")

    elif args.command == "screen":
        videos = sorted(Path(args.input_dir).glob("*.mp4"))
        print(f"🔍 Screening {len(videos)} videos\n")
        for vf in videos:
            vid_id = vf.stem[:10]
            a = analyze_and_screen(str(vf), vid_id, args.brand_ref, brand_config)
            scr = a.get("screening", {})
            feas = a.get("brand_feasibility", {})
            status = "✅" if feas.get("verdict") == "FEASIBLE" else "⚠️" if scr.get("verdict") != "REJECT" else "❌"
            print(f"  {status} {vid_id}: screen={scr.get('verdict','?')} feasible={feas.get('verdict','?')} ({feas.get('overall_score',0)}/10) — {feas.get('reason','')[:50]}")
            time.sleep(3)


if __name__ == "__main__":
    main()
