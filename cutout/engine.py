"""Local foreground-matting engines (GPU-accelerated).

Reconstructed equivalent of the processing stage observed in the remove.bg web
client: the client never ships a model, it uploads normalized pixels and
receives back a per-pixel matte (their ``alpha.png``) plus RGB pixels (their
``color.jpg``).  Locally we produce the same two products with open-source
state-of-the-art matting models running on the user's own GPU.

Supported model backends (Hugging Face Hub):
  * ``birefnet``  - ZhengPeng7/BiRefNet        (MIT license)
  * ``rmbg2``     - briaai/RMBG-2.0            (non-commercial license)

``torch`` is imported lazily so that lightweight commands (``--list-models``,
packaging metadata, tests that do not run inference) work without a torch
install.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

#: nominal inference resolutions offered in the UI
RES_PRESETS = {"fast": 768, "balanced": 1024, "max": 1536}


def _require_torch():
    """Import torch on first use with an actionable error message."""
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "PyTorch is required for inference. Install it first, e.g.\n"
            "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130\n"
            "(see the README for CPU-only instructions)"
        ) from exc
    return torch


@dataclass(frozen=True)
class ModelInfo:
    key: str
    repo: str
    label: str
    license: str
    approx_download: str


MODEL_CATALOG: dict[str, ModelInfo] = {
    "birefnet": ModelInfo(
        key="birefnet",
        repo="ZhengPeng7/BiRefNet",
        label="BiRefNet-general (default)",
        license="MIT",
        approx_download="~0.9 GB",
    ),
    "rmbg2": ModelInfo(
        key="rmbg2",
        repo="briaai/RMBG-2.0",
        label="RMBG-2.0 (BRIA, non-commercial — gated: needs HF login & licence accept)",
        license="bria-rmbg-2.0 (non-commercial)",
        approx_download="~1.7 GB",
    ),
}


def _logits_from_output(out):
    """Normalize the various HF matting model output shapes to one tensor."""
    torch = _require_torch()
    if torch.is_tensor(out):
        return out
    if isinstance(out, dict):
        tensors = [v for v in out.values() if torch.is_tensor(v)]
        if not tensors:
            raise RuntimeError("model returned a dict without tensors")
        return tensors[-1]
    if isinstance(out, (list, tuple)):
        for item in reversed(out):
            if torch.is_tensor(item):
                return item
        raise RuntimeError("model returned a sequence without tensors")
    raise RuntimeError(f"unexpected model output type: {type(out)!r}")


class MattingEngine:
    """Loads one matting model and produces full-resolution alpha mattes."""

    def __init__(
        self,
        model: str = "birefnet",
        device: str | None = None,
        use_half: bool | None = None,
    ) -> None:
        if model not in MODEL_CATALOG:
            raise ValueError(f"unknown model {model!r}; choose from {sorted(MODEL_CATALOG)}")
        torch = _require_torch()
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_key = model
        self.info = MODEL_CATALOG[model]
        self.device = torch.device(device)
        self.use_half = (self.device.type == "cuda") if use_half is None else bool(use_half)
        self._model = None
        self._half_active = False
        self._model_dtype = None
        self._mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
        self._std = torch.tensor(IMAGENET_STD).view(3, 1, 1)

    # ------------------------------------------------------------------ load
    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        _require_torch()  # guard: clear error message when torch is missing
        from transformers import AutoModelForImageSegmentation

        log.info("loading %s from %s ...", self.info.label, self.info.repo)
        try:
            model = AutoModelForImageSegmentation.from_pretrained(
                self.info.repo, trust_remote_code=True
            )
        except OSError as exc:
            # Gated HF repos (e.g. RMBG-2.0) answer with an auth error; surface
            # an actionable message instead of the raw 401/OSError.
            if "restricted" in str(exc) or "401" in str(exc) or "gated" in str(exc).lower():
                raise RuntimeError(
                    f"{self.info.repo} is a *gated* Hugging Face repository "
                    "(licence must be accepted and you must be logged in).\n"
                    "To enable this model:\n"
                    f"  1. Visit https://huggingface.co/{self.info.repo} and accept "
                    "the licence terms.\n"
                    "  2. Run `huggingface-cli login` (or set the HF_TOKEN "
                    "environment variable).\n"
                    "  3. Retry the operation.\n"
                    "Alternatively, use the default BiRefNet model (MIT)."
                ) from exc
            raise
        model.eval()
        # Some checkpoints (e.g. BiRefNet) ship fp16 weights regardless of the
        # platform.  Align the model dtype with the target device instead of
        # assuming it: fp16 on CUDA (when enabled), fp32 on CPU.
        if self.device.type == "cuda" and self.use_half:
            try:
                model = model.half()
                self._half_active = True
            except Exception:  # pragma: no cover - defensive
                log.warning("fp16 conversion failed; continuing in fp32")
                model = model.float()
                self._half_active = False
        else:
            model = model.float()
            self._half_active = False
        model.to(self.device)
        self._model = model
        self._model_dtype = next(model.parameters()).dtype
        log.info(
            "model ready on %s (%s, weights %s)",
            self.device,
            "fp16" if self._half_active else "fp32",
            self._model_dtype,
        )

    def _run(self, tensor):
        torch = _require_torch()
        assert self._model is not None
        autocast = torch.autocast(
            device_type="cuda",
            dtype=torch.float16,
            enabled=self._half_active and self.device.type == "cuda",
        )
        with torch.no_grad(), autocast:
            out = self._model(tensor)
        return _logits_from_output(out)

    def _fallback_fp32(self) -> None:
        log.warning("encountered a fp16 failure; reloading model in fp32")
        self._model = None
        self._half_active = False
        self.use_half = False
        self.load()

    # --------------------------------------------------------------- predict
    def infer_matte(
        self,
        image: Image.Image,
        res: int = 1024,
        keep_aspect: bool = True,
    ) -> np.ndarray:
        """Return a float32 alpha matte in [0, 1] at the *original* size.

        ``res`` is the nominal long-side resolution fed to the network; it is
        rounded to a multiple of 32 (window-attention constraint).
        """
        torch = _require_torch()
        self.load()
        if image.mode != "RGB":
            image = image.convert("RGB")
        w, h = image.size

        if keep_aspect:
            scale = float(res) / float(max(w, h))
            nw = max(64, int(w * scale) // 32 * 32)
            nh = max(64, int(h * scale) // 32 * 32)
        else:
            nw = nh = res // 32 * 32

        small = image if (nw, nh) == (w, h) else image.resize((nw, nh), Image.BICUBIC)
        arr = np.asarray(small, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(arr).permute(2, 0, 1).contiguous()
        tensor = (tensor - self._mean) / self._std
        tensor = tensor.unsqueeze(0)
        # the input dtype must match the loaded weights (fp16 checkpoints!)
        infer_dtype = self._model_dtype or (torch.float16 if self._half_active else torch.float32)
        tensor = tensor.to(self.device, dtype=infer_dtype)

        try:
            logits = self._run(tensor)
        except RuntimeError as exc:
            if self._half_active and "Half" in str(exc):
                self._fallback_fp32()
                tensor = tensor.float()
                logits = self._run(tensor)
            else:
                raise

        matte = logits.sigmoid()
        while matte.dim() > 2:
            matte = matte[:, 0] if matte.dim() == 4 else matte[0]
        matte = matte.float().cpu()
        if matte.shape[-2:] != (h, w):
            matte = torch.nn.functional.interpolate(
                matte[None, None], size=(h, w), mode="bicubic", align_corners=False
            )[0, 0]
        return matte.clamp(0.0, 1.0).numpy()

    # ------------------------------------------------------------- utilities
    def warmup(self) -> None:
        self.infer_matte(Image.new("RGB", (256, 256), (128, 128, 128)), res=256)

    def description(self) -> str:
        torch = _require_torch()
        dev = torch.cuda.get_device_name(0) if self.device.type == "cuda" else "CPU"
        return f"{self.info.label} on {dev}"
