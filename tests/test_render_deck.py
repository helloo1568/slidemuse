import json
import sys
from pathlib import Path

import pytest
import render_deck
from PIL import Image
from pptx import Presentation


@pytest.mark.parametrize("metadata", ["Pages: 1\n", "Pages: 3\n", "Title: no page count\n"])
def test_selected_libreoffice_rejects_incomplete_pdf_before_assigning_page_numbers(tmp_path, monkeypatch, metadata):
    deck = tmp_path / "hidden.pptx"
    presentation = Presentation()
    for _ in range(2):
        presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.slides[0]._element.set("show", "0")
    presentation.save(deck)
    monkeypatch.setattr(render_deck.shutil, "which", lambda name: name)
    raster_calls = []

    def execute(command, **_kwargs):
        if command[0] == "soffice":
            options = json.loads(command[command.index("--convert-to") + 1].split(":", 2)[2])
            assert options["ExportHiddenSlides"]["value"] == "true"
            output = Path(command[command.index("--outdir") + 1])
            (output / "hidden.pdf").write_bytes(b"synthetic PDF; parsed by the stub below")
            return ""
        if command[0] == "pdfinfo":
            return metadata
        raster_calls.append(command)
        raise AssertionError("An unverified PDF must not be assigned PPTX page numbers")

    monkeypatch.setattr(render_deck, "execute", execute)
    output = tmp_path / "selected"
    with pytest.raises(RuntimeError, match="page identity cannot be verified"):
        render_deck.render_selected(deck, output, 320, "libreoffice", [1])
    assert raster_calls == []
    assert not (output / "001.png").exists()


