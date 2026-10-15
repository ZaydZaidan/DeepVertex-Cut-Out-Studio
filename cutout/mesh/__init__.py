"""3D product-snapshot rendering (STEP / STL / OBJ / PLY / GLB -> web-ready images).

The heavy pieces (torch, Qt, mesh libraries) are imported lazily so that the
base package stays importable without them.  The default feature set:

* classic orthographic CAD views (front / back / left / right / top / bottom),
* e-commerce "hero" preset (front-left / front-right / back quarter views),
* customizable turntable ring,
* backgrounds: transparent / pure-white (Amazon main) / studio gradient / solid,
* soft ground shadows (studio & transparent modes).
"""
from .camera import VIEW_PRESETS, look_at, orthographic, perspective, view_direction  # noqa: F401

__all__ = ["VIEW_PRESETS"]
