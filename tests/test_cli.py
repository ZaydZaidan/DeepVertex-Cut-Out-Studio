"""CLI argument parsing and input resolution tests (no model required)."""
from __future__ import annotations

from PIL import Image

from cutout.cli import build_parser, resolve_inputs


def test_parser_defaults():
    args = build_parser().parse_args(["image.png"])
    assert args.model == "birefnet"
    assert args.quality == "balanced"
    assert args.refine == "guided"
    assert args.fmt == "png"
    assert args.suffix == "-nobg"
    assert args.fill_holes is True


def test_parser_out_alias_and_flags():
    args = build_parser().parse_args(["a.jpg", "-o", "/tmp/out", "--defringe", "--no-fill-holes", "--cpu"])
    assert args.out == "/tmp/out"
    assert args.defringe is True
    assert args.fill_holes is False
    assert args.cpu is True


def test_resolve_inputs_filters_extensions(tmp_path):
    Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / "a.jpg")
    (tmp_path / "notes.txt").write_text("ignore me")
    sub = tmp_path / "sub"
    sub.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(sub / "b.png")

    found = resolve_inputs([str(tmp_path)])
    names = sorted(p.name for p in found)
    assert names == ["a.jpg", "b.png"]


def test_resolve_inputs_missing_path_is_skipped(tmp_path, capsys):
    found = resolve_inputs([str(tmp_path / "nope.jpg")])
    assert found == []
    assert "skip" in capsys.readouterr().err


def test_models_listing_does_not_import_torch():
    # --list-models must work even when torch is unavailable; the engine module
    # must therefore not import torch at module level.
    import cutout.engine as engine_mod

    assert "torch" not in [name for name in vars(engine_mod) if name == "torch"]
