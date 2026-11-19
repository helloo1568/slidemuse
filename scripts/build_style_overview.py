#!/usr/bin/env python3
"""Locally arrange existing slide images or explicit crops into a thumbnail grid."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from json_io import read_json
from overlay_text import FONT_CANDIDATES, load_font
from PIL import Image, ImageDraw, ImageOps


def choose_grid(count: int, width: int, height: int, ratio: float) -> dict:
    """Pick the grid that keeps thumbnails largest and closest to the canvas ratio.

    A non-square grid on a canvas whose ratio equals the slide ratio forces the
    cells to differ from the slide ratio (4x2 cells on a 16:9 canvas are 0.889),
    which is what makes generated overviews squeeze slides into square-ish
    frames. Scoring by tile area keeps square grids for 16:9 slides while still
    allowing 3x2 for six pages, where the extra area is worth the slack.
    """
    scale = min(width / 1600, height / 900)
    margin, gap, header, label_h = [max(1, round(v * scale)) for v in (48, 36, 96, 30)]
    usable_w, usable_h = width - 2 * margin, height - header - margin
    region_ratio = usable_w / usable_h if usable_h > 0 else ratio
    best = None
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        cell_w = (width - 2 * margin - (columns - 1) * gap) // columns
        cell_h = (height - header - margin - (rows - 1) * gap) // rows - label_h
        if cell_w <= 0 or cell_h <= 0:
            continue
        tile_w = min(cell_w, int(cell_h * ratio))
        tile_h = max(1, round(tile_w / ratio))
        area = tile_w * tile_h * count
        grid_ratio = (columns * tile_w) / (rows * tile_h)
        slack = abs(math.log(grid_ratio / region_ratio)) if region_ratio > 0 else 0
        candidate = (area, -slack)
        if best is None or candidate > best[0]:
            best = (candidate, columns, rows, tile_w, tile_h)
    if best is None:
        raise ValueError("Canvas is too small for this many thumbnails")
    _, columns, rows, tile_w, tile_h = best
    return {"columns": columns, "rows": rows, "tile_w": tile_w, "tile_h": tile_h,
            "margin": margin, "gap": gap, "header": header, "label_h": label_h}


def build_overview(spec_path: Path, output: Path, overwrite: bool = False) -> dict:
    spec_path, output = spec_path.resolve(), output.resolve()
    spec = read_json(spec_path)
    if not isinstance(spec, dict):
        raise TypeError("Overview specification must be an object")
    slides = spec.get("slides")
    if not isinstance(slides, list) or not 1 <= len(slides) <= 8:
        raise ValueError("Provide 1-8 existing slide images or explicit crops")
    width, height = spec.get("width", 1600), spec.get("height", 900)
    if any(type(v) is not int or not 480 <= v <= 4096 for v in (width, height)) or width <= height:
        raise ValueError("Canvas must be landscape, with integer dimensions between 480 and 4096")
    aspect = spec.get("slide_aspect_ratio", [16, 9])
    if (not isinstance(aspect, list) or len(aspect) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in aspect)):
        raise ValueError("slide_aspect_ratio must contain two positive finite numbers")
    ratio = aspect[0] / aspect[1]
    if not 0.2 <= ratio <= 5:
        raise ValueError("slide_aspect_ratio must be between 1:5 and 5:1")
    if output.suffix.lower() != ".png":
        raise ValueError("Output must be a PNG file")
    if output == spec_path:
        raise ValueError("Output must not overwrite the specification")
    if output.exists() and not overwrite:
        raise ValueError("Output exists; choose a new filename or use --overwrite")
    images = []
    source_sizes = []
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get("file"), str):
            raise TypeError("Each slide needs a file path")
        relative = Path(slide["file"])
        path = (spec_path.parent / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(spec_path.parent):
            raise ValueError("Images must stay inside the specification directory")
        if path == output:
            raise ValueError("Output must not overwrite a source image")
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
        if "box" in slide:
            box = slide["box"]
            if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
                raise ValueError("Crop box must be four integers: x, y, width, height")
            x, y, w, h = box
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image.width or y + h > image.height:
                raise ValueError("Crop box is outside the source image")
            image = image.crop((x, y, x + w, y + h))
        if spec.get("require_native_aspect", False) and abs(image.width - image.height * ratio) > max(1, ratio) + 1e-6:
            raise ValueError("Thumbnail source aspect differs from slide_aspect_ratio; padding cannot repair composition")
        source_sizes.append(list(image.size))
        images.append(image)
    grid = choose_grid(len(images), width, height, ratio)
    columns, rows = grid["columns"], grid["rows"]
    margin, gap, header, label_h = grid["margin"], grid["gap"], grid["header"], grid["label_h"]
    tile_w, tile_h = grid["tile_w"], grid["tile_h"]
    scale = min(width / 1600, height / 900)
    left = (width - columns * tile_w - (columns - 1) * gap) // 2
    top = header + max(0, (height - header - margin - rows * (tile_h + label_h) - (rows - 1) * gap) // 2)
    canvas = Image.new("RGB", (width, height), "#EBEDF0")
    draw = ImageDraw.Draw(canvas)
    fonts = [spec.get("font"), *FONT_CANDIDATES]
    title_font = load_font(max(12, round(32 * scale)), fonts)
    label_font = load_font(max(10, round(22 * scale)), fonts)
    title = str(spec.get("title", ""))
    if draw.textbbox((0, 0), title, font=title_font)[2] > width - 2 * margin:
        raise ValueError("Overview title is too wide; shorten it")
    draw.text((margin, round(24 * scale)), title, font=title_font, fill="#263444")
    tiles = []
    for index, (slide, image) in enumerate(zip(slides, images)):
        row, column = divmod(index, columns)
        x = left + column * (tile_w + gap)
        y = top + row * (tile_h + label_h + gap)
        draw.rectangle((x, y, x + tile_w - 1, y + tile_h - 1), fill="white")
        fitted = ImageOps.contain(image, (tile_w, tile_h), Image.Resampling.LANCZOS)
        px, py = x + (tile_w - fitted.width) // 2, y + (tile_h - fitted.height) // 2
        canvas.paste(fitted, (px, py), fitted)
        draw.rectangle((x, y, x + tile_w - 1, y + tile_h - 1), outline="#BCC5CF")
        label = str(slide.get("label", f"{index + 1:02d}"))
        if draw.textbbox((0, 0), label, font=label_font)[2] > tile_w:
            raise ValueError("Thumbnail label is too wide")
        draw.text((x, y + tile_h + max(1, round(3 * scale))), label, font=label_font, fill="#364658")
        native = abs(image.width - image.height * ratio) <= max(1, ratio) + 1e-6
        tiles.append({"label": label, "slide_id": slide.get("slide_id", label),
                      "box": [x, y, tile_w, tile_h], "content_box": [px, py, fitted.width, fitted.height],
                      "source": slide["file"], "source_pixels": source_sizes[index],
                      "source_crop": slide.get("box"), "native_aspect": native,
                      "occupancy": fitted.width * fitted.height / (tile_w * tile_h)})
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return {"output": str(output), "pixels": [width, height], "tiles": tiles,
            "source_root": os.path.relpath(spec_path.parent, output.parent),
            "image_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "slide_aspect_ratio": aspect, "native_composition": all(t["native_aspect"] for t in tiles),
            "image_generation_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--layout", type=Path, help="Write hash-bound thumbnail geometry beside the overview")
    args = parser.parse_args()
    try:
        if args.layout and (args.layout.resolve() in (args.spec.resolve(), args.output.resolve()) or args.layout.exists() and not args.overwrite):
            raise ValueError("Layout path must be a new independent file (or use --overwrite)")
        result = build_overview(args.spec, args.output, args.overwrite)
        if args.layout:
            args.layout.parent.mkdir(parents=True, exist_ok=True)
            args.layout.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except (TypeError, ValueError, OSError) as error:
        parser.exit(2, f"build_style_overview: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
