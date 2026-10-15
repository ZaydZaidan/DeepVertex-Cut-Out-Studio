# Reverse Engineering Report — remove.bg Web Application

Target: https://www.remove.bg/ (web application + client pipeline)
Date: 2026-10-15
Analyst: Hermes (REA workflow) for Zayd Zaidan
Scope: client-side application shipped to the browser, its internal API contract,
and the observable processing pipeline. The server-side ML models are not
shippable artifacts and were **not** observable (see Limitations).

Evidence IDs (REA evidence ledger, session-local):
- `ev_feee6cb6fec7f39be572220d4ed848cc884c7313d3a4e791a62f287163339889` — analyze_web_bundle (static bundle analysis, 8 scripts)
- `ev_5606a8cbf998a85db214ce61bb0616bb7e701516b5e0acd13a99d100471aecd6` — list_browser_targets
- `ev_3478bcee51db85f0efdfc5ce068fa101f938e0bf5342a67d51b90623eb5957fd` — capture_browser_scenario (runtime network)

---

## 1. Method

1. REA `list_browser_targets` bound the live page target on a loopback CDP
   endpoint (Chrome 145 / CDP 1.3, headless).
2. REA `analyze_web_bundle` statically parsed all 8 loaded scripts
   (no JS execution): chunk graph, route/endpoint candidates, vendor
   fingerprints, and fetched production **source maps**.
3. The 10.5 MB complete analysis exceeded the MCP stdio budget; the retained
   Evidence was exported to disk (`export_evidence_bundle`, 33.2 MB, 3 records)
   and parsed locally — the documented REA recovery path.
4. Production source maps (publicly served) contained full `sourcesContent`.
   **472+ original source files were reconstructed locally** (223 first-party
   `app/javascript/**` files plus node_modules), including the internal API
   client, upload validation, polling logic and the ZIP layer decoder.
5. REA `capture_browser_scenario` recorded runtime request metadata for the
   homepage load (URLs, origins, resource types; no credentials).

Deployment fingerprint: Vite asset base
`static.remove.bg/remove-bg-web/dbfaec02d1e8bd04f1f132c4a92e4623d49a47a7/`,
Cloudflare in front (`cf-cache-status`, `cf-ray`), Rails UJS + Turbo-style
CSRF (`x-csrf-token`), Vue 3 + Pinia + Konva (`vue-konva`) editor mounted into
a Rails page, Stimulus controllers for classic pages. Accounts are served by
`accounts.kaleido.ai` (SSO; Kaleido = the umbrella account system).

## 2. Frontend stack (observed)

- `application-2774b68b.js` (3.1 MB) — Vite production build; contains the
  entire uploader page (Vue SFC tree), editor, checkout, plans, API docs page.
- Vendor fingerprints (REA `inferences`): Vue (app), React (isolated vendor
  chunk), Vue again in a transient chunk; jQuery, Stimulus, Rails UJS, Hooper,
  Konva, JSZip, EXIF utilities.
- Upload page entry: `app/javascript/src/upload.js` — mounts `UploadPage.vue`
  (Vue 3 + Pinia + `plugin-persisted-state`), pushes history state, accepts
  `filePicked`, `filePickedBase64`, `urlPicked`, `examplePicked`.
- Editor: `components/upload/editor.vue` (84 KB source), `old_editor.vue`
  (81 KB), `editor_store.ts`, `stage.ts`, `resizable_canvas.ts`,
  `zoomable.ts`, drawers: adjust / background / erase-restore / design / fx /
  crop / text; `panel_manager.vue`.

Source-map note: 3 maps requested, 3 processed, status `partial` (one map
unavailable) — recorded as an REA `unknowns` entry.

## 3. Client-side preprocessing (recovered verbatim)

From `src/remove-bg-tools/index.js` (`ImageResizer`):

- Accepted upload types (modern path, `upload_validation.ts`):
  `image/jpeg`, `image/png`, `image/webp`.
- Max file size from page config meta `configs.max_file_size_limit_mb`
  (documented default: 12 MB). Zero-byte file => `corrupted`.
- JPEG: EXIF read; orientation normalized (`canvas-exif-orientation` for
  legacy browsers); X/YResolution extracted (PPI metadata is preserved and
  re-attached to the result).
