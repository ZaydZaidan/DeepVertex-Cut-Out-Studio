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
from .envmap import env_texture_array

VERTEX_SRC = """
#version 330 core
in vec3 in_pos;
in vec3 in_normal;
in float in_ao;
uniform mat4 u_mvp;
out vec3 v_pos;
out vec3 v_normal;
out float v_ao;
void main() {
    v_pos = in_pos;            // world space: the model transform is baked in
    v_normal = in_normal;
    v_ao = in_ao;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

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
    vec2 d = v_uv - vec2(0.5);
    col.rgb *= 1.0 - 0.12 * clamp(dot(d, d) * 2.2, 0.0, 1.0);
    out_color = col;
}
"""

FRAGMENT_SRC = """
#version 330 core
in vec3 v_pos;
in vec3 v_normal;
out vec4 out_color;

uniform vec3  u_view_pos;
uniform vec3  u_color;
uniform float u_gloss;      // specular exponent (tight glints)
uniform float u_spec_str;   // specular strength (tight glints)
uniform float u_ambient;    // ambient base
uniform float u_gamma;

uniform vec3 u_key_dir;  uniform vec3 u_key_col;  uniform float u_key_str;
uniform vec3 u_fill_dir; uniform vec3 u_fill_col; uniform float u_fill_str;
uniform vec3 u_rim_dir;  uniform vec3 u_rim_col;  uniform float u_rim_str;
uniform sampler2D u_env;
uniform float u_env_yaw;
uniform float u_env_gain;
in float v_ao;

// equirect lookup for a direction (yaw rotates the map around +Y)
vec2 equirect(vec3 d) {
    float az = atan(d.x, d.z) - u_env_yaw;
    float el = asin(clamp(d.y, -1.0, 1.0));
    return vec2(az / (2.0 * 3.14159265) + 0.5, el / 3.14159265 + 0.5);
}

void main() {
    vec3 N = normalize(v_normal);
    vec3 V = normalize(u_view_pos - v_pos);
    float ndv = max(dot(N, V), 1e-4);

    // micro surface variation (tiny, keeps large surfaces from looking flat)
    float g = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    vec3 albedo = u_color * (0.995 + 0.02 * (g - 0.5));
    float rough = 0.13;

    // Fresnel (Schlick, dielectric)
    float F = 0.045 + 0.955 * pow(1.0 - ndv, 5.0);

    // real environment lookup (bitmap equirect — reflections pick up *shape*)
    vec3 R = reflect(-V, N);
    float lod = clamp(rough * 7.0, 0.20, 2.0);
    vec3 env_r = textureLod(u_env, equirect(R), lod).rgb;
    vec3 refl = env_r * u_env_gain * F * (1.0 - 0.30 * rough);

    vec3 col = albedo * u_ambient;
    col += u_key_col  * u_key_str  * max(dot(N, -u_key_dir), 0.0)  * albedo;
    col += u_fill_col * u_fill_str * max(dot(N, -u_fill_dir), 0.0) * albedo;
    col += u_rim_col  * u_rim_str  * max(dot(N, -u_rim_dir), 0.0)  * albedo;
    col += refl;

    // tight glint on top of the env reflection (tiny, physical sparkle)
    vec3 hk = normalize(-u_key_dir + V);
    col += u_key_col * (u_spec_str * 0.55 * pow(max(dot(N, hk), 0.0), u_gloss)
                      + u_spec_str * 0.25 * pow(max(dot(N, hk), 0.0), 180.0));

    col = pow(clamp(col, 0.0, 1.0), vec3(1.0 / u_gamma)) * mix(0.62, 1.0, clamp(v_ao, 0.0, 1.0));
    // self-occlusion: down-facing surfaces see almost nothing in a studio
    col *= mix(1.0, 0.80, smoothstep(0.0, -0.65, N.y));
    out_color = vec4(col, 1.0);
}
"""#: studio 3-point rig. Tuple layout: (unit direction of travel, RGB, strength)
KEY_LIGHT = (np.array([0.45, -0.70, 0.45]), (1.00, 0.98, 0.94), 0.92)
FILL_LIGHT = (np.array([-0.65, -0.30, -0.10]), (0.92, 0.94, 1.00), 0.40)
RIM_LIGHT = (np.array([-0.10, -0.40, -0.80]), (1.00, 1.00, 1.00), 0.60)

