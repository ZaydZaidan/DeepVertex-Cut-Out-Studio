# Product-Snapshot Study — CAD-to-Marketing-Image Workflow

Study: 2026-10-15 · Analyst: Hermes (REA workflow) for Zayd Zaidan
Scope: how existing, official tools turn a **3D model** into webshop-ready
*product images*, and how this project's **3D Snapshot** feature implements
the same conventions. Target applications: Autodesk Fusion, KeyShot /
KeyShotXR, Sketchfab turntables, marketplace image rules.

Method note: Autodesk Fusion and KeyShot are licensed desktop apps and were
**not installed** on the analyst machine, so this is a **documentation /
public-workflow study**, not a bundle capture like `docs/RECON_REPORT.md`
(remove.bg). Where a camera behaviour is in question, the conventions below
were validated against public docs and screenshots of the official UIs.

---

## 1. Sources consulted (summary)

* **Autodesk Fusion** (desktop + docs):
  - *Render* workspace: render settings dialog (image size, exposure),
    cloud/local rendering, in-canvas rendering preview.
  - Named views of the model: Front / Back / Left / Right / Top / Bottom —
    the standard CAD six-view convention (matches the drawing-view canon).
  - Render output supports **transparent background** (PNG) — a checkbox in
    the render dialog — used for compositing product shots.
  - *Turntable* renders (camera orbits the upright model at a fixed
    elevation) generate spin sequences for websites.
  - Fusion's native `.f3d`/`.f3z` files are an internal Autodesk archive
    format — not documented/parsable by third-party code; the official
    interchange path is **File ▸ Export → STEP / STL**.
* **KeyShot / KeyShotXR**:
  - Environment-based lighting (HDRI); product presets with a "black canvas"
    then light pins; ground shadows are optional (KeyShotXR docs recommend
    *unchecking* ground shadows for transparent web visuals).
  - White-on-white product work: dial the background to pure white, keep the
    product readable via separated highlights (edge visibility against bg).
  - 360°/turntable product visuals for e-commerce; ~24–72 frames typical.
* **Major marketplaces (Amazon et al.)**:
  - Main image: **pure white background** (RGB 255), square, product fill
    ≈ 85 % of the frame, **no shadows/logo/text** in the main image.
  - Alternate gallery shots: transparent / white / contextual.
  - Common title/hero framing: the 3/4 "hero" angle (front-quarter with a
    slight elevation), one *turntable*-like set of side views.
* **Sketchfab / web viewers**: light-emphasis studio environments, matte or
  PBR material, turntable auto-spin.

## 2. Feature design mapping

| Convention (source)                | Implementation in `cutout/mesh/*` |
|------------------------------------|-----------------------------------|
| Six CAD named views (Fusion)       | `front/back/left/right/top/bottom` presets, orthographic projection |
| 3/4 hero angle (marketplace rule)  | `hero-front-left/right`, `hero-back-left/right`, 34 mm-equivalent 34° perspective lens |
| Turntable (Fusion/KeyShotXR)       | `turntable:N` — N azimuths at 22° elevation |
| Product fill ≈ 85 % (Amazon)       | `fill=0.85` framing: bounding-sphere window fit |
| Main image white ~255, no shadow   | `bg=white` + `shadow=off` default |
| Transparent render (Fusion PNG)    | `bg=transparent` alpha-PNG/WebP; shadow optional |
| Studio cyclorama look (KeyShot)    | `bg=studio/dark/sunset` vertical gradient + two-lobe contact shadow |
| Environment HDRI feel (KeyShot)    | 3-point studio light rig key/fill/rim + ambient |
| Ground shadows optional (KeyShotXR)| `shadow=auto|on|off` (auto: off for white/transparent, on for studio) |
| `.f3d` not parseable (Fusion)      | actionable error pointing at Fusion *File ▸ Export STEP/STL* |

## 3. Renderer implementation notes

* Headless OpenGL via **moderngl** (EGL → OSMesa → GLX probing) — no window
  server required, GPU-accelerated when a driver is present (verified on an
  NVIDIA RTX 5050; CPU fallback via OSMesa when available).
* Materials: uniforms key/fill/rim directions + colours + strengths, ambient
  floor, Blinn-Phong specular, gamma correction. Default material is a
  neutral matte "studio clay".
* Soft shadow: the mesh is projected along the key-light direction onto the
  floor plane at the product's lowest point, rasterised in image space with
  the same MVP, then blurred twice — a wide soft lobe and a tight contact
  occlusion restricted to the floor band under the product's base — and
  composited into the frame (multiplies the backdrop, or writes shadow alpha
  under transparent backgrounds).
* Output: PNG (RGBA), WebP, JPG (flattened onto the background), plus an
  optional contact sheet merging all views.

## 4. Limitations

* `.f3d`/`.f3z` remain **unsupported by design** (not an interchange format);
  STEP import requires the optional `cadquery-ocp`/`cadquery` bindings
  (`pip install "deepvertex-cutout-studio[step]"` — heavy).
* Reflections/refractions, textures and per-material PBR (GLTF materials) are
  *not* implemented: snapshots are single-material matte renders, which is
  the normal look for unbranded product mock-ups.
* Shadow is a first-order projection (soft shadow of the whole silhouette),
  not a ray-traced occlusion pass.
