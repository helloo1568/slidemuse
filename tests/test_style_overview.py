import json

import pytest
from build_style_overview import build_overview, label_overview
from PIL import Image, ImageChops


@pytest.fixture
def overview_spec(tmp_path):
    # A misplaced vertical strip with real gutters: crops must be explicit.
    strip = Image.new("RGB", (160, 300), "black")
    colors = ["red", "green", "blue"]
    slides = []
    for index, color in enumerate(colors):
        strip.paste(Image.new("RGB", (160, 90), color), (0, index * 100))
        slides.append({"file": "strip.png", "box": [0, index * 100, 160, 90]})
    strip.save(tmp_path / "strip.png")
    path = tmp_path / "overview.json"
    path.write_text(json.dumps({"title": "Option 1", "slides": slides}), encoding="utf-8")
    return path


def test_three_crops_form_grid_without_changing_pixels_or_sources(overview_spec):
    original = (overview_spec.parent / "strip.png").read_bytes()
    result = build_overview(overview_spec, overview_spec.with_suffix(".png"))
    assert result["image_generation_calls"] == 0
    assert len(result["tiles"]) == 3
    first, second, third = [item["box"] for item in result["tiles"]]
    assert first[1] == second[1] == third[1]
    assert first[0] < second[0] < third[0]
    with Image.open(result["output"]) as image:
        assert image.size == (1600, 900)
        for (x, y, w, h), color in zip([first, second, third], [(255, 0, 0), (0, 128, 0), (0, 0, 255)]):
            assert image.getpixel((x + w // 2, y + h // 2)) == color
        assert image.getpixel((first[0] + first[2] // 2, first[1] + first[3] + 200)) == (235, 237, 240)
    assert (overview_spec.parent / "strip.png").read_bytes() == original


@pytest.mark.parametrize("mutation", ["outside", "overwrite_source", "existing", "traversal"])
def test_invalid_crop_or_overwrite_rejected(overview_spec, mutation):
    spec = json.loads(overview_spec.read_text())
    output = overview_spec.with_suffix(".png")
    if mutation == "outside":
        spec["slides"][0]["box"] = [0, 0, 999, 90]
    elif mutation == "traversal":
        spec["slides"][0]["file"] = "../strip.png"
    elif mutation == "overwrite_source":
        output = overview_spec.parent / "strip.png"
    elif mutation == "existing":
        output.write_bytes(b"previous")
    overview_spec.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError):
        build_overview(overview_spec, output, overwrite=mutation == "overwrite_source")
    if mutation == "existing":
        assert output.read_bytes() == b"previous"


@pytest.mark.parametrize("count", [1, 2, 5, 6])
def test_layout_count_and_bounds(overview_spec, count):
    spec = json.loads(overview_spec.read_text())
    spec["slides"] = [spec["slides"][0]] * count
    overview_spec.write_text(json.dumps(spec), encoding="utf-8")
    result = build_overview(overview_spec, overview_spec.with_suffix(".png"))
    assert len(result["tiles"]) == count
    for tile in result["tiles"]:
        x, y, w, h = tile["box"]
        assert 0 <= x < x + w <= 1600
        assert 0 <= y < y + h < 900
        assert w / h == pytest.approx(16 / 9, abs=0.01)


@pytest.mark.parametrize("count,columns,rows", [
    (1, 1, 1), (2, 2, 1), (3, 3, 1), (4, 3, 2), (5, 3, 2), (6, 3, 2),
])
def test_sixteen_by_nine_pages_keep_sixteen_by_nine_cells(tmp_path, count, columns, rows):
    slides = []
    for index in range(count):
        name = f"p{index}.png"
        Image.new("RGB", (320, 180), "white").save(tmp_path / name)
        slides.append({"file": name, "slide_id": f"s{index + 1:02d}"})
    spec = tmp_path / "overview.json"
    spec.write_text(json.dumps({"title": "Option", "slides": slides, "slide_aspect_ratio": [16, 9],
                                "require_native_aspect": True}), encoding="utf-8")
    result = build_overview(spec, tmp_path / "out.png")
    boxes = [tile["box"] for tile in result["tiles"]]
    assert len({y for _, y, _, _ in boxes}) == rows
    assert len({x for x, _, _, _ in boxes}) == min(columns, count)
    for _, _, w, h in boxes:
        assert w / h == pytest.approx(16 / 9, abs=0.01)
    top, bottom = min(y for _, y, _, _ in boxes), max(y + h for _, y, _, h in boxes)
    if rows > 1:
        assert bottom - top > 900 * .6, "grid must use the canvas height instead of a blank band"


def test_tall_content_is_disclosed_and_strict_mode_rejects_padding(overview_spec):
    spec = json.loads(overview_spec.read_text())
    spec["slides"][0]["box"] = [0, 0, 160, 140]
    overview_spec.write_text(json.dumps(spec))
    result = build_overview(overview_spec, overview_spec.with_suffix(".png"))
    assert not result["native_composition"]
    assert result["tiles"][0]["occupancy"] < .7
    spec["require_native_aspect"] = True
    overview_spec.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="padding"):
        build_overview(overview_spec, overview_spec.with_name("strict.png"))


def test_labels_bind_stable_numbers_without_cropping_the_overview(tmp_path):
    source = tmp_path / "raw.png"
    image = Image.new("RGB", (1600, 900), "blue")
    image.paste("orange", (0, 0, 400, 300))
    image.save(source)
    original = source.read_bytes()
    second = label_overview(source, tmp_path / "02.png", 2, "Architecture")
    first = label_overview(source, tmp_path / "01.png", 1, "Engineering")
    assert second["label"] == "02 · Architecture"
    assert first["label"] == "01 · Engineering"
    x, y, width, height = second["preview_box"]
    with Image.open(second["output"]) as labeled, Image.open(first["output"]) as other:
        assert labeled.size == (1600, 900)
        assert width / height == pytest.approx(16 / 9, abs=0.01)
        assert ImageChops.difference(labeled.crop((x, y, x + width, y + height)),
                                     image.resize((width, height), Image.Resampling.LANCZOS)).getbbox() is None
        assert ImageChops.difference(labeled.crop((0, 0, 1600, y)), other.crop((0, 0, 1600, y))).getbbox()
    assert source.read_bytes() == original
    with pytest.raises(ValueError, match="not overwrite"):
        label_overview(source, source, 2, "Architecture", overwrite=True)


def test_label_option_supports_explicit_4k_canvas_and_discloses_source_resolution(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (2000, 1125), "navy").save(source)
    result = label_overview(source, tmp_path / "labeled.png", 1, "Editorial", width=3840)
    assert result["source_pixels"] == [2000, 1125]
    assert result["pixels"] == [3840, 2160]
    assert result["preview_box"][2:] == [2000, 1125]  # Never manufacture source detail.
    with Image.open(result["output"]) as image:
        assert image.size == (3840, 2160)
        assert image.info["slidemuse_style_option"] == "1"
