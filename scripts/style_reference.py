#!/usr/bin/env python3
"""Bind an explicitly selected single-page style reference to its source pixels."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps
from record_work import locked_log

DECLARATION_FIELDS = {"version", "kind", "source", "source_sha256", "box", "image", "image_sha256"}
SELECTIONS = {"selected", "delegated"}
GUIDANCE = ("Run slidemuse.py style-reference <page-spec.json> --box X Y W H "
            "--output styles/reference.png using the measured bounds of one complete slide in the selected preview")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative_file(base, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Style reference paths must be nonempty relative paths")
    path = Path(name)
    root = Path(base).resolve()
    resolved = (root / path).resolve()
    if path.is_absolute() or not resolved.is_relative_to(root):
        raise ValueError(f"Style reference must stay inside Page Spec directory: {name}")
    return resolved


def references(style):
    names = style.get("tokens", {}).get("reference_images", [])
    if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("Style reference_images must be a list of relative image paths")
    return names


def selected_source(style, base):
    names = references(style)
    if not names:
        raise ValueError("Record the selected source as the first style.tokens.reference_images entry")
    if style.get("decision") in SELECTIONS and (
            type(style.get("option")) is not int or not 1 <= style["option"] <= 4
            or not isinstance(style.get("choice"), str) or not style["choice"].strip()):
        raise ValueError("Selected or delegated style reference requires its numbered option and name")
    path = relative_file(base, names[0])
    if not path.is_file():
        raise ValueError(f"Missing selected style reference: {names[0]}")
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as opened:
        if style.get("decision") in SELECTIONS:
            label = opened.info.get("slidemuse_style_option")
            if label is not None and (label != str(style["option"])
                                      or opened.info.get("slidemuse_style_name") != style["choice"].strip()):
                raise ValueError("Selected style number or name differs from the labeled preview")
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    return names[0], path, raw, image


def reference_pixels(source, box, kind):
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(value) is not int for value in box)):
        raise ValueError("Style reference box must contain four integer pixel coordinates: x, y, width, height")
    x, y, width, height = box
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > source.width or y + height > source.height:
        raise ValueError("Style reference box must stay inside the EXIF-oriented source image")
    full = [0, 0, source.width, source.height]
    if kind == "single-page":
        if list(box) != full:
            raise ValueError("A single-page style reference must preserve the entire source without cropping")
    elif kind == "preview-crop":
        if list(box) == full:
            raise ValueError("Do not use the entire overview as a preview-crop; select one complete slide")
        # Thumbnail dimensions can differ by one pixel after raster rounding.
        if width < 16 or height < 9 or abs(width - height * 16 / 9) > 16 / 9 + 1e-6:
            raise ValueError("Preview crop must cover one complete 16:9 slide; measure its bounds without resizing")
    else:
        raise ValueError("Style reference kind must be preview-crop or single-page")
    return source.crop((x, y, x + width, y + height))


def reference_result(style, kind, image_path, image_raw, source_path, source_raw, box):
    return {"kind": kind, "path": str(image_path), "sha256": digest(image_raw),
            "source_path": str(source_path), "source_sha256": digest(source_raw),
            "box": list(box), "option": style.get("option"), "choice": style.get("choice")}


def resolve_reference(spec, base, required=False):
    """Verify a declared crop, or retain an explicitly locked existing single page.

    Old selected styles remain readable without a declaration when required=False.
    Callers preparing a new visual generation request decide when it is required.
    """
    style = spec["style"]
    decision = style.get("decision")
    if "generation_reference" not in style:
        if decision in SELECTIONS and required:
            raise ValueError("Selected style needs an explicit single-page generation reference. " + GUIDANCE)
        if decision == "locked-reference" and references(style):
            _, path, raw, source = selected_source(style, base)
            return reference_result(style, "single-page", path, raw, path, raw, [0, 0, *source.size])
        return None

    declaration = style["generation_reference"]
    if not isinstance(declaration, dict) or set(declaration) != DECLARATION_FIELDS:
        raise ValueError("Style generation_reference must contain exactly version, kind, source, source_sha256, box, image and image_sha256")
    if declaration["version"] != "1.0" or declaration["kind"] not in {"preview-crop", "single-page"}:
        raise ValueError("Unsupported style generation_reference version or kind")
    if decision not in {*SELECTIONS, "locked-reference"}:
        raise ValueError("A generation reference requires a selected, delegated or locked-reference style")
    if declaration["kind"] == "single-page" and decision != "locked-reference":
        raise ValueError("Use preview-crop for selected/delegated overviews; single-page requires locked-reference")
    for field in ("source_sha256", "image_sha256"):
        if not isinstance(declaration[field], str) or not re.fullmatch(r"[0-9a-f]{64}", declaration[field]):
            raise ValueError(f"Style generation_reference {field} must be a SHA256 hash")
    name, source_path, source_raw, source = selected_source(style, base)
    if declaration["source"] != name:
        raise ValueError("Generation reference source must match the first selected reference_images entry")
    if digest(source_raw) != declaration["source_sha256"]:
        raise ValueError("Selected style source hash changed; register a new reference from the current selection")
    expected = reference_pixels(source, declaration["box"], declaration["kind"])
    image_path = relative_file(base, declaration["image"])
    if image_path == source_path:
        raise ValueError("Derived style reference must be independent of the selected source")
    if declaration["image"] not in references(style):
        raise ValueError("Derived style reference must be retained in style.tokens.reference_images")
    if not image_path.is_file():
        raise ValueError(f"Missing derived style reference: {declaration['image']}")
    raw = image_path.read_bytes()
    if digest(raw) != declaration["image_sha256"]:
        raise ValueError("Derived style reference hash changed; retain the registered PNG")
    with Image.open(io.BytesIO(raw)) as opened:
        if opened.format != "PNG" or opened.getexif().get(274, 1) != 1:
            raise ValueError("Derived style reference must be an orientation-normalized PNG")
        actual = opened.convert("RGBA")
    if actual.size != expected.size or actual.tobytes() != expected.tobytes():
        raise ValueError("Derived style reference pixels differ from the declared source crop; do not redraw or resize it")
    return reference_result(style, declaration["kind"], image_path, raw, source_path, source_raw, declaration["box"])


def report(reference, spec_path):
    return {**reference, "page_spec": str(spec_path), "purpose": "style-reference-only", "image_generation_calls": 0,
            "scope": "Visual style reference only; this crop is not a generated or final delivery slide."}


def create_reference(spec_path, output, box=None, single_page=False):
    """Create a lossless reference and register it under the production transaction lock."""
    # Local imports avoid a cycle: Page Spec validation also checks this declaration.
    from page_production import workspace
    from validate_page_spec import validate_page_spec

    spec_path = Path(spec_path).resolve()
    base = spec_path.parent
    requested = Path(output)
    requested = requested if requested.is_absolute() else base / requested
    target = requested.resolve()
    if (not target.is_relative_to(base) or target.suffix.lower() != ".png"
            or requested.is_symlink() or target.is_relative_to(workspace(spec_path).resolve())):
        raise ValueError("Output must be an independent PNG inside the Page Spec directory, outside managed production state")
    if single_page and box is not None:
        raise ValueError("Use either --box or --single-page, not both")
    with locked_log(workspace(spec_path) / "transaction"):
        original = spec_path.read_bytes()
        spec = json.loads(original.decode("utf-8-sig"))
        style = spec["style"]
        decision = style.get("decision")
        if decision not in {*SELECTIONS, "locked-reference"}:
            raise ValueError("Choose or lock a style before creating its visual reference")
        if single_page and decision != "locked-reference":
            raise ValueError("--single-page requires an explicitly locked-reference style")
        source_name, source_path, source_raw, source = selected_source(style, base)
        kind = "single-page" if single_page else "preview-crop"
        if single_page:
            box = [0, 0, *source.size]
        elif box is None:
            raise ValueError(GUIDANCE + "; an explicitly locked single page may use --single-page")
        pixels = reference_pixels(source, box, kind)
        # Do not retain overview labels or EXIF transforms on the independent crop.
        pixels.info.clear()
        buffer = io.BytesIO()
        pixels.save(buffer, format="PNG")
        image_raw = buffer.getvalue()
        image_name = target.relative_to(base).as_posix()
        declaration = {"version": "1.0", "kind": kind, "source": source_name,
                       "source_sha256": digest(source_raw), "box": list(box),
                       "image": image_name, "image_sha256": digest(image_raw)}
        previous = style.get("generation_reference")
        old_image = relative_file(base, previous["image"]) if isinstance(previous, dict) and "image" in previous else None
        protected = {spec_path, source_path}
        protected.update(relative_file(base, slide["image_file"]) for slide in spec["slides"])
        protected.update(relative_file(base, element["preserve_asset"]["file"])
                         for slide in spec["slides"] for element in slide["elements"] if "preserve_asset" in element)
        protected.update(relative_file(base, name) for name in references(style)
                         if relative_file(base, name) != old_image)
        if target in protected:
            raise ValueError("Style reference output must not overwrite the source, slide images, Page Spec or other assets")
        if target.exists():
            same = (isinstance(previous, dict) and all(previous.get(key) == value for key, value in declaration.items()
                                                      if key != "image_sha256"))
            if not target.is_file() or not same:
                raise ValueError("Output already exists and is not this registered reference; choose a new PNG path")
            validate_page_spec(spec, base, strict=True)
            return report(resolve_reference(spec, base, required=True), spec_path)

        updated = copy.deepcopy(spec)
        updated["style"]["generation_reference"] = declaration
        names = updated["style"]["tokens"]["reference_images"]
        if image_name not in names:
            names.append(image_name)
        result = report(reference_result(style, kind, target, image_raw, source_path, source_raw, box), spec_path)
        parents = []
        published = False
        with tempfile.TemporaryDirectory(prefix=".style-reference-", dir=base) as temporary:
            stage = Path(temporary)
            staged_image, staged_spec = stage / "reference.png", stage / "page-spec.json"
            staged_image.write_bytes(image_raw)
            staged_spec.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            # Validate the complete new contract before publishing either file.
            candidate = copy.deepcopy(updated)
            staged_name = staged_image.relative_to(base).as_posix()
            candidate["style"]["generation_reference"]["image"] = staged_name
            candidate["style"]["tokens"]["reference_images"] = [
                staged_name if name == image_name else name for name in names]
            validate_page_spec(candidate, base, strict=True)

            def unchanged():
                if spec_path.read_bytes() != original or source_path.read_bytes() != source_raw:
                    raise ValueError("Page Spec or selected source changed during reference creation; retry with current inputs")

            try:
                unchanged()
                parent = target.parent
                while not parent.exists():
                    parents.append(parent)
                    parent = parent.parent
                target.parent.mkdir(parents=True, exist_ok=True)
                # A hard link publishes complete bytes without replacing a racing file.
                os.link(staged_image, target)
                published = True
                unchanged()
                os.replace(staged_spec, spec_path)
            except BaseException:
                if published and target.exists() and target.samefile(staged_image):
                    target.unlink()
                for parent in parents:
                    try:
                        parent.rmdir()
                    except OSError:
                        pass
                raise
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page_spec", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--box", nargs=4, type=int, metavar=("X", "Y", "WIDTH", "HEIGHT"),
                      help="Measured bounds of one complete 16:9 slide in the selected overview; never guessed")
    mode.add_argument("--single-page", action="store_true", help="Keep an explicitly locked full single-page reference")
    parser.add_argument("--output", required=True, type=Path, help="New PNG path, relative to the Page Spec directory")
    args = parser.parse_args()
    try:
        result = create_reference(args.page_spec, args.output, args.box, args.single_page)
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(2, f"style-reference: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
