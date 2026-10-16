"""Check original evidence pixels embedded in image slides; no OCR or semantic claims."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageChops, ImageOps


def relative_file(base: Path, name: str) -> Path:
    root = base.resolve()
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root):
        raise ValueError(f"Preserved asset path must stay inside Page Spec directory: {name}")
    return path


def source_pixels(base: Path, declaration: dict) -> Image.Image:
    path = relative_file(base, declaration["file"])
    if not path.is_file():
        raise ValueError(f"Missing preserved asset: {declaration['file']}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != declaration["sha256"]:
        raise ValueError(f"Preserved asset source hash changed: {declaration['file']}")
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGBA")
        # A fixed opaque rectangle makes the actual evidence check unambiguous.
        if image.getchannel("A").getextrema() != (255, 255):
            raise ValueError("Preserved assets must be opaque; prepare and approve an opaque source first")
        return image.convert("RGB")


def expected_patch(base: Path, declaration: dict) -> Image.Image:
    source = source_pixels(base, declaration)
    _, _, width, height = declaration["region"]
    ratio = source.width / source.height
    if abs(width - height * ratio) > max(1.0, ratio) + 1e-6:
        raise ValueError("Preserved asset region must preserve source aspect ratio without cropping")
    return source.resize((width, height), Image.Resampling.LANCZOS)


def validate_preserved_assets(slide: dict, base: Path, require_image: bool) -> None:
    declarations = [element["preserve_asset"] for element in slide["elements"]
                    if "preserve_asset" in element]
    if not declarations:
        return
    rectangles = []
    patches = []
    for declaration in declarations:
        if relative_file(base, declaration["file"]) == relative_file(base, slide["image_file"]):
            raise ValueError("Preserved asset must be independent of the slide image")
        patch = expected_patch(base, declaration)
        x, y, width, height = declaration["region"]
        box = (x, y, x + width, y + height)
        if any(x < right and x + width > left and y < bottom and y + height > top
               for left, top, right, bottom in rectangles):
            raise ValueError("Preserved asset regions must not overlap")
        rectangles.append(box)
        patches.append(patch)
    if not require_image:
        return
    path = relative_file(base, slide["image_file"])
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError("Slides with preserved assets require lossless PNG")
        page = ImageOps.exif_transpose(image).convert("RGBA")
        if page.getchannel("A").getextrema() != (255, 255):
            raise ValueError("Slides with preserved assets must be opaque")
        page = page.convert("RGB")
        for box, patch in zip(rectangles, patches):
            if box[2] > page.width or box[3] > page.height:
                raise ValueError("Preserved asset region outside actual slide image")
            if ImageChops.difference(page.crop(box), patch).getbbox() is not None:
                raise ValueError(f"Preserved asset pixels changed on {slide['id']}: {box}")
