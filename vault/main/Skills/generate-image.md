---
title: Generate Image
description: Standard procedure for generating images for publications. Covers Gemini nano-banana, local scripts, hosting via catbox.moe, and dimension conventions per use case.
type: skill
created: 2026-04-10
updated: 2026-04-10
trigger: "when a routine or pipeline step needs to generate an image (cover, illustration, social card) — use /generate-image or reference this skill"
tags: [skill, image, generation, gemini, nano-banana]
---

# Generate Image

Canonical procedure for generating images used in Notion pages, social posts, and other publications. Standardizes tool selection, prompt engineering, dimensions, and hosting.

## Tool selection

**Default: Gemini 2.5 Flash Image ("nano-banana")** via `GEMINI_API_KEY_NANO_BANANA` in `vault/.env`.

| Tool | When to use |
|------|-------------|
| Gemini nano-banana (API) | General-purpose image generation, fast, good quality |
| Local Python script (e.g., `generate-ta-cover.py`) | Template-based images with dynamic data (charts, overlays, fixed layouts) |
| Reuse existing asset | When the content already has a suitable image (e.g., WP featured media in palmeiras-feed) |

**Decision rule:** if the image is a fixed-layout template with dynamic text/data overlays → use a local script. If it's a free-form illustration → use Gemini.

## Prerequisites

Read from `vault/.env`:
- `GEMINI_API_KEY_NANO_BANANA` — primary key for image generation
- `GEMINI_API_KEY_SKILLS` — secondary/fallback key

## Input contract

- `prompt` (string, required) — description of the image
- `aspect_ratio` (string, default "16:9") — target shape
- `output_path` (string, required) — local path to save the image (e.g., `/tmp/cover-{timestamp}.jpg`)
- `style_hint` (string, optional) — artistic direction (e.g., "photorealistic", "minimalist vector", "retro synthwave")
- `upload_to_catbox` (bool, default True) — whether to upload to catbox.moe and return a public URL

## Procedure

### Step 1 — Load API key

```python
import os, json, urllib.request, base64
from pathlib import Path

env = {}
env_path = Path.home() / "claude-bot" / "vault" / ".env"
for line in env_path.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

GEMINI_KEY = env.get("GEMINI_API_KEY_NANO_BANANA") or env.get("GEMINI_API_KEY_SKILLS")
if not GEMINI_KEY:
    raise RuntimeError("No Gemini API key available in vault/.env")
```

### Step 2 — Enhance the prompt

Raw prompts from routines are often too short. Apply the enhancement checklist:

1. **Subject** — what is the main element (BTC chart, football stadium, abstract shape, etc.)
2. **Composition** — close-up, wide shot, overhead, etc.
3. **Style** — photorealistic, illustration, vector, 3D render, retro, etc.
4. **Color palette** — dominant colors (e.g., "green and gold for Palmeiras", "orange and black for crypto")
5. **Lighting** — dramatic, soft, neon, daylight
6. **Mood** — professional, energetic, calm, aggressive
7. **Negative constraints** — "no text", "no logos", "no watermarks", "landscape orientation"

**Good prompt template:**

> A [subject] in [composition], [style], with [color palette] and [lighting]. Mood: [mood]. [negative constraints].

**Example (crypto cover):**

> A stylized Bitcoin chart with a clear bullish trend, wide landscape composition, 3D render in orange and black neon, dramatic lighting from below. Mood: professional and energetic. No text, no watermarks, 16:9 aspect ratio, landscape orientation.

**Example (Palmeiras post):**

> Allianz Parque stadium at night during a Palmeiras match, wide aerial composition, photorealistic, dominant colors deep green and white, dramatic stadium lighting. Mood: epic and passionate. No text, 16:9 aspect ratio.

### Step 3 — Call Gemini API

```python
endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent?key={GEMINI_KEY}"

payload = {
    "contents": [{
        "parts": [{"text": enhanced_prompt}]
    }],
    "generationConfig": {
        "responseModalities": ["IMAGE"],
        "imageConfig": {"aspectRatio": aspect_ratio},
    },
}

req = urllib.request.Request(
    endpoint,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read())

# Extract base64 image from response
parts = result["candidates"][0]["content"]["parts"]
image_b64 = None
for part in parts:
    if "inlineData" in part:
        image_b64 = part["inlineData"]["data"]
        break

if not image_b64:
    raise RuntimeError(f"Gemini did not return an image: {result}")

Path(output_path).write_bytes(base64.b64decode(image_b64))
```

