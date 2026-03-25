# Blue-Word (蓝词) SEO Strategy for Douyin/TikTok

Blue words (蓝词) are clickable hashtag-like keywords that Douyin highlights in video titles,
enabling search discovery. Strategic use significantly boosts organic reach.

## What Are Blue Words

On Douyin, certain keywords in video titles turn blue and become clickable. When users tap them,
they're taken to a search results page for that term. This creates a direct SEO pathway:
video title → blue word → search results → more views.

Blue words work because Douyin's algorithm treats them as content signals, similar to how Google
treats meta keywords. Videos with well-chosen blue words get distributed to users searching
those terms.

## The Four-Step Method (挂说写评)

Based on [woshipm research](https://www.woshipm.com/operate/6255659.html):

| Step | Chinese | Action | Purpose |
|------|---------|--------|---------|
| 挂 | Hang | Attach product link/cart | Direct conversion |
| 说 | Speak | Mention brand in voiceover + subtitle | Audio+visual brand signal |
| 写 | Write | Brand name in title + TAG prefix | Search discovery |
| 评 | Comment | Seed comments with search prompts | Social proof + search behavior |

For non-e-commerce (pure traffic) videos, focus on 写 and 评.

## Title Structure

```
{emotional_hook}{#emotion_tag}{#scene_tag}{#trend_tag}{#brand_anchor}
```

### Tag Layers

| Layer | Position | Purpose | Examples |
|-------|----------|---------|----------|
| Emotion | Front | High search volume, broad reach | #微醺 #深夜emo |
| Scene | Middle | Precise audience matching | #一个人喝酒 #深夜小酌 |
| Trend | Supplement | Ride trending waves | #情绪稳定 #治愈系 |
| Brand Anchor | Tail | Brand+category combined | #CraftBeerBrandName |

### Rules
- **No spaces between tags**: `#tag1#tag2#tag3` (native Douyin format, better algorithm recognition)
- **Brand anchor always last**: Combined category + brand name in one tag
- **3-5 tags per title**: More gets truncated
- **Emotional hook first**: The non-tag text that creates curiosity/resonance

## Comment Seeding

Guide search behavior without direct links:

```
"搜【BrandName】this is perfect for late nights"
"搜【BrandName ProductType】just discovered this"
"Everyone asking in comments: where to buy this ProductType"
```

Pattern: `搜【keyword】+ authentic-sounding reaction`

## Emotion-Tag Mapping

The copy engine automatically classifies subtitle emotion and selects matching tags:

| Emotion | Trigger Words | Tag Pool |
|---------|---------------|----------|
| emo | mood, unstable, terrible, sad | #深夜emo #情绪出口 #治愈系 |
| solo | alone, by myself, solitude | #一个人喝酒 #独处 #解压 |
| relax | relax, decompress, reward | #深夜小酌 #解压好物 #下班喝一杯 |
| social | friends, together, gathering | #朋友聚会 #小酌 #周末 |

### Customization

Override in brand config:

```json
{
  "emotion_tags": {
    "emo": ["#custom_emo_tag", "#your_mood_tag"],
    "solo": ["#alone_time", "#your_brand_moment"]
  },
  "trend_tags": ["#trending_term_1", "#seasonal_tag"],
  "brand_anchor": "#ProductTypeBrandName"
}
```

## Blue Word Optimization Tips

1. **Low-view videos (<500) are more likely to trigger blue words** — the algorithm compensates
2. **Category + brand in one tag** beats separate tags for search indexing
3. **Emotion tags drive discovery**, brand anchor drives attribution
4. **Rotate 3-5 emotion/scene tags** per video for dedup + A/B testing
5. **Monitor which tags generate blue links** — not all tags turn blue; Douyin decides dynamically