#: neutral matte "product studio" material
MATERIAL = dict(
    color=(0.87, 0.88, 0.90), gloss=96.0, spec_str=0.70, ambient=0.26, gamma=2.2
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

    def __init__(self, size: tuple[int, int] = (1600, 1600), env_path=None) -> None:
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
        self._env_tex = None
        self.set_env(env_path)

    # ------------------------------------------------------------------- env
    def set_env(self, env_path=None, yaw: float = 0.0, gain: float = 1.0) -> None:
        """Load an equirect environment (user file or bundled default)."""
        import numpy as np

        arr = env_texture_array(env_path)
        tex = self.ctx.texture((arr.shape[1], arr.shape[0]), components=3, dtype="f1")
        tex.write((np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8).tobytes())
        tex.filter = (self.ctx.LINEAR_MIPMAP_LINEAR, self.ctx.LINEAR)
        tex.repeat_x = True
        tex.build_mipmaps()
        self._env_tex = tex
        self._env_yaw = float(yaw)
        self._env_gain = float(gain)

    # ------------------------------------------------------------------ mesh
    @staticmethod
    def _mesh_arrays(mesh):
        import numpy as np

        positions = np.asarray(mesh.vertices, dtype=np.float32)
        normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
        ao_raw = getattr(mesh, "ao_array", None)
        ao = (
            np.asarray(ao_raw, dtype=np.float32)
            if ao_raw is not None and np.ndim(ao_raw) == 1
               and np.asarray(ao_raw).size == len(positions)
            else np.ones(len(positions), dtype=np.float32)
        )
        faces = np.asarray(mesh.faces, dtype=np.uint32)
        v0 = positions[faces[:, 0]]
        v1 = positions[faces[:, 1]]
        v2 = positions[faces[:, 2]]
        keep = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1) > 1e-12
        return positions, normals, ao, faces[keep]

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
        depth_tex = self.ctx.depth_texture((w, h))
        fbo = self.ctx.framebuffer(color_attachments=[fbo_tex], depth_attachment=depth_tex)
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 1.0 if bg is not None else 0.0)
        self.ctx.enable(self.ctx.DEPTH_TEST)

        if bg is not None:
            self._bg_prog["u_bg_top"].value = tuple(bg[0])
            self._bg_prog["u_bg_bot"].value = tuple(bg[1])
            self._bg_vao.render()

        positions, normals, ao_vals, indices = self._mesh_arrays(mesh)
        vbo = self.ctx.buffer(positions.tobytes())
        nbo = self.ctx.buffer(normals.tobytes())
        abo = self.ctx.buffer(ao_vals.tobytes())
        ibo = self.ctx.buffer(indices.tobytes())
        vao = self.ctx.vertex_array(
            self._mesh_prog,
            [(vbo, "3f", "in_pos"), (nbo, "3f", "in_normal"), (abo, "1f", "in_ao")],
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
        if self._env_tex is not None:
            self._env_tex.use(location=1)
            pr["u_env"].value = 1
            pr["u_env_yaw"].value = self._env_yaw
            pr["u_env_gain"].value = self._env_gain
        vao.render()

        raw = np.flipud(np.frombuffer(fbo.read(components=4), dtype=np.uint8).reshape(h, w, 4))
        rgb = raw[:, :, :3].copy()
        alpha = raw[:, :, 3].astype(np.float32) / 255.0
        try:
            d = np.flipud(np.frombuffer(depth_tex.read(), dtype=np.float32).reshape(h, w))
        except Exception:  # noqa: BLE001 - depth readback optional
            d = None
        fbo.release()
        fbo_tex.release()
        return rgb, alpha, d

    def release(self) -> None:
        try:
            self.ctx.release()
        except Exception:  # noqa: BLE001 - context may already be released
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