**API version note:** Gemini endpoints change. If `gemini-2.5-flash-image-preview` 404s, check Google AI Studio for the current image model ID.

### Step 4 — Post-process (optional)

Common post-processing steps:

- **Resize** — use Pillow or ffmpeg to fit exact dimensions (see dimensions table below)
- **Compress** — target <500KB for Notion page performance
- **Generate thumbnail** — 600×400 for Telegram previews

```python
# Using ffmpeg (no pip dependencies)
import subprocess
subprocess.run([
    "ffmpeg", "-y", "-i", output_path,
    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
    "-q:v", "3",
    output_path.replace(".", "-resized."),
], check=True, capture_output=True)
```

### Step 5 — Upload to catbox.moe

Catbox.moe is the standard hosting service used by existing pipelines (see `crypto-ta-analise/steps/cover.md`). Free, permanent, no auth.

```bash
IMAGE_URL=$(curl -s -F "reqtype=fileupload" -F "fileToUpload=@/tmp/cover.jpg" https://catbox.moe/user/api.php)
```

The response is the raw URL (plain text, no JSON). If it doesn't start with `https://`, it failed — the response will contain an error message.

**Fallback hosts** (if catbox.moe is down):
- `litterbox.catbox.moe` (temporary, 1h-72h expiration) — for short-lived use
- Local file hosting via bot HTTP server (not implemented yet)

### Step 6 — Return result

Return a dict:

```python
{
    "local_path": "/tmp/cover-1234.jpg",
    "public_url": "https://files.catbox.moe/abc123.jpg",
    "width": 1920,
    "height": 1080,
    "size_bytes": 456789,
    "prompt": enhanced_prompt,
}
```

## Dimension conventions

Standardize on these sizes across all pipelines:

| Use case | Dimensions | Aspect ratio | Notes |
|----------|-----------|--------------|-------|
| Notion page cover | 1500×600 | 2.5:1 | Notion's recommended cover ratio |
| Crypto TA cover | 1080×694 | ~16:10 | Legacy from `generate-ta-cover.py` |
| Social post (landscape) | 1200×675 | 16:9 | X, Threads, Facebook |
| Social post (square) | 1080×1080 | 1:1 | Instagram, fallback |
| Social post (portrait) | 1080×1350 | 4:5 | Instagram vertical |
| Telegram thumbnail | 600×400 | 3:2 | Telegram preview cards |
| Article inline | 800×450 | 16:9 | In-article illustrations |

## Error handling

| Symptom | Cause | Action |
|---------|-------|--------|
| 401 Unauthorized | Invalid Gemini key | Notify user, check `.env`, abort |
| 429 Rate limit | Too many requests | Wait 60s, retry once. If still failing, abort |
| 400 Bad Request | Prompt violated safety filter | Log full response, try sanitized prompt, then abort |
| 500/503 | Gemini downtime | Retry with exponential backoff (3 attempts, 2/4/8s) |
| Empty response | Model refused or timeout | Try fallback key, then abort |
| catbox upload fails | Service down | Try litterbox, otherwise return local path only with warning |
| Generated image is NSFW/off-topic | Prompt ambiguity | Refine prompt, retry once |

**All errors visible** — log and notify user. On unrecoverable failure, return a placeholder image URL (e.g., a solid color with title text via local Pillow) rather than breaking the pipeline.

## Prompt safety

Gemini has safety filters. To avoid rejections:
- Avoid proper names of real people (use generic descriptions)
- Avoid political/religious symbols unless essential
- Avoid explicit violence, even for historical contexts
- For sports: "a football player in green and white" is safer than naming specific players

If the use case requires a real person's likeness (e.g., "Abel Ferreira celebrating"), prefer reusing existing photos via `Skills/fetch-web.md` (WP featured media cascade) over generation.

## Notes

- **Cost awareness**: Gemini image generation is cheap (~$0.02/image) but not free. Don't generate speculatively — only when the pipeline will actually publish.
- **Caching**: for repeated prompts (e.g., fallback assets), cache in `/tmp/image-cache/{prompt-hash}.jpg` and reuse for 24h.
- **Compliance**: Generated images used publicly should not impersonate public figures or brand logos.
- Reference implementations: `crypto-bro/Routines/crypto-ta-analise/scripts/cover_v2.py`, `crypto-bro/scripts/generate-ta-cover.py`
- For image selection from existing web sources (not generation), see `Skills/fetch-web.md` and the palmeiras-feed image cascade pattern
