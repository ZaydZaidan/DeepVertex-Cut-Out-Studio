# Contributing to DeepVertex Cut-Out Studio

Thanks for your interest in contributing! This document covers local setup,
code style, and testing expectations.

## Development setup

```bash
git clone https://github.com/ZaydZaidan/DeepVertex-Cut-Out-Studio.git
cd DeepVertex-Cut-Out-Studio

python3 -m venv venv
venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130  # or the CPU index
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e ".[dev]"
```

## Quality gates

A pull request is merged only when all of these pass:

1. **Lint** — `venv/bin/ruff check .` must be clean
   (line length 120, rule set `E,F,W,I,UP,B` — see `pyproject.toml`).
2. **Tests** — `venv/bin/python -m pytest -q` must pass. The suite is
   CPU-only and must never require a GPU or a real model download; engines
   are faked in tests.
3. **UI changes** — additionally run the offscreen audit and include its
   summary in the PR description:

   ```bash
   venv/bin/python scripts/gui_smoke.py /tmp/smoke-out IMG...   # needs sample images
   venv/bin/python scripts/ux_audit.py /tmp/audit-out
   ```

4. **No new heavy dependencies** without justification — torch/transformers
   are intentionally imported lazily so lightweight commands and tests work
   without them.

## Conventions

- Python 3.10+; type hints encouraged; docstrings explain *why*, not *what*.
- Commits: imperative, concise subject lines (e.g. `fix: guard fp16 inference on CPU`).
- Documentation, comments and commit messages are in English.
- Do not commit local artefacts: `venv/`, `runtime-libs/`, model caches,
  `HANDOFF.md`, `__pycache__`, build outputs (all gitignored).

## Reporting bugs

Open an issue using the bug report template — include your OS, Python and
torch versions, GPU, the exact command or GUI action, and the full error
text (for the GUI, paste `~/.cache/cutout-studio/gui.log`).