- PNG: DPI parsed from the PNG header (`png-dpi-reader-writer`).
- **Hard pixel cap: 25,000,000 px** — larger images are downscaled
  (`scale = sqrt(25e6 / pixels)`) before upload.
- The normalized bitmap is re-encoded to **JPEG quality 0.92**. For PNG
  input the canvas is first filled white (transparency flattened) and then
  exported as JPEG — i.e. the web tool uploads lossy-normalized pixels,
  not the original bytes.
- Original filename is carried through; result naming convention
  `basename-removebg` (+`-preview` when not hires) seen in
  `src/download_utils.js`.

## 4. Internal web API (recovered from `modules/internal_api/client.ts`)

All calls use `x-csrf-token` + `Accept: application/json`; multipart/FormData
for uploads. Reconstructed contract:

| Method | Path | Purpose |
|---|---|---|
| POST | `/images` | Upload (multipart `image[original]`, or `image[original_source_url]`, `trust_token`, `new_editor=true`) -> image resource JSON |
| GET | `/images/inline` | List images for the session |
| GET | `/images/inline/{id}` | **Poll** processing state (`state`, `nextFetchIn`, result urls) |
| DELETE | `/images/{id}` | Delete image |
| POST | `/images/{id}/full_image/create_inline` | Enqueue HD ("full image") processing |
| PUT | `/images/{id}/ai_brush` | Magic Brush preview (`mask`, `mask_mode=positive_mask|negative_mask`, `previous_alpha`, `previous_color`, `iteration_id`, `size=preview`) |
| PUT | `/images/{id}/full_image/ai_brush` | Magic Brush HD |
| POST | `/images/{id}/signed_url` | Signed bucket URL for result (`size=hd|preview`) |
| POST | `/images/{id}/public_url` | Public share URL |
| POST | `/images/{id}/signed_background_url` | Signed URL for a custom background upload |
| PATCH | `/images/{id}` | Rating + training-contribution flag (`image[rating]`, `image[contribute]`) |
| POST | `/images/{id}/generate` | Magic Background (AI background) enqueue (`template_id`) |
| POST | `/images/{id}/generate/upscale` | Upscale a generation (`generated_image_id`) |
| POST | `/images/{generationId}/full_image/process_full` | Foreground HD for AI backgrounds |
| GET | `/bg-image/search?query&page&locale` | Background photo search (Pexels-backed) |
| GET | `/bg-image/collections` , `/bg-image/collections/{name}` | Curated background collections |
| GET | `/magic-backgrounds/templates/{foregroundType}` | Templates per foreground class (`person|car|animal|product|other`) |

State machine (`image.ts`): `ProcessingState = ready | processing | finished |
error`; `UploadState = pending | uploading | finished | error |
token_requested`. Polling (`poll.ts`): client re-fetches
`/images/inline/{id}` after the server-provided **`nextFetchIn`** delay
(server-driven backoff), until `finished`/`error`.

Result variants tracked per image: `previewResult`, `hdResult`,
`magicBrushPreviewResult`, `magicBrushHdResult`,
`magicBackgroundPreviewResult`, `magicBackgroundHdResult`.

Metadata fields per image: `width/height`, `previewWidth/Height`,
`hdWidth/Height`, `fullWidth/Height`, `50mpWidth/Height`,
`foregroundType`, `modelsVersion`, `orientation`, `has_no_foreground`,
`sizeMb`, magic-brush iteration history (preview/hd/alpha per iteration).

## 5. Result transport format — the "ZIP protocol" (recovered)

From `modules/zip_canvas.ts` / `remove-bg-tools/index.js` (`ZipCanvas`):

The processed result is a **ZIP archive** (fetched via XHR as ArrayBuffer)
containing separate color and alpha planes:

- `color.jpg` — RGB foreground (JPEG)
- `alpha.png` — alpha matte as a greyscale PNG; **client composites by copying
  the red channel of `alpha.png` into the alpha channel of `color`**
- Optional `shadow_color.jpg` + `shadow_alpha.png` — AI shadow layer
- Optional `semi_transparency_color.jpg` + `semi_transparency_alpha.png` —
  semi-transparency layer (hair/glass/motion blur class of pixels)

