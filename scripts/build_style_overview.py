#!/usr/bin/env python3
"""Label a style card, compare four style cards, or arrange a 3x2 slide preview."""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
from pathlib import Path

from json_io import read_json
from overlay_text import FONT_CANDIDATES, load_font
from PIL import Image, ImageDraw, ImageOps, PngImagePlugin

COLUMNS, ROWS = 3, 2
SLOTS = COLUMNS * ROWS


def check_output(source: Path, output: Path, overwrite: bool) -> None:
    if output.suffix.lower() != ".png":
        raise ValueError("Output must be a PNG file")
    if output == source:
        raise ValueError("Output must not overwrite the input")
    if output.exists() and not overwrite:
        raise ValueError("Output exists; choose a new filename or use --overwrite")


def label_overview(source: Path, output: Path, option: int, name: str, *,
                   font_path: str | None = None, overwrite: bool = False, width: int = 1600) -> dict:
    """Put a stable option label outside an intact, proportionally scaled preview."""
    source, output = source.resolve(), output.resolve()
    check_output(source, output, overwrite)
    if type(option) is not int or not 1 <= option <= 4 or not name.strip() or len(name.splitlines()) != 1:
        raise ValueError("Provide an option from 1 to 4 and a one-line name")
    label = f"{option:02d} · {name.strip()}"
    if type(width) is not int or not 960 <= width <= 4096 or width % 16:
        raise ValueError("Label canvas width must be a multiple of 16 between 960 and 4096")
    height = width * 9 // 16
    scale = width / 1600
    margin, header = round(32 * scale), round(65 * scale)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        source_pixels = list(image.size)
        preview = ImageOps.contain(image, (min(image.width, width - 2 * margin),
                                            min(image.height, height - header - margin)), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (width, height), "#EBEDF0")
    draw = ImageDraw.Draw(canvas)
    font = load_font(round(30 * scale), [font_path, *FONT_CANDIDATES])
    if draw.textlength(label, font=font) > width - 2 * margin:
        raise ValueError("Overview label is too wide; shorten the option name")
    draw.text((margin, round(16 * scale)), label, font=font, fill="#263444")
    x = (width - preview.width) // 2
    y = header + (height - header - margin - preview.height) // 2
    canvas.paste(preview, (x, y), preview)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("slidemuse_style_option", str(option))
    metadata.add_text("slidemuse_style_name", name.strip())
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, pnginfo=metadata)
    return {"output": str(output), "option": option, "label": label,
            "pixels": [width, height], "source_pixels": source_pixels,
            "preview_box": [x, y, preview.width, preview.height], "image_generation_calls": 0}


