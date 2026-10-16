import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from build_image_ppt import build_deck
from PIL import Image
from preserved_assets import expected_patch
from validate_page_spec import validate_page_spec


@pytest.fixture
def evidence_page(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples/page-spec.example.json"
    spec = json.loads(example.read_text(encoding="utf-8"))
    spec["style"].pop("tokens", None)
    slide = spec["slides"][0]
    slide.update(image_file="slide.png", image_status="approved")
    # A nonuniform image exposes stretching, shifts and pixel changes.
    source = Image.new("RGB", (60, 40), "white")
    for x in range(source.width):
        for y in range(source.height):
            source.putpixel((x, y), (x * 4, y * 6, (x + y) * 2))
    source.save(tmp_path / "map.png")
    declaration = {"file": "map.png", "sha256": hashlib.sha256(
        (tmp_path / "map.png").read_bytes()).hexdigest(), "region": [10, 10, 90, 60]}
    slide["elements"][2]["preserve_asset"] = declaration
    page = Image.new("RGB", (320, 180), "white")
    page.paste(expected_patch(tmp_path, declaration), (10, 10))
    page.save(tmp_path / "slide.png")
    return spec, tmp_path, declaration


def test_exact_source_pixels_pass_and_survive_export(evidence_page):
    spec, root, _ = evidence_page
    validate_page_spec(spec, root, require_images=True, strict=True)
    (root / "page-spec.json").write_text(json.dumps(spec), encoding="utf-8")
    args = argparse.Namespace(input_dir=root / "page-spec.json", output=root / "deck.pptx",
                              extensions=[".png"], width=None, height=None,
                              background="FFFFFF", title="", max_width=0,
                              jpeg_quality=0, fit="contain")
    assert build_deck(args)["slides"] == 1
    with ZipFile(root / "deck.pptx") as deck:
        media = [name for name in deck.namelist() if name.startswith("ppt/media/")]
        assert len(media) == 1
        assert deck.read(media[0]) == (root / "slide.png").read_bytes()


def test_changed_evidence_pixel_rejected_but_surroundings_allowed(evidence_page):
    spec, root, _ = evidence_page
    with Image.open(root / "slide.png") as page:
        page.putpixel((300, 150), (255, 0, 0))
        page.save(root / "slide.png")
    validate_page_spec(spec, root, require_images=True)
    with Image.open(root / "slide.png") as page:
        page.putpixel((25, 25), (255, 0, 0))
        page.save(root / "slide.png")
    with pytest.raises(ValueError, match="pixels changed"):
        validate_page_spec(spec, root, require_images=True)


@pytest.mark.parametrize("case,match", [
    ("hash", "source hash changed"), ("aspect", "aspect ratio"),
    ("outside", "outside actual"), ("traversal", "inside Page Spec"),
    ("overlap", "must not overlap"), ("self", "independent"),
    ("lossy", "lossless PNG"), ("alpha", "must be opaque"),
])
def test_evidence_contract_rejects_invalid_or_stale_inputs(evidence_page, case, match):
    spec, root, declaration = evidence_page
    slide = spec["slides"][0]
    if case == "hash":
        Image.new("RGB", (60, 40), "red").save(root / "map.png")
    elif case == "aspect":
        declaration["region"][2] = 100
    elif case == "outside":
        declaration["region"][0] = 300
    elif case == "traversal":
        declaration["file"] = "../map.png"
    elif case == "overlap":
        duplicate = dict(slide["elements"][2], id="second-map")
        duplicate["preserve_asset"] = dict(declaration)
        slide["elements"].append(duplicate)
    elif case == "self":
        declaration["file"] = slide["image_file"]
    elif case == "lossy":
        with Image.open(root / "slide.png") as page:
            page.save(root / "slide.jpg")
        slide["image_file"] = "slide.jpg"
    elif case == "alpha":
        with Image.open(root / "slide.png") as page:
            page = page.convert("RGBA")
            page.putpixel((25, 25), (0, 0, 0, 0))
            page.save(root / "slide.png")
    with pytest.raises(ValueError, match=match):
        validate_page_spec(spec, root, require_images=True)


@pytest.mark.parametrize("option", ["max_width", "jpeg_quality"])
def test_export_cannot_silently_recompress_evidence(evidence_page, option):
    spec, root, _ = evidence_page
    (root / "page-spec.json").write_text(json.dumps(spec), encoding="utf-8")
    args = argparse.Namespace(input_dir=root / "page-spec.json", output=root / "deck.pptx",
                              max_width=0, jpeg_quality=0)
    setattr(args, option, 80)
    with pytest.raises(ValueError, match="forbid"):
        build_deck(args)
    assert not (root / "deck.pptx").exists()
