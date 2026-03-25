---
name: viral-brand-video
description: >
  Generate branded short videos from viral reference videos with AI-powered brand replacement,
  blue-word SEO titles, and platform-ready delivery. Use when: (1) creating branded short videos
  from trending/viral reference clips, (2) replacing brands/labels in product videos with a target
  brand, (3) generating Douyin/TikTok-optimized titles with blue-word tag strategy, (4) batch
  producing brand video content with deduplication for multi-account publishing, (5) user mentions
  brand video, viral video, label replacement, product placement AI, or blue-word/蓝词 strategy.
---

# Viral Brand Video

Turn trending short videos into branded content — AI replaces the product label, generates the video,
adds BGM + subtitles, and outputs platform-ready posts with blue-word SEO titles.

## Overview

```
Reference video (viral clip with competitor brand)
  → Analyze + Screen + Brand feasibility scoring
  → Remove watermarks (3-tier: AI inpaint → crop → original)
  → Replace brand label (scene-aware AI edit)
  → QC (brand visible + no watermark residue)
  → Generate video (Kling i2v from branded first frame)
  → Deduplicate (6-layer pixel/encoding variation)
  → Extract & mix BGM (from reference, vocals removed)
  → Generate copy (subtitle + title with blue-word tags + comment guide)
  → Overlay subtitle
  → Deliver: video + title + comment guide
```

## Setup

### Required API Keys

Set these environment variables or pass via `--config`:

```bash
export VBV_GEMINI_API=https://your-gemini-endpoint   # Gemini 3.1 Flash Image Preview
export VBV_GEMINI_KEY=sk-xxx
export VBV_KLING_API=https://your-kling-endpoint      # Kling v3-omni
export VBV_KLING_KEY=sk-xxx
```

### Required Files

1. **Brand reference image** — a clear photo of your product label/bottle/packaging
2. **Reference videos** — viral/trending short videos in your product category

### Brand Config

Create a brand config JSON (or pass `--brand` flags):

```json
{
  "name": "YourBrand",
  "product": "Craft Beer",
  "tagline": "Premium craft experience",
  "container": "glass_bottle",
  "hashtag_anchor": "#CraftBeerYourBrand",
  "scenes": ["solo drinking", "nightlife", "relaxation"],
  "subtitle_adaptations": {
    "negative_word": "positive_replacement"
  }
}
```

## Usage

```bash
# Single video — full pipeline
python3 scripts/pipeline.py run \
  --brand-ref brand_label.jpg \
  --brand-config brand.json \
  --input reference_videos/V01.mp4 \
  --output output/

# Batch — all videos in a directory
python3 scripts/pipeline.py batch \
  --brand-ref brand_label.jpg \
  --brand-config brand.json \
  --input-dir reference_videos/ \
  --output output/

# Analysis only — screen videos without generating
python3 scripts/pipeline.py screen \
  --brand-ref brand_label.jpg \
  --input-dir reference_videos/
```

## Pipeline Phases

**10 phases, each independently callable.** See `references/pipeline-phases.md` for full technical details.

### Phase 1: Analyze + Screen + Feasibility

Single Gemini call extracts scene description, i2v prompt, watermark detection, and brand replacement feasibility score (5 dimensions, 0-10).

Gate: `REJECT` if overlay >40%, face >30%, resolution <480p, duration <3s.
Gate: `NOT_FEASIBLE` if brand score <4 (e.g., no visible bottle, backlit silhouette).

### Phase 2: Watermark Removal (mandatory, 3-tier)

1. **AI inpaint** (Gemini) + verification → best quality
2. **ffmpeg crop** top 12% + bottom 5% → guaranteed logo removal
3. **Original** → last resort

### Phase 3: Brand Frame Edit

Scene-aware prompt (static/pouring/handheld) + dual-image mode (brand ref + clean frame).

### Phase 4: Brand QC

Checks brand visibility AND watermark residue. Auto-retry on failure.

### Phase 5: Prompt Variation

7 cameras × 7 lightings × 7 atmospheres = 343 unique combinations per scene.

### Phase 6: Video Generation (Kling i2v)

`kling-v3-omni`, 9:16, 5/10/15s based on reference duration.

### Phase 7: Deduplication (6-layer)

Color shift (8 presets) × speed (±5%) × crop (0-8px) × CRF (21-25) × GOP (24-72) × subtitle style.

### Phase 8: Background Audio

Extract BGM from reference → remove center-panned vocals → pitch shift ±8% → normalize -20dB → fade in/out → mix.

### Phase 9: Copy Engine (Blue-Word Strategy)

See `references/blue-word-strategy.md` for the complete Douyin blue-word SEO methodology.

- **Subtitle**: Adapt original video's subtitle — keep emotional core, make brand-friendly
- **Title**: `{emotional hook}{#emotion tag}{#scene tag}{#trend tag}{#brand anchor}`
- **Comment guide**: Search-inducing phrases (`搜【YourBrand】...`)

### Phase 10: Subtitle Overlay

Pillow frame-by-frame rendering. Position: upper-middle (y=35%). Preserves audio track.

## Output

```
output/
├── {id}_ref.jpg            # Reference frame
├── {id}_clean.png          # Watermark-removed frame
├── {id}_branded.png        # Brand-replaced frame
├── {id}_base.mp4           # Kling output (720×1280)
├── {id}_final.mp4          # Final video (subtitle + BGM)
└── batch_results.json      # All results with copy
```

Each entry in `batch_results.json`:
```json
{
  "status": "complete",
  "copy": {
    "subtitle": "Tonight, just this one glass",
    "title": "Some words only alcohol understands#mood#nightcap#craft beer#CraftBeerYourBrand",
    "comment_guide": "Search【YourBrand】perfect for late nights"
  },
  "dedup_info": {"color": "golden", "speed": 1.03, "crf": 22},
  "brand_qc": {"brand_visible": true, "brand_confidence": 9}
}
```

## Cost

~¥0.6-0.8 per video (~$0.08-0.11). 100 videos/month ≈ ¥60-80.

| Phase | API Calls | Cost |
|-------|-----------|------|
| Analyze + Screen | 1× Gemini | ~$0.01 |
| Watermark removal | 1-2× Gemini | ~$0.01-0.02 |
| Brand edit + QC | 2× Gemini | ~$0.015 |
| Video generation | 1× Kling | ~¥0.3 |
| Audio/subtitle/dedup | Local (ffmpeg/Pillow) | Free |

## Limitations

- Dark/backlit scenes have low brand replacement success (~30%)
- Multi-bottle scenes: AI may only replace one bottle
- Vocal removal is imperfect (center-pan trick, side vocals leak)
- macOS font dependency (STHeiti Medium) — configure `--font` for other OS
