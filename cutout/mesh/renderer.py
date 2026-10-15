"""Headless OpenGL renderer for product snapshots (moderngl, EGL/OSMesa/GLX).

Render conventions follow the product-visualization study in
``docs/3D_SNAPSHOT_RECON.md`` (Autodesk Fusion render workspace, KeyShot /
KeyShotXR, Amazon image rules): three-point studio lighting, neutral matte
materials, framed product fill, optional soft contact shadow (applied by the
caller), transparent or gradient backgrounds.
"""
from __future__ import annotations

import numpy as np

from .camera import look_at, orthographic, perspective  # noqa: F401 (re-export)

BG_VERTEX_SRC = """
#version 330 core
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.999, 1.0);
}
"""

BG_FRAGMENT_SRC = """
#version 330 core
in vec2 v_uv;
out vec4 out_color;
uniform vec4 u_bg_top;
uniform vec4 u_bg_bot;
void main() {
    vec4 col = mix(u_bg_bot, u_bg_top, v_uv.y);
    // photographic vignette on the cyclorama
    vec2 d = v_uv - vec2(0.5);
    col.rgb *= 1.0 - 0.12 * clamp(dot(d, d) * 2.2, 0.0, 1.0);
    out_color = col;
}
"""

VERTEX_SRC = """
#version 330 core
in vec3 in_pos;
in vec3 in_normal;
uniform mat4 u_mvp;
out vec3 v_pos;
out vec3 v_normal;
void main() {
    v_pos = in_pos;            // world space: the model transform is baked in
    v_normal = in_normal;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

FRAGMENT_SRC = """
#version 330 core
in vec3 v_pos;
in vec3 v_normal;
out vec4 out_color;

uniform vec3  u_view_pos;
uniform vec3  u_color;
uniform float u_gloss;      // specular exponent
uniform float u_spec_str;   // specular strength
uniform float u_ambient;    // ambient base
uniform float u_gamma;

uniform vec3 u_key_dir;  uniform vec3 u_key_col;  uniform float u_key_str;
uniform vec3 u_fill_dir; uniform vec3 u_fill_col; uniform float u_fill_str;
uniform vec3 u_rim_dir;  uniform vec3 u_rim_col;  uniform float u_rim_str;

