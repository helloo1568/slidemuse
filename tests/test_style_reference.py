"""Synthetic pixel and transaction tests; no real generation or visual approval."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import style_reference
from page_production import workspace
from PIL import Image, ImageOps, PngImagePlugin
from record_work import locked_log
from style_reference import create_reference, digest, resolve_reference
from validate_page_spec import load_page_spec, validate_page_spec

ROOT = Path(__file__).resolve().parents[1]
BOX = [220, 200, 160, 90]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def selected(tmp_path):
    spec = json.loads((ROOT / "examples/page-spec.example.json").read_text(encoding="utf-8"))
    spec.update(content_policy="1.1", workflow={"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                                              "outline_ref": "Synthetic test outline"})
    spec["style"].update(option=2, choice="Synthetic option two")
    spec["style"]["tokens"]["reference_images"] = ["styles/02-choice.png"]
    styles = tmp_path / "styles"
    styles.mkdir()
    source = styles / "02-choice.png"
    image = Image.new("RGB", (640, 360), "white")
    for index, color in enumerate(("red", "green", "blue", "yellow", "purple", "orange")):
        x, y = 20 + index % 3 * 200, 60 + index // 3 * 140
        image.paste(color, (x, y, x + 160, y + 90))
        image.putpixel((x + 5, y + 7), (index, 23, 177))
    info = PngImagePlugin.PngInfo()
    info.add_text("slidemuse_style_option", "2")
    info.add_text("slidemuse_style_name", "Synthetic option two")
    image.save(source, pnginfo=info)
    path = tmp_path / "page-spec.json"
    write(path, spec)
    return path, source


@pytest.mark.parametrize("decision", ["selected", "delegated"])
def test_create_binds_exact_selected_crop_and_retains_it_for_portable_drafts(selected, decision):
    path, source = selected
    spec = json.loads(path.read_bytes())
    spec["style"]["decision"] = decision
    write(path, spec)
    before = source.read_bytes()
    result = create_reference(path, "styles/02-reference.png", BOX)
    updated, _ = load_page_spec(path, strict=True)
    declaration = updated["style"]["generation_reference"]
    assert declaration == {"version": "1.0", "kind": "preview-crop", "source": "styles/02-choice.png",
                           "source_sha256": digest(before), "box": BOX, "image": "styles/02-reference.png",
                           "image_sha256": digest(Path(result["path"]).read_bytes())}
    assert updated["style"]["tokens"]["reference_images"] == ["styles/02-choice.png", "styles/02-reference.png"]
    with Image.open(source) as original, Image.open(result["path"]) as crop:
        expected = original.convert("RGBA").crop((220, 200, 380, 290))
        assert crop.size == (160, 90) and crop.convert("RGBA").tobytes() == expected.tobytes()
        assert "slidemuse_style_option" not in crop.info
    assert source.read_bytes() == before
    resolved = resolve_reference(updated, path.parent, required=True)
    assert resolved == {key: result[key] for key in ("kind", "path", "sha256", "source_path", "source_sha256", "box", "option", "choice")}
    assert result["option"] == 2 and result["choice"] == "Synthetic option two"
    assert result["purpose"] == "style-reference-only" and result["image_generation_calls"] == 0
    assert "not a generated or final delivery slide" in result["scope"]
    # Production archives store only the style/canvas/slide intent, not a full Page Spec.
    assert resolve_reference({"style": updated["style"]}, path.parent) == resolved


@pytest.mark.parametrize("policy", [None, "1.0", "1.1"])
def test_missing_derivation_is_readable_but_explicit_generation_requires_it(selected, policy):
    path, _ = selected
    spec = json.loads(path.read_bytes())
    if policy is None:
        spec.pop("content_policy")
    else:
        spec["content_policy"] = policy
    assert validate_page_spec(spec, path.parent)["slides"] == 1
    assert resolve_reference(spec, path.parent) is None
    with pytest.raises(ValueError, match="style-reference.*--box"):
        resolve_reference(spec, path.parent, required=True)


@pytest.mark.parametrize(("damage", "error"), [
    ("source-hash", "source hash changed"),
    ("image-hash", "reference hash changed"),
    ("pixels-with-new-hash", "pixels differ"),
    ("different-box", "pixels differ"),
    ("other-option", "first selected"),
    ("whole-overview", "entire overview"),
    ("wrong-ratio", "16:9"),
    ("outside-box", "inside.*source"),
    ("missing-closure", "retained in"),
    ("renamed-jpeg", "normalized PNG"),
    ("outside-image", "inside Page Spec directory"),
    ("selected-as-single-page", "single-page requires locked-reference"),
])
def test_declared_reference_rejects_substitution_even_for_legacy_specs(selected, damage, error):
    path, source = selected
    result = create_reference(path, "styles/reference.png", BOX)
    spec = json.loads(path.read_bytes())
    spec.pop("content_policy")
    declaration = spec["style"]["generation_reference"]
    target = Path(result["path"])
    if damage == "source-hash":
        source.write_bytes(source.read_bytes() + b"changed source bytes")
    elif damage == "image-hash":
        target.write_bytes(target.read_bytes() + b"changed image bytes")
    elif damage == "pixels-with-new-hash":
        with Image.open(target) as opened:
            image = opened.convert("RGBA")
        image.putpixel((0, 0), (0, 0, 0, 255))
        image.save(target)
        declaration["image_sha256"] = digest(target.read_bytes())
    elif damage == "different-box":
        declaration["box"] = [20, 60, 160, 90]
    elif damage == "other-option":
        other = source.with_name("other-option.png")
        other.write_bytes(source.read_bytes())
        spec["style"]["tokens"]["reference_images"][0] = "styles/other-option.png"
    elif damage == "whole-overview":
        declaration["box"] = [0, 0, 640, 360]
    elif damage == "wrong-ratio":
        declaration["box"] = [220, 200, 160, 100]
    elif damage == "outside-box":
        declaration["box"] = [500, 200, 160, 90]
    elif damage == "missing-closure":
        spec["style"]["tokens"]["reference_images"].remove(declaration["image"])
    elif damage == "renamed-jpeg":
        with Image.open(target) as opened:
            image = opened.convert("RGB")
        image.save(target, format="JPEG")
        declaration["image_sha256"] = digest(target.read_bytes())
    elif damage == "outside-image":
        declaration["image"] = "../escape.png"
    else:
        declaration["kind"] = "single-page"
    with pytest.raises(ValueError, match=error):
        resolve_reference(spec, path.parent)
    if damage not in {"missing-closure", "outside-image"}:
        with pytest.raises(ValueError, match=error):
            validate_page_spec(spec, path.parent)


def test_exif_coordinates_and_pixels_use_the_displayed_source(selected):
    path, original = selected
    source = original.with_suffix(".jpg")
    with Image.open(original) as opened:
        raw_pixels = opened.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6
    raw_pixels.save(source, quality=95, exif=exif)
    before = source.read_bytes()
    spec = json.loads(path.read_bytes())
    spec["style"]["tokens"]["reference_images"] = ["styles/02-choice.jpg"]
    write(path, spec)
    result = create_reference(path, "styles/exif-reference.png", BOX)
    with Image.open(source) as opened, Image.open(result["path"]) as actual:
        expected = ImageOps.exif_transpose(opened).convert("RGBA").crop((220, 200, 380, 290))
        assert actual.size == (160, 90) and actual.convert("RGBA").tobytes() == expected.tobytes()
        assert actual.getexif().get(274, 1) == 1
    assert source.read_bytes() == before
    assert resolve_reference(json.loads(path.read_bytes()), path.parent)["source_sha256"] == digest(before)


def test_locked_single_page_preserves_four_by_three_and_text_only_compatibility(selected):
    path, source = selected
    Image.new("RGB", (320, 240), "purple").save(source)
    spec = json.loads(path.read_bytes())
    spec["style"]["decision"] = "locked-reference"
    write(path, spec)
    implicit = resolve_reference(spec, path.parent, required=True)
    assert implicit["path"] == implicit["source_path"] == str(source)
    assert implicit["box"] == [0, 0, 320, 240]
    result = create_reference(path, "styles/full-page.png", single_page=True)
    assert result["kind"] == "single-page" and result["box"] == [0, 0, 320, 240]
    with Image.open(result["path"]) as image:
        assert image.size == (320, 240)
    assert resolve_reference(json.loads(path.read_bytes()), path.parent)["sha256"] == result["sha256"]
    for decision in ("locked-reference", "skipped"):
        text_only = {"style": {"decision": decision, "visual_spec": "Existing text-only style"}}
        assert resolve_reference(text_only, path.parent, required=True) is None


@pytest.mark.parametrize("box", [None, [0, 0, 640, 360], [-1, 0, 160, 90], [0, 0, 0, 90],
                                  [500, 300, 160, 90], [0, 0, 160, 100], [0, 0, 1, 1], [0, 0, 160.0, 90]])
def test_invalid_or_implicit_crop_never_changes_spec_or_output(selected, box):
    path, source = selected
    before = path.read_bytes(), source.read_bytes()
    with pytest.raises(ValueError):
        create_reference(path, "new/reference.png", box)
    assert (path.read_bytes(), source.read_bytes()) == before
    assert not (path.parent / "new").exists()


def test_selected_overview_cannot_be_declared_single_page(selected):
    path, _ = selected
    before = path.read_bytes()
    with pytest.raises(ValueError, match="explicitly locked-reference"):
        create_reference(path, "styles/full.png", single_page=True)
    assert path.read_bytes() == before and not (path.parent / "styles/full.png").exists()


@pytest.mark.parametrize("target_kind", ["source", "slide", "unrelated", "another-reference", "outside", "managed-state"])
def test_output_cannot_overwrite_inputs_or_unrelated_files(selected, target_kind):
    path, source = selected
    spec = json.loads(path.read_bytes())
    if target_kind == "source":
        output = source
    elif target_kind == "slide":
        output = path.parent / spec["slides"][0]["image_file"]
    elif target_kind == "another-reference":
        output = source.with_name("keep.png")
        output.write_bytes(source.read_bytes())
        spec["style"]["tokens"]["reference_images"].append("styles/keep.png")
        write(path, spec)
    elif target_kind == "outside":
        output = path.parent.parent / (path.parent.name + "-outside.png")
    elif target_kind == "managed-state":
        output = workspace(path) / "artifacts/reference.png"
    else:
        output = source.with_name("unrelated.png")
        output.write_bytes(b"unrelated existing file")
    before_spec = path.read_bytes()
    before = output.read_bytes() if output.exists() else None
    with pytest.raises(ValueError):
        create_reference(path, output, BOX)
    assert path.read_bytes() == before_spec
    if before is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == before


def test_registered_reference_is_idempotent_but_new_crop_needs_new_path(selected):
    path, _ = selected
    first = create_reference(path, "styles/reference.png", BOX)
    target = Path(first["path"])
    before = path.read_bytes(), target.read_bytes(), target.stat().st_mtime_ns
    assert create_reference(path, target, BOX) == first
    assert (path.read_bytes(), target.read_bytes(), target.stat().st_mtime_ns) == before
    with pytest.raises(ValueError, match="already exists"):
        create_reference(path, target, [20, 60, 160, 90])
    assert (path.read_bytes(), target.read_bytes(), target.stat().st_mtime_ns) == before


def test_failed_spec_validation_leaves_no_published_reference(selected):
    path, _ = selected
    spec = json.loads(path.read_bytes())
    spec["slides"][0]["elements"][0]["bbox_hint"] = [1590, 0, 20, 10]
    write(path, spec)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="outside canvas"):
        create_reference(path, "new/reference.png", BOX)
    assert path.read_bytes() == before and not (path.parent / "new").exists()
    assert not list(path.parent.glob(".style-reference-*"))


def test_spec_publish_failure_rolls_back_new_image_and_directories(selected, monkeypatch):
    path, _ = selected
    before = path.read_bytes()

    def fail_replace(*args):
        raise OSError("Synthetic spec publication failure")

    monkeypatch.setattr(style_reference.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Synthetic spec publication"):
        create_reference(path, "new/deep/reference.png", BOX)
    assert path.read_bytes() == before and not (path.parent / "new").exists()
    assert not list(path.parent.glob(".style-reference-*"))


def test_racing_output_is_not_overwritten_or_deleted(selected, monkeypatch):
    path, _ = selected
    before = path.read_bytes()
    link = style_reference.os.link

    def race(source, target):
        Path(target).write_bytes(b"independent concurrent output")
        link(source, target)

    monkeypatch.setattr(style_reference.os, "link", race)
    with pytest.raises(FileExistsError):
        create_reference(path, "new/reference.png", BOX)
    assert path.read_bytes() == before
    assert (path.parent / "new/reference.png").read_bytes() == b"independent concurrent output"


@pytest.mark.parametrize("changed", ["spec", "source"])
def test_input_change_during_preparation_is_not_overwritten(selected, monkeypatch, changed):
    path, source = selected
    import validate_page_spec as validation
    validate = validation.validate_page_spec
    original = path.read_bytes()

    def concurrent_update(spec, base, *args, **kwargs):
        result = validate(spec, base, *args, **kwargs)
        if changed == "spec":
            current = json.loads(path.read_bytes())
            current["title"] = "New independent user revision"
            write(path, current)
        else:
            source.write_bytes(source.read_bytes() + b"independent source revision")
        return result

    monkeypatch.setattr(validation, "validate_page_spec", concurrent_update)
    with pytest.raises(ValueError, match="changed during reference creation"):
        create_reference(path, "new/reference.png", BOX)
    if changed == "spec":
        assert json.loads(path.read_bytes())["title"] == "New independent user revision"
    else:
        assert path.read_bytes() == original and source.read_bytes().endswith(b"independent source revision")
    assert not (path.parent / "new").exists()


def test_reference_creation_uses_the_same_lock_as_production(selected):
    path, _ = selected
    before = path.read_bytes()
    with locked_log(workspace(path) / "transaction"), pytest.raises(OSError):
        create_reference(path, "styles/reference.png", BOX)
    assert path.read_bytes() == before and not (path.parent / "styles/reference.png").exists()


def test_cli_resolves_relative_output_from_spec_not_cwd(selected, tmp_path):
    path, _ = selected
    other = tmp_path / "other-working-directory"
    other.mkdir()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/style_reference.py"), str(path),
                             "--box", *map(str, BOX), "--output", "styles/cli-reference.png"],
                            cwd=other, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["path"] == str(path.parent / "styles/cli-reference.png")
    assert report["purpose"] == "style-reference-only"
    assert not (other / "styles").exists()


def test_schema_rejects_extra_or_incomplete_derivation_fields(selected):
    path, _ = selected
    create_reference(path, "styles/reference.png", BOX)
    spec = json.loads(path.read_bytes())
    for field in ("unexpected", "source_sha256"):
        invalid = copy.deepcopy(spec)
        if field == "unexpected":
            invalid["style"]["generation_reference"][field] = "unrecorded choice"
        else:
            del invalid["style"]["generation_reference"][field]
        with pytest.raises(ValueError, match="Page Spec schema"):
            validate_page_spec(invalid, path.parent)
