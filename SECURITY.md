# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x   | ✅        |

## Reporting a vulnerability

Please **do not open a public issue** for a suspected vulnerability.

Report it privately to the maintainer:

- Email: <zaydzihnizaidan@gmail.com>
- Or use GitHub's *Security → Report a vulnerability* (private security advisory) on this repository.

Include a description of the issue, steps to reproduce, and the affected version(s).
You can expect an initial response within **7 days**.

## Scope notes

This project is a **local desktop application**. Of particular interest:

- Anything that makes the app contact unexpected network endpoints
  (the only intended network traffic is one-time model downloads from
  huggingface.co).
- Path traversal / arbitrary file write via CLI or GUI inputs
  (background image paths, output directories, filename suffixes).
- Remote-code execution through `trust_remote_code=True` model loading
  (models are loaded from the pinned public repos above; supply-chain issues
  in model repos are in scope to report).