Client progress stages: `download(10%) -> loadzip(20%) -> extractzip(30%) ->
loadimages(70%) -> compositing(80%) -> exporting(90%)`. This matches the
documented API `format=zip` option and the `semitransparency` API parameter —
the web app consumes the same zip product the public API exposes.

Observed model-derived outputs therefore include: foreground matte, an
optional **shadow synthesis** layer, an optional **semi-transparency** layer,
and a **foreground-type classification** used to pick AI background templates.

## 6. Public API contract (documentation, corroboration)

`POST https://api.remove.bg/v1.0/removebg` with `X-Api-Key`:
`image_file` or `image_url`, `size` (auto/preview/…), `format` (png/jpg/zip),
`bg_color`, `semitransparency`, `type_level`; response: binary image or JSON;
`GET /account` credit balance; `POST /improve`. Limits: 12 MB input,
up to 25 MP (per changelog), rate limits resolution-dependent; transfer moved
to Leonardo (banner observed in bundle: `leonardo.ai/news/removebg-api-leonardo`).

## 7. Feature inventory (observed in recovered first-party sources)

- Inline editor (Konva canvas): crop, adjust, fx, text, design overlays,
  erase/restore brush, zoom, image navigation, presets (persisted).
- **Magic Brush**: iterative AI erase/restore with server round-trips; max
  **10 iterations** (`MAX_MAGIC_BRUSH_ITERATIONS`); sends mask + previous
  alpha/color for temporal coherence.
- **Magic Backgrounds**: AI-generated backgrounds per foreground class
  (person/car/animal/product/other), inspiration gallery, HD upscale.
- Background search: Pexels search/collections + user upload + solid colors +
  blur; attribution UI for photographers.
- Share flow: signed upload -> public URL. Canva integration CTA.
- Credits/plans/checkout (PAYG + subscription), usage chart, referrals.
- Rating + "contribute to improve" opt-in (training-data consent).

## 8. Reconstruction — local application design

Deliverable: `cutout-studio` (this repo) — a fully local, GPU-accelerated
background remover mirroring the observed remove.bg pipeline architecture
without any server dependency.

| remove.bg (observed) | Local reconstruction |
|---|---|
| Server model (unobservable) | Open-source SOTA matting: **BiRefNet-general** (MIT) default, **RMBG-2.0** (non-commercial) optional |
| `/images` upload + `/images/inline/{id}` poll | In-process synchronous inference (no network) |
| `nextFetchIn` server-driven polling | GUI worker threads with per-image progress/cancel |
| ZIP `color.jpg` + `alpha.png` protocol | Internal float32 alpha matte + RGBA composition (same math: matte -> alpha channel) |
| Shadow layer synthesis | Optional drop-shadow compositor (color/opacity/blur/offset) |
| Semi-transparency layer | Alpha-matting refinement (closed-form matting) recovers hair/glass edges |
| 25 MP cap + EXIF normalize + JPEG q92 | EXIF transpose + configurable pixel cap; lossless pipeline (no re-encode before inference) |
| Backgrounds: color / blur / upload / search | Transparent / solid / blurred original / custom image |
| Download naming `-removebg` | Configurable suffix (default `-nobg`) |
| Batch via image navigation | Multi-file queue + batch processing |
| Inputs: jpeg/png/webp, 12 MB | jpeg/png/webp/bmp/tiff, size limited by RAM/VRAM |

Explicitly not reconstructed (server-side secrets, out of scope): the trained
network, credit accounting, Pexels integration, Canva, and any remove.bg
branding/assets. GUI, naming and code are original work.

## 9. Limitations and unknowns (per REA discipline)

- The ML model is server-side; **no model weights or architecture are present
  in the shipped client**. All model claims above are limited to
  input/output *behavior* visible in client code (matte + optional shadow /
  semi-transparency / foreground-type).
- No authenticated flows were exercised; upload/download/credit behavior is
  reconstructed from shipped code + public docs, not from live account use.
- One source map was unavailable (`status: partial`); bundle-level minified
  code was used where maps were missing.
- Runtime capture recorded request metadata only (no bodies; credentials
  excluded by the provider).