void main() {
    vec3 N = normalize(v_normal);
    vec3 V = normalize(u_view_pos - v_pos);

    vec3 col = u_color * u_ambient;
    col += u_key_col  * u_key_str  * max(dot(N, -u_key_dir), 0.0)  * u_color;
    col += u_fill_col * u_fill_str * max(dot(N, -u_fill_dir), 0.0) * u_color;
    col += u_rim_col  * u_rim_str  * max(dot(N, -u_rim_dir), 0.0)  * u_color;

    vec3 hk = normalize(-u_key_dir  + V);
    vec3 hf = normalize(-u_fill_dir + V);
    vec3 hr = normalize(-u_rim_dir  + V);
    col += u_key_col  * u_spec_str        * pow(max(dot(N, hk), 0.0), u_gloss);
    col += u_fill_col * (0.3 * u_spec_str) * pow(max(dot(N, hf), 0.0), u_gloss);
    col += u_rim_col  * (0.5 * u_spec_str) * pow(max(dot(N, hr), 0.0), u_gloss);
    // broad "softbox" sheen (kitchen-lamp broad glossy reflection)
    col += u_key_col  * 0.16 * pow(max(dot(N, hk), 0.0), 7.0);

    col = pow(clamp(col, 0.0, 1.0), vec3(1.0 / u_gamma));
    // self-occlusion cue: surfaces facing down (under overhangs / cavities)
    // catch almost no light in a studio — droop them carefully.
    col *= mix(1.0, 0.80, smoothstep(0.0, -0.65, N.y));
    out_color = vec4(col, 1.0);
}
"""

#: studio 3-point rig. Tuple layout: (unit direction of travel, RGB, strength)
KEY_LIGHT = (np.array([0.45, -0.70, 0.45]), (1.00, 0.98, 0.94), 0.92)
FILL_LIGHT = (np.array([-0.65, -0.30, -0.10]), (0.92, 0.94, 1.00), 0.40)
RIM_LIGHT = (np.array([-0.10, -0.40, -0.80]), (1.00, 1.00, 1.00), 0.60)

#: neutral matte "product studio" material
MATERIAL = dict(
    color=(0.87, 0.88, 0.90), gloss=52.0, spec_str=0.45, ambient=0.26, gamma=2.2
)

BACKGROUND_PRESETS: dict[str, tuple[tuple, tuple]] = {
    # (top RGBA, bottom RGBA) — RGB 0..1
    "studio": ((0.93, 0.94, 0.96, 1.0), (0.66, 0.68, 0.72, 1.0)),
    "studio-dark": ((0.10, 0.11, 0.13, 1.0), (0.02, 0.02, 0.03, 1.0)),
    "sunset": ((0.98, 0.89, 0.84, 1.0), (0.92, 0.68, 0.55, 1.0)),
}


def create_context():
    """Standalone (headless) OpenGL context: EGL -> OSMesa -> GLX probing."""
    import moderngl

    errors = []
    for backend in ("egl", "osmesa", "glx"):
        try:
            return moderngl.create_context(standalone=True, backend=backend)
        except Exception as exc:  # noqa: BLE001 - probe all backends
            errors.append(f"  {backend}: {type(exc).__name__}: {exc}")
    raise RuntimeError(
        "no headless OpenGL context available. Install one of:\n"
        "  libegl1 (usually ships with the graphics driver),\n"
        "  libosmesa6 (CPU fallback)\n"
        "Details:\n" + "\n".join(errors)
    )


class GLRenderer:
    """Renders one triangle-mesh view per call into an RGBA canvas."""

    def __init__(self, size: tuple[int, int] = (1600, 1600)) -> None:
        self.ctx = create_context()
        self.size = size
        self._mesh_prog = self.ctx.program(vertex_shader=VERTEX_SRC, fragment_shader=FRAGMENT_SRC)
        self._bg_prog = self.ctx.program(vertex_shader=BG_VERTEX_SRC, fragment_shader=BG_FRAGMENT_SRC)
        quad = self.ctx.buffer(
            np.asarray([[-1, -1], [1, -1], [-1, 1], [1, 1]], dtype=np.float32)
        )
        self._bg_vao = self.ctx.vertex_array(
            self._bg_prog, [(quad, "2f", "in_pos")], mode=self.ctx.TRIANGLE_STRIP
        )

    # ------------------------------------------------------------------ mesh
    @staticmethod
    def _mesh_arrays(mesh):
        import numpy as np

        positions = np.asarray(mesh.vertices, dtype=np.float32)
        normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
        faces = np.asarray(mesh.faces, dtype=np.uint32)
        v0 = positions[faces[:, 0]]
        v1 = positions[faces[:, 1]]
        v2 = positions[faces[:, 2]]
        keep = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1) > 1e-12
        return positions, normals, faces[keep]

    def render_mesh(
        self,
        mesh,
        view_mat: np.ndarray,
        proj_mat: np.ndarray,
        view_pos: np.ndarray,
        bg: tuple | None = None,          # (top rgba, bottom rgba) or None for transparent
        material: dict | None = None,
    ):
        """Returns (rgb uint8 HxWx3, alpha float32 HxW)."""
        import numpy as np

        mat = {**MATERIAL, **(material or {})}
        w, h = self.size
        fbo_tex = self.ctx.texture((w, h), components=4, dtype="f1")
        fbo_tex.filter = (self.ctx.LINEAR, self.ctx.LINEAR)
        depth = self.ctx.depth_renderbuffer((w, h))
        fbo = self.ctx.framebuffer(color_attachments=[fbo_tex], depth_attachment=depth)
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 1.0 if bg is not None else 0.0)
        self.ctx.enable(self.ctx.DEPTH_TEST)

        if bg is not None:
            self._bg_prog["u_bg_top"].value = tuple(bg[0])
            self._bg_prog["u_bg_bot"].value = tuple(bg[1])
            self._bg_vao.render()

        positions, normals, indices = self._mesh_arrays(mesh)
        vbo = self.ctx.buffer(positions.tobytes())
        nbo = self.ctx.buffer(normals.tobytes())
        ibo = self.ctx.buffer(indices.tobytes())
        vao = self.ctx.vertex_array(
            self._mesh_prog,
            [(vbo, "3f", "in_pos"), (nbo, "3f", "in_normal")],
            ibo,
        )
        pr = self._mesh_prog
        # NOTE: uniform mat4 data is column-major in GL; numpy is row-major,
        # so transpose before upload (otherwise the MVP lands transposed and
        # geometry renders gigantic/mirrored).
        pr["u_mvp"].write(((proj_mat @ view_mat).T.astype(np.float32)).tobytes())
        pr["u_view_pos"].value = tuple(np.asarray(view_pos, dtype=float))
        pr["u_color"].value = tuple(mat["color"])
        pr["u_gloss"].value = float(mat["gloss"])
        pr["u_spec_str"].value = float(mat["spec_str"])
        pr["u_ambient"].value = float(mat["ambient"])
        pr["u_gamma"].value = float(mat["gamma"])
        pr["u_key_dir"].value = tuple(KEY_LIGHT[0])
        pr["u_key_col"].value = KEY_LIGHT[1]
        pr["u_key_str"].value = KEY_LIGHT[2]
        pr["u_fill_dir"].value = tuple(FILL_LIGHT[0])
        pr["u_fill_col"].value = FILL_LIGHT[1]
        pr["u_fill_str"].value = FILL_LIGHT[2]
        pr["u_rim_dir"].value = tuple(RIM_LIGHT[0])
        pr["u_rim_col"].value = RIM_LIGHT[1]
        pr["u_rim_str"].value = RIM_LIGHT[2]
        vao.render()

        raw = np.flipud(np.frombuffer(fbo.read(components=4), dtype=np.uint8).reshape(h, w, 4))
        rgb = raw[:, :, :3].copy()
        alpha = raw[:, :, 3].astype(np.float32) / 255.0
        fbo.release()
        fbo_tex.release()
        return rgb, alpha

    def release(self) -> None:
        try:
            self.ctx.release()
        except Exception:  # noqa: BLE001 - context may already be released
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
