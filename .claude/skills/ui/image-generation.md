# image-generation.md — Real AI Image Mockups (Optional Power-Up)

**Read this only if `recipes/mockups.md` device-frame + primitive composition isn't enough.** For 90% of builds, the device-frame approach wins on speed, control, and zero API cost. This file covers the cases where you genuinely want a generated image.

---

## When this is worth it

- Hero needs a **real product photo** (physical product: hardware, packaging, fashion, food)
- Site has budget for ongoing image-gen API spend (~$0.01-$0.10 per image)
- You need a hero photograph that doesn't exist in stock libraries (`assets/backgrounds/`, `picsum.photos`)
- The product is unique/unphotographed and a freeform render adds real value

## Don't bother if

- It's an MVP / you just need a placeholder → use `picsum.photos/seed/{slug}/{w}/{h}`
- The product is a web app → use `recipes/mockups.md` `BrowserFrame` + primitives. Generated dashboards still look fake.
- You don't have an API key set up
- The brand needs reproducibility (image gen is non-deterministic — same prompt twice = different output)

---

## Three providers, ranked

### 1. fal.ai — fastest, cheapest, recommended default

- ~1-3 seconds per image, $0.003-$0.05/image
- Best models: **flux-pro** (premium quality), **flux-schnell** (cheap + fast), **sdxl** (legacy fallback)
- Setup: `FAL_KEY` env var → `https://fal.ai/dashboard/keys`
- SDK: `npm install @fal-ai/serverless-client`

```ts
import * as fal from "@fal-ai/serverless-client";
fal.config({ credentials: process.env.FAL_KEY });

const result = await fal.subscribe("fal-ai/flux-pro", {
  input: {
    prompt: "Studio product photograph of a brushed-aluminum coffee scale, soft top-down light, off-white seamless backdrop, sharp focus, 50mm",
    image_size: "landscape_16_9",
  },
});
// result.images[0].url
```

### 2. Replicate — most model variety

- ~5-15 seconds per image, $0.005-$0.10/image
- Best when you need a specific niche model (interior renders, fashion try-on, product upscaling)
- Setup: `REPLICATE_API_TOKEN` env var → `https://replicate.com/account/api-tokens`
- SDK: `npm install replicate`

```ts
import Replicate from "replicate";
const replicate = new Replicate({ auth: process.env.REPLICATE_API_TOKEN });
const output = await replicate.run("black-forest-labs/flux-1.1-pro", {
  input: { prompt: "...", aspect_ratio: "16:9" },
});
```

### 3. OpenAI gpt-image-1 — highest quality, slowest, dimmest output by default

- ~10-30 seconds per image, $0.04-$0.17/image
- Strongest at text-in-image (UI labels, signage, packaging copy)
- Tends to render slightly muted — bump saturation in post if hero needs punch
- Setup: `OPENAI_API_KEY` env var → `https://platform.openai.com/api-keys`

```ts
import OpenAI from "openai";
const openai = new OpenAI();
const img = await openai.images.generate({
  model: "gpt-image-1",
  prompt: "...",
  size: "1536x1024",
  quality: "high",
});
```

---

## Model recommendations by use case

| Use case | Model | Why |
|---|---|---|
| Premium product photo | fal `flux-pro` or Replicate `flux-1.1-pro` | Best photorealism + composition |
| Hero background photo | fal `flux-schnell` | Cheap, plenty good for backdrops |
| Packaging / text-on-product | OpenAI `gpt-image-1` | Only model that gets text right |
| Iterative cheap drafts | fal `flux-schnell` | $0.003/image — burn through 100 |
| Dashboard mockup | **DON'T** — use `recipes/mockups.md` instead | Image gen still hallucinates UI |

---

## Prompt template for product mockups

```
Studio product photograph of [PRODUCT], [MATERIAL FINISH], [LIGHTING],
[BACKDROP], [LENS] mm, sharp focus, [MOOD], photorealistic, no text.
```

Filled example:

```
Studio product photograph of a matte-ceramic pour-over kettle in burnt sienna,
brushed copper handle, soft directional window light from the left,
warm off-white seamless backdrop, 85mm, sharp focus, calm and editorial,
photorealistic, no text.
```

**Always end with `no text`** unless you specifically need text — most models hallucinate gibberish letters.

---

## Cross-references

- For the device-frame approach (free, deterministic, recommended default), see `recipes/mockups.md`
- For free placeholder photos (no API), see `recipes/backgrounds-catalog.md` and the `picsum.photos/seed/{slug}/{w}/{h}` pattern in `anti-slop.md` § CONTENT
