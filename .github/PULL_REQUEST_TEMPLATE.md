<!-- Thank you for contributing! Complete the checklist below. -->

## Summary

<!-- What does this PR do? -->

## Motivation & context

<!-- Why is this change needed? Link any related issues (#NN). -->

## How it was tested

- [ ] `venv/bin/ruff check .` passes
- [ ] `venv/bin/python -m pytest -q` passes (all 22 tests)
- [ ] For UI changes: `scripts/ux_audit.py` run and its summary is pasted below
- [ ] For engine/pipeline changes: verified on GPU **and** `--cpu` (no parity regression)

<details>
<summary>UX audit / test output</summary>

```
(paste output here)
```

</details>

## Checklist

- [ ] No new heavy runtime dependencies (torch/transformers stay lazily imported)
- [ ] Documentation/comments updated where behaviour changed
- [ ] No local artefacts included (`venv/`, `runtime-libs/`, caches, `HANDOFF.md`)
