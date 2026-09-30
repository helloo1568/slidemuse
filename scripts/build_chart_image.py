#!/usr/bin/env python3
"""Draw a precise single-series horizontal bar reference, optionally replace its approved page region."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_chart_geometry import bar_data, number
from overlay_text import FONT_CANDIDATES, load_font, parse_color
from PIL import Image, ImageDraw, ImageOps
from render_deck import sha256
from validate_page_spec import _relative_path, load_page_spec


def render(spec_path, layout_path, output, replace_region=False):
    spec_path, output = spec_path.resolve(), output.resolve()
    spec, _ = load_page_spec(spec_path)
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    slide = next((s for s in spec["slides"] if s["id"] == layout["slide_id"]), None)
    element = next((e for e in slide["elements"] if e["id"] == layout["element_id"]), None) if slide else None
    if not element or element["kind"] != "chart":
        raise ValueError("Layout must select an existing chart element")
    data, categories, values = bar_data(element)
    source = _relative_path(spec_path.parent, slide["image_file"])
    if output in {_relative_path(spec_path.parent, s["image_file"]) for s in spec["slides"]}:
        raise ValueError("Write a new image; do not overwrite the source page")
    if data["chart_type"] != "bar":
        raise ValueError("Raster fallback currently supports horizontal bars only")
    if output.suffix.lower() != ".png":
        raise ValueError("Use PNG output to preserve pixels outside the replaced region")
    region = layout["region"]
    if len(region) != 4 or any(isinstance(x, bool) or not isinstance(x, int) for x in region):
        raise ValueError("Region must be integer [x,y,width,height]")
    x, y, width, height = region
    if min(x, y) < 0 or min(width, height) <= 0:
        raise ValueError("Invalid region bounds")
    px, py, pw, ph = (number(v) for v in layout["plot"])
    if min(px, py) < 0 or min(pw, ph) <= 0 or px + pw >= width or py + ph >= height:
        raise ValueError("Plot must fit inside region with space for labels/ticks")
    lo, hi = number(layout["axis_min"]), number(layout["axis_max"])
    if lo >= hi or lo > min(0, *values) or hi < max(0, *values):
        raise ValueError("Axis must include zero and every source value")
    colors = {key: parse_color(layout.get(key, default)) for key, default in (
        ("background", "#FFFFFF"), ("positive_color", "#9582DE"), ("negative_color", "#B8A8E2"),
        ("text_color", "#242638"), ("grid_color", "#DED9EF"))}
    font_size = layout.get("font_size", 24)
    if isinstance(font_size, bool) or not isinstance(font_size, int) or font_size <= 0:
        raise ValueError("Font size must be a positive integer")
    font = load_font(font_size, [layout.get("font"), *FONT_CANDIDATES])
    image = Image.new("RGB", (width, height), colors["background"])
    draw = ImageDraw.Draw(image)

    def text(position, value, anchor):
        bounds = draw.textbbox(position, value, font=font, anchor=anchor)
        if bounds[0] < 0 or bounds[1] < 0 or bounds[2] > width or bounds[3] > height:
            raise ValueError(f"Label overflows region: {value}; enlarge region or adjust plot/font")
        draw.text(position, value, font=font, fill=colors["text_color"], anchor=anchor)

    scale = pw / (hi - lo)
    zero = px - lo * scale
    for tick in layout.get("ticks", [lo, 0, hi]):
        tick = number(tick)
        if not lo <= tick <= hi:
            raise ValueError("Tick outside axis")
        tx = px + (tick - lo) * scale
        draw.line((tx, py, tx, py + ph), fill=colors["grid_color"], width=1)
        text((tx, py + ph + 8), f"{tick:g}", "mt")
    draw.line((zero, py, zero, py + ph), fill=colors["text_color"], width=1)
    step = ph / len(values)
    thickness = number(layout.get("bar_thickness", step * 0.55))
    if not 0 < thickness < step:
        raise ValueError("Bar thickness must be smaller than row spacing")
    decimals = layout.get("decimals", 2)
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 8:
        raise ValueError("Decimals must be an integer between 0 and 8")
    geometry = []
    for index, (category, value) in enumerate(zip(categories, values)):
        cy = py + step * (index + 0.5)
        end = zero + value * scale
        if value:
            draw.rectangle((min(zero, end), cy - thickness / 2, max(zero, end), cy + thickness / 2),
                           fill=colors["positive_color" if value > 0 else "negative_color"])
        label = format(value, ("+" if layout.get("signed", False) else "") + f".{decimals}f") + layout.get("suffix", "")
        text((end + 8, cy) if value >= 0 else (end - 8, cy), label, "lm" if value >= 0 else "rm")
        if layout.get("show_categories", True):
            text((px - 12, cy), category, "rm")
        geometry.append({"category": category, "start": x + zero, "end": x + end})
    source_hash = None
    if replace_region:
        if layout.get("source_sha256") != sha256(source):
            raise ValueError("Replacement source hash is missing or stale")
        source_hash = sha256(source)
        with Image.open(source) as opened:
            page = ImageOps.exif_transpose(opened).convert("RGBA")
        if x + width > page.width or y + height > page.height:
            raise ValueError("Replacement region outside source page")
        page.paste(image, (x, y))
        image = page
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return {"output": str(output), "output_sha256": sha256(output), "page_spec_sha256": sha256(spec_path),
            "layout_sha256": sha256(layout_path), "source_sha256": source_hash,
            "region": region, "construction_geometry": geometry,
            "note": "Construction coordinates are not independent visual observations. Inspect the output before approval."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page_spec", type=Path)
    parser.add_argument("layout", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--replace-region", action="store_true", help="Modify only the specified rectangle; respect host image-edit permissions")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = render(args.page_spec, args.layout, args.output, args.replace_region)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"build_chart_image: {error}\n")


if __name__ == "__main__":
    main()
