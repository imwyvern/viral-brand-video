# Pipeline Phases — Technical Reference

Complete technical documentation for all 10 pipeline phases.

## Table of Contents

1. [Phase 1: Analyze + Screen + Feasibility](#phase-1)
2. [Phase 2: Watermark Removal](#phase-2)
3. [Phase 3: Brand Frame Edit](#phase-3)
4. [Phase 4: Brand QC](#phase-4)
5. [Phase 5: Prompt Variation](#phase-5)
6. [Phase 6: Video Generation](#phase-6)
7. [Phase 7: Deduplication](#phase-7)
8. [Phase 8: Background Audio](#phase-8)
9. [Phase 9: Copy Engine](#phase-9)
10. [Phase 10: Subtitle Overlay](#phase-10)

---

## Phase 1: Analyze + Screen + Feasibility {#phase-1}

### Input
- 3 frames extracted at 10%/40%/80% of video duration (512px wide)
- Brand reference image

### Gemini Prompt Structure

One API call produces all three outputs: scene analysis, content screening, brand feasibility.

### Output JSON Schema
```json
{
  "scene": "description",
  "camera_movement": "slow push / static / orbit...",
  "lighting": "warm / cool / neon...",
  "product_placement": "on table / in hand / background...",
  "original_subtitle": "Chinese text visible in video",
  "i2v_prompt": "2-3 sentence English prompt. NO brand names. NO Chinese.",
  "negative_prompt": "blurry, text, watermark...",
  "screening": {
    "overlay_coverage_pct": 0-100,
    "overlay_types": ["watermark", "subtitle", "username"],
    "overlay_texts": ["exact text..."],
    "has_face": false,
    "face_coverage_pct": 0,
    "verdict": "PASS|WARN|REJECT",
    "reject_reasons": []
  },
  "brand_feasibility": {
    "bottle_size": 0-10,
    "label_visibility": 0-10,
    "bottle_count": 0-10,
    "lighting": 0-10,
    "obstruction": 0-10,
    "overall_score": 0-10,
    "verdict": "FEASIBLE|RISKY|NOT_FEASIBLE",
    "reason": "one-line explanation"
  }
}
```

### Hard Screening Rules
| Condition | Result |
|-----------|--------|
| overlay_coverage > 40% | REJECT |
| face_coverage > 30% | REJECT |
| Resolution < 480p | REJECT |
| Duration < 3s | REJECT |

### Feasibility Scoring
| Dimension | 0 (worst) | 10 (best) |
|-----------|-----------|-----------|
| bottle_size | Tiny dot | Full-frame close-up |
| label_visibility | Pitch black | Crystal clear text |
| bottle_count | 5+ bottles | Single bottle |
| lighting | Backlit/silhouette | Even, bright |
| obstruction | Mostly blocked | Fully visible |

- **< 4**: NOT_FEASIBLE → skip (saves downstream API cost)
- **4-6**: RISKY → attempt, strict QC
- **> 6**: FEASIBLE → proceed

---

## Phase 2: Watermark Removal {#phase-2}

### 3-Tier Strategy (always runs)

**Tier 1: AI Inpaint**
- Gemini edit with specific text targets from Phase 1
- Post-verification: second Gemini call confirms removal
- Accept only if verification passes

**Tier 2: ffmpeg Crop**
```bash
ffmpeg -i input.jpg -vf \
  "crop=iw:ih*0.83:0:ih*0.12,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black" \
  output.png
```
- Removes top 12% (platform logo zone) + bottom 5% (watermark zone)
- Guaranteed to remove fixed-position overlays

**Tier 3: Original frame (fallback)**

---

## Phase 3: Brand Frame Edit {#phase-3}

### Scene-Specific Prompts

| Scene Type | Prompt Strategy |
|------------|-----------------|
| static | Replace LARGEST/MOST VISIBLE bottle label. Match curvature, perspective, lighting. |
| pouring | Replace brand on the pouring bottle. Keep action intact. |
| handheld | If bottle visible → replace label. If only glasses → place branded bottle on nearest surface. |

### Dual-Image Mode
- Image 1: Brand reference (target label)
- Image 2: Cleaned frame from Phase 2
- Model: Gemini 3.1 Flash Image Preview

---

## Phase 4: Brand QC {#phase-4}

### Checks
```json
{
  "brand_visible": true,
  "brand_confidence": 0-10,
  "has_watermark_residue": true/false,
  "watermark_details": ["remaining items..."],
  "overall_pass": true/false
}
```

### Retry Logic
1. brand_visible=false + confidence<4 → retry with stronger prompt
2. has_watermark_residue=true → re-run Phase 2 Tier 2 → re-run Phase 3
3. Two failures → mark as failed, skip

---

## Phase 5: Prompt Variation {#phase-5}

### Pool Dimensions

**Camera (7):**
- Slowly pushes forward
- Static with natural sway
- Drifts right with slow pan
- Subtle crane upward
- Gentle pull back
- Slow orbit left
- Static with micro-tremor

**Lighting (7):**
- Warm amber candlelight
- Soft golden hour
- Neon-tinted warm glow
- Dim moody tungsten
- Warm string light bokeh
- Cool blue ambient with warm key
- Firelight flicker

**Atmosphere (7):**
- Cozy intimate
- Melancholic peaceful
- Relaxed late-night
- Cinematic shallow focus
- Quiet contemplative
- Dreamy soft-focus haze
- Raw emotional solitude

**Format:** `{base_prompt}. {camera}. {lighting}. {atmosphere}.`
**Combinations:** 7×7×7 = 343

---

## Phase 6: Video Generation {#phase-6}

### Kling i2v Configuration
| Parameter | Value |
|-----------|-------|
| Model | kling-v3-omni |
| Aspect | 9:16 |
| First frame | Branded frame from Phase 3 |
| Duration | 5s (ref ≤6s) / 10s (ref ≤11s) / 15s (ref >11s) |
| Negative | blurry, text, watermark, subtitle, Chinese characters, overlay |

### Post-processing
```bash
ffmpeg -i raw.mp4 -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p \
  -an -movflags +faststart \
  -vf "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black" \
  base.mp4
```

---

## Phase 7: Deduplication {#phase-7}

### 6 Layers

| Layer | Parameter | Range | Purpose |
|-------|-----------|-------|---------|
| 1 | Prompt variation | 343 combos | Content-level |
| 2 | Color shift | 8 presets | Color fingerprint |
| 3 | Speed | ±5% (0.95-1.05x) | Frame timing |
| 4 | Crop | 0-8px per edge | Pixel offset |
| 5 | CRF | 21-25 | Compression fingerprint |
| 6 | GOP | 24-72 | Keyframe structure |

### Color Presets
```python
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
```

---

## Phase 8: Background Audio {#phase-8}

### Processing Chain
```
Reference video → extract WAV 44.1kHz stereo
  → Remove center vocals: pan=stereo|c0=c0-0.5*c1|c1=c1-0.5*c0
  → Band filter: highpass=60Hz, lowpass=12kHz
  → Pitch shift: asetrate×(0.92-1.08 random)
  → Normalize: loudnorm I=-20 LRA=7 TP=-1
  → Duration fit: trim+fade (long) or loop (short)
  → Fade: in 0.5s, out 1s
  → Mix: -c:a aac -b:a 128k
```

### Why Reference BGM
| Alternative | Problem |
|-------------|---------|
| Silent | Platform algorithms penalize; low completion rate |
| Music library | Extra API/licensing cost |
| AI music gen | Inconsistent quality, may not match scene |
| **Reference BGM** | Already scene-matched, zero extra cost |

### Fallback
1. No audio in reference → keep silent
2. Vocal removal fails → original audio + pitch shift only
3. Mix fails → keep silent

---

## Phase 10: Subtitle Overlay {#phase-10}

### Parameters
| Parameter | Value |
|-----------|-------|
| Engine | Pillow frame-by-frame |
| Position | y = height × 35% (upper-middle) |
| Delay | 0.5s before appearing |
| Font | Configurable (`--font`), default STHeiti Medium |
| Size | 34-38px (random per video) |
| Colors | 6 presets (white/cream/bisque variants) |
| Stroke | 2px dark border |

### Audio Preservation
If input video has audio (from Phase 8), subtitle overlay extracts and re-mixes it:
```bash
# Extract audio
ffmpeg -i with_audio.mp4 -vn -c:a copy audio.aac
# Re-encode frames + audio
ffmpeg -framerate {fps} -i frames/%04d.jpg -i audio.aac \
  -c:v libx264 -c:a aac -shortest final.mp4
```
