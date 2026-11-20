import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from build_style_overview import label_overview
from PIL import Image
from validate_page_spec import load_page_spec, validate_page_spec


@pytest.fixture
def page_spec(tmp_path):
    spec = {
        "version": "1.0",
        "title": "Test deck",
        "content_approved": True,
        "content_version": "outline-v1",
        "content_authorization": "User approved outline v1",
        "canvas": {"width": 1600, "height": 900},
        "style": {
            "decision": "selected",
            "authorization": "User selected option 1",
            "visual_spec": "Clean editorial",
        },
        "slides": [
            {
                "id": "s01",
                "page_number": 1,
                "title": "Accurate title",
                "core_message": "One conclusion",
                "visual_brief": "Title left, image right",
                "image_file": "slides/01.png",
                "image_status": "pending",
                "elements": [
                    {
                        "id": "title",
                        "kind": "text",
                        "role": "heading",
                        "native_intent": "native",
                        "source_ref": "report p1",
                        "confirmation_status": "confirmed",
                        "text": "Accurate title",
                        "bbox_hint": [100, 80, 800, 120],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "page-spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_example_is_valid():
    path = Path(__file__).resolve().parents[1] / "examples/page-spec.example.json"
    _, result = load_page_spec(path)
    assert result == {"slides": 1, "elements": 3, "unresolved": 0}


@pytest.mark.parametrize(("problem", "error"), [
    ("missing", "workflow"),
    ("stale", "current content_version"),
    ("blank-outline", "outline reference"),
    ("blank-authorization", "user content authorization"),
    ("blank-style-authorization", "user style authorization"),
])
def test_new_workflow_requires_recorded_current_approval(page_spec, problem, error):
    spec, _ = load_page_spec(page_spec)
    spec["content_policy"] = "1.1"
    spec["slides"][0]["role"] = "cover"
    spec["style"]["decision"] = "locked-reference"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "Message 4, complete outline v1"}
    validate_page_spec(spec, page_spec.parent, strict=True)
    if problem == "missing":
        del spec["workflow"]
    elif problem == "stale":
        spec["content_version"] = "outline-v2"
    elif problem == "blank-outline":
        spec["workflow"]["outline_ref"] = " "
    elif problem == "blank-authorization":
        spec["content_authorization"] = " "
    else:
        spec["style"]["authorization"] = " "
    with pytest.raises(ValueError, match=error):
        validate_page_spec(spec, page_spec.parent, strict=True)


def test_workflow_style_selection_binds_number_name_and_preview(page_spec):
    spec, _ = load_page_spec(page_spec)
    spec["content_policy"] = "1.1"
    spec["slides"][0]["role"] = "cover"
    spec["workflow"] = {"content_mode": "reused", "approved_content_version": "outline-v1",
                        "outline_ref": "Existing deck v1 reused at the user's request"}
    style = spec["style"]
    with pytest.raises(ValueError, match="numbered option and name"):
        validate_page_spec(spec, page_spec.parent)
    style.update(option=2, choice="Architectural journal")
    with pytest.raises(ValueError, match="labeled preview"):
        validate_page_spec(spec, page_spec.parent)
    example = Path(__file__).resolve().parents[1] / "examples/page-spec.example.json"
    style["tokens"] = json.loads(example.read_text(encoding="utf-8"))["style"]["tokens"]
    style["tokens"]["reference_images"] = ["02-architectural-journal.png"]
    with pytest.raises(ValueError, match="Missing style reference"):
        validate_page_spec(spec, page_spec.parent)
    raw = page_spec.parent / "preview.png"
    Image.new("RGB", (320, 180), "ivory").save(raw)
    label_overview(raw, page_spec.parent / "02-architectural-journal.png", 2, "Architectural journal")
    assert validate_page_spec(spec, page_spec.parent)["slides"] == 1
    style["option"] = 3
    with pytest.raises(ValueError, match="differs from the labeled preview"):
        validate_page_spec(spec, page_spec.parent)


def test_requires_approval_and_existing_images(page_spec):
    spec, _ = load_page_spec(page_spec)
    spec["slides"][0]["image_status"] = "approved"
    page_spec.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing approved slide image"):
        load_page_spec(page_spec, require_images=True)
    image = page_spec.parent / "slides/01.png"
    image.parent.mkdir()
    Image.new("RGB", (16, 9), "white").save(image)
    _, result = load_page_spec(page_spec, require_images=True)
    assert result["slides"] == 1


@pytest.mark.parametrize("rotated", [False, True])
def test_approved_image_ratio_allows_pixel_rounding_and_exif(page_spec, rotated):
    spec, _ = load_page_spec(page_spec)
    slide = spec["slides"][0]
    slide.update(image_status="approved", image_file="slides/01.jpg")
    target = page_spec.parent / slide["image_file"]
    target.parent.mkdir()
    exif = Image.Exif()
    if rotated:
        exif[0x0112] = 6
    size = (941, 1672) if rotated else (1672, 941)
    Image.new("RGB", size, "white").save(target, exif=exif)
    assert validate_page_spec(spec, page_spec.parent, require_images=True, strict=True)["slides"] == 1


@pytest.mark.parametrize("mutation", ["approval", "duplicate", "outside", "traversal"])
def test_invalid_page_spec_rejected(page_spec, mutation):
    spec, _ = load_page_spec(page_spec)
    if mutation == "approval":
        spec["content_approved"] = False
    elif mutation == "duplicate":
        spec["slides"][0]["elements"].append(
            copy.deepcopy(spec["slides"][0]["elements"][0])
        )
    elif mutation == "outside":
        spec["slides"][0]["elements"][0]["bbox_hint"] = [1500, 20, 200, 50]
    elif mutation == "traversal":
        spec["slides"][0]["image_file"] = "../outside.png"
    with pytest.raises(ValueError):
        validate_page_spec(spec, page_spec.parent)


def test_cli_from_other_working_directory(page_spec, tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/validate_page_spec.py"
    result = subprocess.run(
        [sys.executable, str(script), str(page_spec)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "1 slides, 1 semantic elements, 0 unresolved" in result.stdout


def test_strict_rejects_unresolved(page_spec):
    spec, _ = load_page_spec(page_spec)
    spec["slides"][0]["elements"][0]["confirmation_status"] = "unresolved"
    spec["slides"][0]["elements"][0]["confidence"] = 0.5
    assert validate_page_spec(spec, page_spec.parent)["unresolved"] == 1
    with pytest.raises(ValueError, match="1 unresolved"):
        validate_page_spec(spec, page_spec.parent, strict=True)


def test_style_reference_must_exist_inside_task(page_spec):
    spec, _ = load_page_spec(page_spec)
    spec["style"]["tokens"] = {
        "palette": {"background": "#FFFFFF", "text": "#111111", "primary": "#123456", "accent": "#ABCDEF"},
        "typography": {"heading_font": "Arial", "body_font": "Arial", "heading_size": 50, "body_size": 24},
        "layout": {"grid": "two columns", "margin_px": 100, "spacing_px": 24},
        "image_treatment": "soft light", "reference_images": ["styles/selected.png"],
    }
    with pytest.raises(ValueError, match="Missing style reference"):
        validate_page_spec(spec, page_spec.parent)
    target = page_spec.parent / "styles/selected.png"
    target.parent.mkdir()
    Image.new("RGB", (16, 9), "white").save(target)
    assert validate_page_spec(spec, page_spec.parent)["slides"] == 1
    spec["style"]["tokens"]["reference_images"] = ["../outside.png"]
    with pytest.raises(ValueError, match="inside Page Spec directory"):
        validate_page_spec(spec, page_spec.parent)


def test_slide_role_accepts_the_published_enum_only(page_spec):
    spec, _ = load_page_spec(page_spec)
    for role in ("cover", "agenda", "section-divider", "concept", "process", "comparison",
                 "timeline", "data-evidence", "architecture", "case-study", "summary", "qa"):
        spec["slides"][0]["role"] = role
        assert validate_page_spec(spec, page_spec.parent)["slides"] == 1
    spec["slides"][0]["role"] = "agenda-list"
    with pytest.raises(ValueError, match="schema|density|duplicate|readable"):
        validate_page_spec(spec, page_spec.parent)


def test_slide_key_points_require_three_to_five_unique_items(page_spec):
    spec, _ = load_page_spec(page_spec)
    spec["slides"][0]["role"] = "comparison"
    spec["slides"][0]["key_points"] = ["口径相同", "差异方向相反", "差距 8 个百分点"]
    assert validate_page_spec(spec, page_spec.parent)["slides"] == 1


@pytest.mark.parametrize("points", [
    [],
    ["少于三条"],
    ["一", "二"],
    ["一", "二", "三", "四", "五", "六"],
    ["换词重复", "换词重复", "第三条"],
    ["一", "二", ""],
])
def test_slide_key_points_reject_the_wrong_density(page_spec, points):
    spec, _ = load_page_spec(page_spec)
    spec["slides"][0]["role"] = "concept"
    spec["slides"][0]["key_points"] = points
    with pytest.raises(ValueError, match="schema|density|duplicate|readable"):
        validate_page_spec(spec, page_spec.parent)


def test_specs_without_role_and_key_points_stay_readable(page_spec):
    spec, _ = load_page_spec(page_spec)
    assert "role" not in spec["slides"][0] and "key_points" not in spec["slides"][0]
    assert validate_page_spec(spec, page_spec.parent)["slides"] == 1
