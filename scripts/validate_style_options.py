#!/usr/bin/env python3
"""Validate the four current landscape slide-sorter candidates before selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from json_io import read_json
from PIL import Image, ImageChops, ImageOps


def validate_layout(layout, overview, root, pages, aspect):
    """Validate measured geometry and actual source pixels, not just outer canvas."""
    if (not isinstance(aspect, list) or len(aspect) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in aspect)):
        raise ValueError("slide_aspect_ratio needs two positive finite numbers")
    if layout.get("image_sha256") != hashlib.sha256(overview.read_bytes()).hexdigest():
        raise ValueError("Stale overview layout hash")
    tiles = layout.get("tiles", [])
    if [tile.get("slide_id") for tile in tiles] != pages:
        raise ValueError("Layout must cover representative pages in order")
    ratio = aspect[0] / aspect[1]
    source_root = (overview.parent / layout.get("source_root", ".")).resolve()
    if not source_root.is_relative_to(root):
        raise ValueError("Layout source root escapes options directory")
    boxes = []
    with Image.open(overview) as opened:
        page = ImageOps.exif_transpose(opened).convert("RGB")
    for tile in tiles:
        rectangles = []
        for name in ("box", "content_box"):
            box = tile.get(name)
            if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
                raise ValueError("Thumbnail geometry needs integer boxes")
            x, y, w, h = box
            if min(x, y) < 0 or min(w, h) < 3 or x + w > page.width or y + h > page.height:
                raise ValueError("Thumbnail outside overview")
            rectangles.append((x, y, w, h))
        x, y, w, h = rectangles[0]
        px, py, pw, ph = rectangles[1]
        if px < x or py < y or px + pw > x + w or py + ph > y + h:
            raise ValueError("Thumbnail content outside frame")
        if abs(w - h * ratio) > max(1, ratio) + 1e-6 or pw * ph / (w * h) < .98:
            raise ValueError("Thumbnail padding cannot stand in for native landscape composition")
        if any(x < r and x + w > l and y < b and y + h > t for l, t, r, b in boxes):
            raise ValueError("Thumbnail frames overlap")
        boxes.append((x, y, x + w, y + h))
        source = (source_root / tile["source"]).resolve()
        if not source.is_relative_to(root) or source == overview:
            raise ValueError("Unsafe thumbnail source")
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
        crop = tile.get("source_crop")
        if crop is not None:
            if (not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop)
                    or min(crop[:2]) < 0 or min(crop[2:]) <= 0
                    or crop[0] + crop[2] > image.width or crop[1] + crop[3] > image.height):
                raise ValueError("Invalid source crop")
            a, b, c, d = crop
            image = image.crop((a, b, a + c, b + d))
        if abs(image.width - image.height * ratio) > max(1, ratio) + 1e-6:
            raise ValueError("Thumbnail source has wrong native aspect")
        fitted = ImageOps.contain(image, (w, h), Image.Resampling.LANCZOS)
        if fitted.size != (pw, ph) or (px, py) != (x + (w - pw) // 2, y + (h - ph) // 2):
            raise ValueError("Content geometry differs from source fit")
        patch = Image.new("RGB", fitted.size, "white")
        patch.paste(fitted, (0, 0), fitted)
        # The overview draws a one-pixel frame after placing the source.
        interior = (1, 1, pw - 1, ph - 1)
        if ImageChops.difference(page.crop((px, py, px + pw, py + ph)).crop(interior), patch.crop(interior)).getbbox():
            raise ValueError("Thumbnail pixels differ from declared crop")
    return "verified_native_geometry; composition and legibility still require visual review"


def validate_style_options(spec: dict, base: Path, require_layout: bool = False) -> dict:
    if not isinstance(spec, dict) or spec.get("version") != "1.0":
        raise ValueError("Style options must be a version 1.0 object")
    total = spec.get("total_pages")
    pages = spec.get("representative_pages")
    if type(total) is not int or total < 1:
        raise ValueError("total_pages must be a positive integer")
    if (
        not isinstance(pages, list)
        or not pages
        or any(not isinstance(page, str) or not page.strip() for page in pages)
        or len(set(pages)) != len(pages)
    ):
        raise ValueError("representative_pages must contain unique, nonempty slide IDs")
    if (total <= 8 and len(pages) != total) or (total > 8 and not 6 <= len(pages) <= 8):
        raise ValueError("Show every page up to 8 pages; otherwise use 6-8 representative pages")
    aspect = spec.get("overview_aspect_ratio", [16, 9])
    if (
        not isinstance(aspect, list)
        or len(aspect) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in aspect)
        or aspect[0] <= aspect[1]
    ):
        raise ValueError("overview_aspect_ratio must describe a landscape canvas")
    ratio = aspect[0] / aspect[1]
    options = spec.get("options")
    if not isinstance(options, list) or len(options) != 4:
        raise ValueError("Exactly four current options are required; exclude drafts and superseded revisions")
    paths, hashes, results = set(), set(), []
    root = base.resolve()
    for number, option in enumerate(options, 1):
        if not isinstance(option, dict) or type(option.get("option")) is not int or option["option"] != number:
            raise ValueError("Options must be numbered 1, 2, 3, 4 in order, without duplicates")
        if option.get("slide_ids") != pages:
            raise ValueError(f"Option {number}: slide IDs/order differ from the representative pages")
        value = option.get("file")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Option {number}: missing image file")
        path = Path(value)
        resolved = (root / path).resolve()
        if path.is_absolute() or not resolved.is_relative_to(root):
            raise ValueError(f"Option {number}: image must stay inside the options directory")
        if resolved in paths:
            raise ValueError(f"Option {number}: duplicate image path")
        paths.add(resolved)
        if not resolved.is_file():
            raise ValueError(f"Option {number}: missing image {value}")
        with Image.open(resolved) as image:
            if image.format not in ("PNG", "JPEG"):
                raise ValueError(f"Option {number}: use a PNG or JPEG overview")
            image.verify()
        with Image.open(resolved) as image:
            image = ImageOps.exif_transpose(image).convert("RGBA")
            width, height = image.size
            if width <= height or abs(width - height * ratio) > max(1.0, ratio) + 1e-6:
                raise ValueError(f"Option {number}: expected a landscape overview, not a vertical slide strip or wrong canvas ratio")
            digest = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
        if digest in hashes:
            raise ValueError(f"Option {number}: duplicate image content is not a distinct option")
        hashes.add(digest)
        geometry = "not_checked: legacy outer-canvas validation only"
        layout_name = option.get("layout")
        if require_layout and not layout_name:
            raise ValueError(f"Option {number}: a hash-bound thumbnail layout is required")
        if layout_name:
            layout_path = (root / layout_name).resolve()
            if Path(layout_name).is_absolute() or not layout_path.is_relative_to(root):
                raise ValueError("Layout must stay inside options directory")
            geometry = validate_layout(read_json(layout_path), resolved, root, pages, spec.get("slide_aspect_ratio", [16, 9]))
        results.append({"option": number, "file": value, "pixels": [width, height], "thumbnail_geometry": geometry})
    return {
        "options": results,
        "representative_pages": pages,
        "visual_review": "required: inspect thumbnail grid, page coverage, content and visual differences",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("choices", type=Path)
    parser.add_argument("--require-layout", action="store_true", help="Require native-aspect source crops and hash-bound geometry for every thumbnail")
    args = parser.parse_args()
    try:
        spec = read_json(args.choices)
        result = validate_style_options(spec, args.choices.resolve().parent, args.require_layout)
    except (ValueError, OSError) as error:
        parser.exit(2, f"validate_style_options: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