def compare_styles(sources: list[Path], output: Path, overwrite: bool = False, *, html_preview: bool = False) -> dict:
    if len(sources) != 4:
        raise ValueError("Provide four labeled style cards, one for each option 01–04")
    output = output.resolve()
    preview = output.with_suffix(".html")
    if html_preview and preview.exists() and not overwrite:
        raise ValueError("HTML preview exists; choose a new filename or use --overwrite")
    cards = {}
    for source in sources:
        source = source.resolve()
        check_output(source, output, overwrite)
        if html_preview and preview.resolve() == source:
            raise ValueError("HTML preview must not overwrite a source image")
        with Image.open(source) as opened:
            option = opened.info.get("slidemuse_style_option")
            name = opened.info.get("slidemuse_style_name", "").strip()
            if option not in {"1", "2", "3", "4"} or option in cards or not name:
                raise ValueError(f"Expected one labeled style card per option 01–04: {source.name}")
            card = ImageOps.exif_transpose(opened).convert("RGBA")
        card.thumbnail((960, 540), Image.Resampling.LANCZOS)
        cards[option] = (source, name, card)

    tile_w = max(card.width for _, _, card in cards.values())
    tile_h = max(card.height for _, _, card in cards.values())
    gap = 16
    canvas = Image.new("RGB", (2 * tile_w + gap, 2 * tile_h + gap), "#BBC5D0")
    options = []
    for index, (option, (source, name, card)) in enumerate(sorted(cards.items())):
        row, column = divmod(index, 2)
        x = column * (tile_w + gap)
        y = row * (tile_h + gap)
        canvas.paste("#EBEDF0", (x, y, x + tile_w, y + tile_h))
        canvas.paste(card, (x + (tile_w - card.width) // 2, y + (tile_h - card.height) // 2), card)
        options.append({"option": int(option), "name": name, "source": str(source)})

    output.parent.mkdir(parents=True, exist_ok=True)
    png = io.BytesIO()
    canvas.save(png, format="PNG")
    output.write_bytes(png.getvalue())
    result = {"output": str(output), "pixels": list(canvas.size), "options": options, "image_generation_calls": 0}
    if html_preview:
        labels = html.escape(" / ".join(f"{item['option']:02d} · {item['name']}" for item in options), quote=True)
        encoded = base64.b64encode(png.getbuffer()).decode("ascii")
        preview.write_text(
            '<!doctype html>\n<html><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>SlideMuse</title>'
            '<style>body{margin:0;background:#ebedf0}img{display:block;margin:auto;max-width:100%;'
            'max-height:100vh;width:auto;height:auto}</style></head><body>'
            f'<img alt="{labels}" src="data:image/png;base64,{encoded}"></body></html>\n', encoding="utf-8"
        )
        result["html_preview"] = str(preview)
    return result


def build_overview(spec_path: Path, output: Path, overwrite: bool = False) -> dict:
    spec_path, output = spec_path.resolve(), output.resolve()
    check_output(spec_path, output, overwrite)
    spec = read_json(spec_path)
    if not isinstance(spec, dict):
        raise TypeError("Overview specification must be an object")
    slides = spec.get("slides")
    if not isinstance(slides, list) or not 1 <= len(slides) <= SLOTS:
        raise ValueError("Provide 1-6 existing slide images or explicit crops")
    width, height = spec.get("width", 1600), spec.get("height", 900)
    if any(type(v) is not int or not 480 <= v <= 4096 for v in (width, height)) or width <= height:
        raise ValueError("Canvas must be landscape, with integer dimensions between 480 and 4096")
    if abs(width / height - 16 / 9) > 1e-6:
        raise ValueError("Canvas must use the standard 16:9 slide size")
    aspect = spec.get("slide_aspect_ratio", [16, 9])
    if (not isinstance(aspect, list) or len(aspect) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in aspect)
            or abs(aspect[0] / aspect[1] - 16 / 9) > 1e-6):
        raise ValueError("Thumbnails must use the standard 16:9 slide size")
    ratio = aspect[0] / aspect[1]
    images = []
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
        images.append(image)
    scale = min(width / 1600, height / 900)
    margin, gap, header, label_h = [max(1, round(v * scale)) for v in (48, 36, 96, 30)]
    cell_w = (width - 2 * margin - (COLUMNS - 1) * gap) // COLUMNS
    cell_h = (height - header - margin - (ROWS - 1) * gap) // ROWS - label_h
    if cell_w <= 0 or cell_h <= 0:
        raise ValueError("Canvas is too small for a 3x2 thumbnail sheet")
    tile_w = min(cell_w, int(cell_h * ratio))
    tile_h = max(1, round(tile_w / ratio))
    left = (width - COLUMNS * tile_w - (COLUMNS - 1) * gap) // 2
    top = header + max(0, (height - header - margin - ROWS * (tile_h + label_h) - (ROWS - 1) * gap) // 2)
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
        row, column = divmod(index, COLUMNS)
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
                      "source": slide["file"], "source_pixels": list(image.size),
                      "source_crop": slide.get("box"), "native_aspect": native,
                      "occupancy": fitted.width * fitted.height / (tile_w * tile_h)})
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return {"output": str(output), "pixels": [width, height], "tiles": tiles,
            "slide_aspect_ratio": aspect, "native_composition": all(t["native_aspect"] for t in tiles),
            "image_generation_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="+", type=Path, help="Layout JSON, one image to label, or four labeled cards")
    parser.add_argument("output", type=Path)
    parser.add_argument("--compare", action="store_true", help="Arrange four labeled style cards by option in a 2x2 PNG")
    parser.add_argument("--html", action="store_true", help="With --compare, also make a self-contained HTML preview")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--option", type=int, choices=range(1, 5), help="Stable number of an existing style preview")
    parser.add_argument("--name", help="Short name printed next to --option")
    parser.add_argument("--font", help="Font file for the option label; layout JSON uses its own font field")
    parser.add_argument("--width", type=int, help="Labeled output canvas width; 3840 for 4K (no source upscaling)")
    args = parser.parse_intermixed_args()
    if args.compare:
        if any(value is not None for value in (args.option, args.name, args.font, args.width)):
            parser.error("--compare uses existing labels; omit labeling options")
    elif args.html:
        parser.error("--html requires --compare")
    elif len(args.source) != 1:
        parser.error("provide one source unless using --compare")
    elif (args.option is None) != (args.name is None) or ((args.font or args.width is not None) and args.option is None):
        parser.error("labeling requires both --option and --name")
    try:
        if args.compare:
            result = compare_styles(args.source, args.output, args.overwrite, html_preview=args.html)
        elif args.option is None:
            result = build_overview(args.source[0], args.output, args.overwrite)
        else:
            result = label_overview(args.source[0], args.output, args.option, args.name,
                                    font_path=args.font, overwrite=args.overwrite,
                                    width=args.width if args.width is not None else 1600)
    except (TypeError, ValueError, OSError) as error:
        parser.exit(2, f"build_style_overview: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
