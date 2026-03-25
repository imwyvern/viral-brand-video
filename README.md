# viral-brand-video

> AI-powered branded short video generation from viral reference clips — with blue-word SEO for Douyin/TikTok.

## What It Does

Turn trending short videos (with competitor brands) into your own branded content:

1. **Analyze** — Scene classification, watermark detection, brand replacement feasibility scoring
2. **Clean** — 3-tier watermark removal (AI inpaint → crop → fallback)
3. **Replace** — AI brand label replacement (scene-aware: static/pouring/handheld)
4. **Generate** — Kling i2v video generation from branded first frame
5. **Deduplicate** — 6-layer pixel/encoding variation for multi-account publishing
6. **Audio** — Extract reference BGM, remove vocals, pitch-shift for copyright safety
7. **Copy** — Emotion-classified subtitles + blue-word hashtag titles + comment guides
8. **Deliver** — Platform-ready 9:16 video with subtitle overlay

## Quick Start

```bash
# Set API keys
export VBV_GEMINI_API=https://your-gemini-endpoint
export VBV_GEMINI_KEY=sk-xxx
export VBV_KLING_API=https://your-kling-endpoint
export VBV_KLING_KEY=sk-xxx

# Single video
python3 scripts/pipeline.py run \
  --brand-ref my_label.jpg \
  --brand-config brand.json \
  --input trending_video.mp4 \
  --output output/

# Batch
python3 scripts/pipeline.py batch \
  --brand-ref my_label.jpg \
  --brand-config brand.json \
  --input-dir videos/ \
  --output output/

# Screen only (no video generation)
python3 scripts/pipeline.py screen \
  --brand-ref my_label.jpg \
  --input-dir videos/
```

## Brand Config

```json
{
  "name": "YourBrand",
  "product": "Craft Beer",
  "container": "glass_bottle",
  "hashtag_anchor": "#CraftBeerYourBrand",
  "emotion_tags": {
    "emo": ["#latenight", "#mood"],
    "solo": ["#alone", "#relax"]
  },
  "subtitle_adaptations": {
    "negative_word": "positive_replacement"
  }
}
```

## Requirements

- Python 3.8+
- ffmpeg (with ffprobe)
- Pillow (`pip install Pillow requests`)
- Gemini API access (image editing)
- Kling API access (video generation)

## Cost

~¥0.6-0.8 per video (~$0.08-0.11). Gemini calls for analysis/editing + Kling for video generation.

## As an Agent Skill

This is an [OpenClaw](https://github.com/openclaw/openclaw) / [Codex](https://github.com/openai/codex) compatible skill. Install to your skills directory and the agent will use it when you ask about brand video generation.

## License

MIT

---

## 🇨🇳 中文说明

将抖音爆款视频（竞品品牌）→ AI 品牌替换 + 视频生成 + 蓝词 SEO 标题 → 输出可直接发布的品牌短视频。

**核心能力：**
- 10 步自动化管线（分析→去水印→品牌替换→QC→视频生成→去重→音频→文案→字幕→交付）
- 蓝词策略（情绪蓝词 + 场景蓝词 + 趋势蓝词 + 品牌锚定）
- 6 层去重（支持多账号矩阵发布）
- 参考视频 BGM 复用（去人声 + 变调）
- 每条视频成本 ~¥0.6-0.8