def test_render_deck_writes_every_slide_and_comparison(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    presentation = Presentation()
    presentation.slide_height = presentation.slide_width * 9 // 16
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(deck)
    for number, color in enumerate(("white", "black"), 1):
        path = tmp_path / f"source-{number}.png"
        Image.new("RGB", (160, 90), color).save(path)
    spec = tmp_path / "page-spec.json"
    spec.write_text(json.dumps({"slides": [
        {"id": "s01", "image_status": "approved", "image_file": "source-1.png"},
        {"id": "s02", "image_status": "approved", "image_file": "source-2.png"},
    ]}), encoding="utf-8")

    def fake_renderer(_deck, output, width, height):
        for index in range(1, 3):
            Image.new("RGB", (width, height), "white").save(output / f"{index:03d}.png")

    monkeypatch.setattr(render_deck, "render_powerpoint", fake_renderer)
    monkeypatch.setattr(sys, "argv", ["render_deck.py", str(deck), str(tmp_path / "review"),
                                      "--backend", "powerpoint", "--page-spec", str(spec)])
    render_deck.main()
    report = json.loads((tmp_path / "review/render-report.json").read_text(encoding="utf-8"))
    assert len(report["slides"]) == 2
    assert report["slides"][0]["mean_absolute_difference"] == 0
    assert report["slides"][1]["mean_absolute_difference"] == 255
    assert report["slides"][0]["reference_sha256"] == render_deck.sha256(tmp_path / "source-1.png")
    assert report["slides"][1]["reference_sha256"] == render_deck.sha256(tmp_path / "source-2.png")
    assert report["slides"][0]["rendered"] == str(tmp_path / "review/001.png")
    assert (tmp_path / "review/review.png").is_file()
    assert all((tmp_path / "review" / f"{index:03d}.png").is_file() for index in (1, 2))


def test_selected_render_keeps_original_index_and_checks_dimensions(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    presentation = Presentation()
    for _ in range(3):
        presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(deck)
    calls = []

    def selected(_deck, output, width, height, slides):
        calls.append(slides)
        for index in slides:
            Image.new("RGB", (width, height), "white").save(output / f"{index:03d}.png")

    monkeypatch.setattr(render_deck, "render_powerpoint", selected)
    output = tmp_path / "selected"
    assert render_deck.render_selected(deck, output, 320, "powerpoint", [3]) == "powerpoint"
    assert calls == [[3]]
    assert sorted(p.name for p in output.iterdir()) == ["003.png"]
    for invalid in ([1, 1], [4], [True], []):
        with pytest.raises(ValueError, match="indices"):
            render_deck.render_selected(deck, tmp_path / "bad", 320, "powerpoint", invalid)

    def incorrect(_deck, output, width, height, slides):
        Image.new("RGB", (1, 1)).save(output / "001.png")

    monkeypatch.setattr(render_deck, "render_powerpoint", incorrect)
    with pytest.raises(RuntimeError, match="incorrect dimensions"):
        render_deck.render_selected(deck, tmp_path / "wrong", 320, "powerpoint", [1])
    assert not (tmp_path / "wrong/001.png").exists()


def test_portrait_review_preserves_readable_page_proportions(tmp_path):
    rendered = tmp_path / "portrait.png"
    Image.new("RGB", (612, 792), "white").save(rendered)
    output = tmp_path / "review"
    output.mkdir()
    report = render_deck.build_review([rendered], output, [rendered])
    with Image.open(output / "review.png") as sheet:
        assert sheet.width == 1920
        # The page area remains portrait instead of shrinking into a 360px landscape row.
        assert sheet.height > 800
    assert report[0]["mean_absolute_difference"] == 0


def test_overwrite_does_not_reuse_old_powerpoint_measurements(tmp_path, monkeypatch):
    deck = tmp_path / "new.pptx"
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(deck)
    output = tmp_path / "review"
    output.mkdir()
    # This belongs to a deleted object from an older PowerPoint render.
    (output / "001.layout.json").write_text(json.dumps({
        "page_number": 1, "slide_width_pt": 720, "slide_height_pt": 540,
        "items": [{"element_id": "deleted-object", "status": "measured", "bounds": [20, 20, 100, 50],
                   "content_width_pt": 500, "content_height_pt": 50,
                   "available_width_pt": 100, "available_height_pt": 50}]}), encoding="utf-8")

    def renderer(_deck, target, width, height, count):
        assert count == 1
        Image.new("RGB", (width, height), "white").save(target / "001.png")

    monkeypatch.setattr(render_deck, "render_libreoffice", renderer)
    monkeypatch.setattr(sys, "argv", ["render_deck.py", str(deck), str(output),
                                      "--backend", "libreoffice", "--overwrite"])
    render_deck.main()
    report = json.loads((output / "render-report.json").read_text(encoding="utf-8"))
    assert report["backend"] == "libreoffice"
    assert report["deck_sha256"] == render_deck.sha256(deck)
    assert report["measured_layout"] == []
    assert not (output / "001.layout.json").exists()


@pytest.mark.parametrize("reference_name", ["001.png", "002.png", "1000.png", "review.png"])
def test_overwrite_rejects_reference_collisions_before_render_or_deletion(tmp_path, monkeypatch, reference_name):
    deck = tmp_path / "deck.pptx"
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(deck)
    output = tmp_path / "references"
    output.mkdir()
    reference = output / reference_name
    Image.new("RGB", (160, 90), "red").save(reference)
    (output / "001.layout.json").write_bytes(b"retained previous measurements")
    spec = tmp_path / "page-spec.json"
    spec.write_text(json.dumps({"slides": [
        {"id": "s01", "image_status": "approved", "image_file": f"references/{reference_name}"}]}), encoding="utf-8")
    before = {p: p.read_bytes() for p in output.iterdir()}

    def unexpected(*_args):
        raise AssertionError("Collisions must fail before invoking a renderer")

    monkeypatch.setattr(render_deck, "render_powerpoint", unexpected)
    monkeypatch.setattr(sys, "argv", ["render_deck.py", str(deck), str(output), "--overwrite",
                                      "--page-spec", str(spec), "--backend", "powerpoint"])
    with pytest.raises(SystemExit) as error:
        render_deck.main()
    assert error.value.code == 2
    assert {p: p.read_bytes() for p in output.iterdir()} == before


@pytest.mark.parametrize("input_kind", ["deck", "page-spec", "reference-symlink"])
def test_render_protects_nonimage_inputs_and_path_aliases(tmp_path, monkeypatch, input_kind):
    output = tmp_path / "review"
    output.mkdir()
    deck = output / "001.png" if input_kind == "deck" else tmp_path / "deck.pptx"
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(deck)
    reference = tmp_path / "reference.png"
    Image.new("RGB", (160, 90), "red").save(reference)
    if input_kind == "reference-symlink":
        try:
            (output / "001.png").symlink_to(reference)
        except OSError:
            pytest.skip("Symlink creation is unavailable on this platform")
    spec = output / "render-report.json" if input_kind == "page-spec" else tmp_path / "page-spec.json"
    image_file = "reference.png"
    if input_kind == "page-spec":
        reference = output / "reference.png"
        Image.new("RGB", (160, 90), "red").save(reference)
    spec.write_text(json.dumps({"slides": [
        {"id": "s01", "image_status": "approved", "image_file": image_file}]}), encoding="utf-8")
    original = {p: p.read_bytes() for p in (deck, spec, reference)}
    monkeypatch.setattr(sys, "argv", ["render_deck.py", str(deck), str(output), "--overwrite", "--page-spec", str(spec)])
    with pytest.raises(SystemExit) as error:
        render_deck.main()
    assert error.value.code == 2
    assert all(p.read_bytes() == value for p, value in original.items())


@pytest.mark.parametrize("failure", ["renderer", "incomplete", "reference-changed", "publication"])
def test_failed_overwrite_preserves_complete_previous_review(tmp_path, monkeypatch, failure):
    deck = tmp_path / "deck.pptx"
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(deck)
    output = tmp_path / "review"
    output.mkdir()
    for name in ("001.png", "002.png", "1000.png", "001.layout.json", "review.png", "render-report.json", "user-notes.txt"):
        (output / name).write_bytes(f"previous {name}".encode())
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    reference = tmp_path / "source.png"
    Image.new("RGB", (160, 90), "red").save(reference)
    spec = tmp_path / "page-spec.json"
    spec.write_text(json.dumps({"slides": [
        {"id": "s01", "image_status": "approved", "image_file": reference.name}]}), encoding="utf-8")

    def renderer(_deck, target, width, height):
        assert target != output
        if failure == "incomplete":
            return
        Image.new("RGB", (width, height), "blue").save(target / "001.png")
        if failure == "renderer":
            raise RuntimeError("Synthetic renderer failure after writing one page")
        if failure == "reference-changed":
            Image.new("RGB", (160, 90), "green").save(reference)

    replace = render_deck.os.replace
    failed = False

    def replace_once(source, destination):
        nonlocal failed
        if failure == "publication" and Path(destination) == output / "review.png" and not failed:
            failed = True
            raise OSError("Synthetic failure publishing review sheet")
        return replace(source, destination)

    monkeypatch.setattr(render_deck, "render_powerpoint", renderer)
    monkeypatch.setattr(render_deck.os, "replace", replace_once)
    monkeypatch.setattr(sys, "argv", ["render_deck.py", str(deck), str(output), "--overwrite",
                                      "--page-spec", str(spec), "--backend", "powerpoint"])
    with pytest.raises((SystemExit, ValueError, OSError)):
        render_deck.main()
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert not list(tmp_path.glob(".review-*-*"))


def test_font_preflight_reports_missing_east_asian_family_per_slide(monkeypatch):
    import render_environment
    from build_editable_ppt import east_asian_font
    from pptx.util import Inches

    deck = Presentation()
    for family in ("宋体", "noto serif cjk sc"):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        frame = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text_frame
        run = frame.paragraphs[0].add_run()
        run.text = "中文"
        east_asian_font(run.font, family)
        run.font.name = "+mn-lt"  # An inherited Latin font does not mask the explicit East Asian request.
    monkeypatch.setattr(render_environment, "installed_font_families", lambda: {"noto serif cjk sc"})
    result = render_environment.font_preflight(deck, "libreoffice")
    assert result["status"] == "warning"
    assert result["pages"] == [{"slide": 1, "missing_families": ["宋体"]}]
    assert render_environment.font_preflight(deck, "powerpoint")["status"] == "unverified"
