import json
import sys

import pytest
import render_deck
from PIL import Image
from pptx import Presentation


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
