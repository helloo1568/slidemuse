"""Offline regressions for preserving user content through editable reconstruction."""
import copy
import hashlib
import json
import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageOps
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches
from test_editable_backend import ROOT, RUNTIME, invoke


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def backend_script(name, *args):
    return subprocess.run([sys.executable, str(RUNTIME / name), *map(str, args)],
                          capture_output=True, encoding="utf-8", check=False)


def prepared_notes_run(tmp_path):
    spec = json.loads((ROOT / "examples/page-spec.example.json").read_text(encoding="utf-8"))
    spec.update(content_policy="1.1", canvas={"width": 640, "height": 360},
                workflow={"content_mode": "reused", "approved_content_version": spec["content_version"],
                          "outline_ref": "Synthetic approved note regression fixture"})
    spec["style"].update(decision="locked-reference", authorization="Reuse the supplied test images")
    original = spec["slides"][0]
    spec["slides"] = []
    for number in (1, 2):
        source = tmp_path / f"source-{number}.png"
        image = Image.new("RGB", (640, 360), "white")
        ImageDraw.Draw(image).text((40, 30), f"Page {number}", fill="black")
        image.save(source)
        slide = copy.deepcopy(original)
        slide.update(id=f"s{number:02d}", page_number=number, title=f"Page {number}",
                     core_message=f"Page {number}", image_file=source.name, image_status="approved",
                     image_origin={"kind": "provided", "source_ref": "Supplied synthetic regression image",
                                   "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
                     elements=[{"id": "title", "kind": "text", "role": "Title", "native_intent": "native",
                                "source_ref": "Synthetic fixture", "confirmation_status": "confirmed",
                                "text": f"Page {number}"}])
        if number == 1:
            slide["speaker_notes"] = "  User notes\r\n\r\nSecond paragraph\vSoft break\r\n"
        spec["slides"].append(slide)
    spec_path = tmp_path / "page-spec.json"
    write_json(spec_path, spec)
    job = tmp_path / "run"
    result = invoke("--offline", "prepare", "--page-spec", spec_path, "--job-dir", job)
    assert result.returncode == 0, result.stdout + result.stderr
    for number in (1, 2):
        page = job / f"pages/page_{number:03d}"
        request = json.loads((page / "page_request.json").read_text(encoding="utf-8"))
        slide = request["slide"]
        manifest = {"source": {"width_px": 640, "height_px": 360}, "slide": slide,
                    "content_box": request["content_box"],
                    "text_boxes": [{"text": f"Page {number}", "box_px": [40, 30, 400, 60],
                                    "font_size": 24, "fit_text": False}],
                    "shapes": [], "tables": [], "images": [], "visual_inventory": [],
                    "background_strategy": {"mode": "native-or-script", "comparison_note": "Synthetic fixture"},
                    "quality_checks": dict.fromkeys(["font_size_calibrated", "visual_inventory_matched",
                                                      "background_strategy_checked", "shape_corner_geometry_checked"], True)}
        write_json(page / "manifest.json", manifest)
        built = invoke("--offline", "page", "build", page)
        assert built.returncode == 0, built.stdout + built.stderr
        validated = invoke("--offline", "page", "validate", page, "--report", "validation.json")
        assert validated.returncode == 0, validated.stdout + validated.stderr
    return job


def test_page_spec_notes_survive_rebuild_and_independent_validation(tmp_path):
    job = prepared_notes_run(tmp_path)
    output = tmp_path / "rebuilt.pptx"
    build_args = ("--deck-manifest", job / "deck_manifest.json", "--out", output)
    result = backend_script("build_pptx_from_manifest.py", *build_args)
    assert result.returncode == 0, result.stdout + result.stderr
    prs = Presentation(output)
    assert prs.slides[0].notes_slide.notes_text_frame.text == "  User notes\n\nSecond paragraph\vSoft break\n"
    assert not prs.slides[1].has_notes_slide
    result = backend_script("validate_pptx.py", output, "--deck-manifest", job / "deck_manifest.json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["passed"]

    # Losing the assembly input must fail before replacing an existing delivery.
    prior = output.read_bytes()
    write_json(job / "notes_manifest.json", {"notes": []})
    result = backend_script("build_pptx_from_manifest.py", *build_args)
    assert result.returncode != 0 and "approved Page Spec" in result.stderr
    assert output.read_bytes() == prior

    # A stale/empty notes manifest cannot make an actually corrupted deck pass.
    prs.slides[0].notes_slide.notes_text_frame.text = "Wrong notes"
    prs.save(output)
    result = backend_script("validate_pptx.py", output, "--deck-manifest", job / "deck_manifest.json")
    assert result.returncode != 0
    assert json.loads(result.stdout)["notes_contract_errors"]


def test_cover_crop_and_original_pptx_canvas_survive_prepare(tmp_path):
    source_dir = tmp_path / "slides"
    source_dir.mkdir()
    image = Image.new("RGB", (400, 200), "blue")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 19, 199), fill="red")
    draw.rectangle((380, 0, 399, 199), fill="green")
    image.save(source_dir / "01.png")
    original = tmp_path / "source.pptx"
    built = subprocess.run([sys.executable, str(ROOT / "scripts/build_image_ppt.py"), str(source_dir),
                            str(original), "--fit", "cover", "--width", "8", "--height", "4.5"],
                           capture_output=True, encoding="utf-8", check=False)
    assert built.returncode == 0, built.stderr
    picture = Presentation(original).slides[0].shapes[0]
    assert picture.crop_left > 0 and picture.crop_right > 0
    job = tmp_path / "run"
    result = invoke("--offline", "prepare", original, "--job-dir", job)
    assert result.returncode == 0, result.stdout + result.stderr
    deck = json.loads((job / "deck_manifest.json").read_text(encoding="utf-8"))
    assert deck["slide"]["width"] == 8
    assert deck["slide"]["height"] == 4.5
    with Image.open(job / "pages/page_001/source.png") as normalized:
        assert abs(normalized.width - normalized.height * 16 / 9) <= 1
        assert normalized.getpixel((0, normalized.height // 2)) == (0, 0, 255)
        assert normalized.getpixel((normalized.width - 1, normalized.height // 2)) == (0, 0, 255)


@pytest.mark.parametrize("change", ["rotation", "flip", "overlay"])
def test_unhandled_picture_transforms_are_rejected(tmp_path, change):
    image = tmp_path / "image.png"
    Image.new("RGB", (640, 360), "white").save(image)
    original = tmp_path / "input.pptx"
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(8), Inches(4.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    picture = slide.shapes.add_picture(str(image), 0, 0, width=prs.slide_width, height=prs.slide_height)
    if change == "rotation":
        picture.rotation = 90
    elif change == "flip":
        picture._element.spPr.xfrm.flipH = True
    else:
        slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(1), Inches(1))
    prs.save(original)
    job = tmp_path / "run"
    result = invoke("--offline", "prepare", original, "--job-dir", job)
    assert result.returncode != 0 and "render the slide" in result.stderr
    assert not (job / "deck_manifest.json").exists()


def test_exif_orientation_is_applied_before_normalization(tmp_path):
    source = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (400, 200), "blue")
    ImageDraw.Draw(image).rectangle((0, 0, 100, 199), fill="red")
    exif = Image.Exif()
    exif[0x0112] = 6
    image.save(source, exif=exif)
    job = tmp_path / "run"
    result = invoke("--offline", "prepare", source, "--job-dir", job)
    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(source) as original, Image.open(job / "pages/page_001/source.png") as normalized:
        expected = ImageOps.exif_transpose(original).convert("RGB")
        assert normalized.size == expected.size == (200, 400)
        assert ImageChops.difference(expected, normalized).getbbox() is None
