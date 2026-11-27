"""Register independent original images and verify byte-preserving reuse."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from deck_run_state import (
    find_page,
    load_deck,
    load_jobs,
    page_dir_for,
    resolve_inside,
    run_dir_from_target,
)
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def asset_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value) is None:
        raise ValueError("Original asset ID must be a safe, nonempty filename component")
    return value


def original_run(manifest_path):
    """Locate the real run, not a receipt supplied by a page worker."""
    manifest_path = Path(manifest_path).resolve()
    for directory in manifest_path.parents:
        if not (directory / "deck_manifest.json").is_file() or not (directory / "page_jobs.json").is_file():
            continue
        deck = load_deck(directory)
        for page in deck.get("pages", []):
            page_dir = resolve_inside(directory, page["page_dir"])
            if manifest_path.is_relative_to(page_dir):
                return directory
    raise ValueError("Preserved originals require a prepared run and a manifest inside one of its pages")


def preserved_original_error(entry, manifest_path):
    """A worker's provenance claim cannot substitute for the input registration."""
    try:
        if entry.get("source_type") != "user-provided":
            raise ValueError("Preserved originals require user-provided provenance")
        identifier = asset_id(entry.get("original_asset_id"))
        run = original_run(manifest_path)
        bundle = resolve_inside(run / "input", f"preserved-originals/{identifier}")
        receipt = json.loads((bundle / "registration.json").read_text(encoding="utf-8"))
        if receipt.get("version") != 1 or receipt.get("id") != identifier:
            raise ValueError("Invalid original asset registration")
        original = resolve_inside(bundle, receipt["file"])
        source = (Path(manifest_path).parent / entry["source"]).resolve()
        asset = resolve_inside(Path(manifest_path).parent, entry["path"])
        expected = receipt.get("sha256")
        if (source != original or not isinstance(expected, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected) is None
                or digest(original) != expected or digest(asset) != expected):
            raise ValueError("Preserved asset or original source differs from its registered hash")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return str(error)
    return None


def register_original(run, page, source, identifier, note):
    """Copy a supplied image once into inputs and return truthful provenance."""
    run = run_dir_from_target(run)
    page_dir = page_dir_for(run, find_page(load_jobs(run), page)).resolve()
    identifier = asset_id(identifier)
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ValueError("Original asset source must be an existing image")
    if source.is_relative_to(run) and not source.is_relative_to(run / "input"):
        raise ValueError("Register the independent supplied original, not a page output or a crop from the run")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("Record the supplied image's actual source in --note")
    raw = source.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        extension = {"PNG": ".png", "JPEG": ".jpg"}.get(image.format)
        if extension is None:
            raise ValueError("Preserved originals must be PNG or JPEG images")
        image.verify()
    expected = hashlib.sha256(raw).hexdigest()
    registry = resolve_inside(run / "input", "preserved-originals")
    registry.mkdir(parents=True, exist_ok=True)
    bundle = resolve_inside(registry, identifier)
    receipt = {"version": 1, "id": identifier, "file": "original" + extension,
               "sha256": expected, "source_name": source.name, "note": note.strip()}
    if bundle.exists():
        previous = json.loads((bundle / "registration.json").read_text(encoding="utf-8"))
        if previous.get("sha256") != expected or previous.get("file") != receipt["file"]:
            raise ValueError("Original asset ID already names a different input; use a new ID")
        if digest(resolve_inside(bundle, previous["file"])) != expected:
            raise ValueError("Previously registered original has changed")
    else:
        with tempfile.TemporaryDirectory(prefix=".register-", dir=registry) as temporary:
            stage = Path(temporary) / "asset"
            stage.mkdir()
            (stage / receipt["file"]).write_bytes(raw)
            (stage / "registration.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stage.rename(bundle)
    original = bundle / receipt["file"]
    target = resolve_inside(page_dir, f"assets/{identifier}{extension}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(target) != expected:
            raise ValueError("Page asset already exists with different bytes; use a new asset ID")
    else:
        # Exclusive creation never replaces a page's existing work.
        with target.open("xb") as output, original.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
    return {"path": target.relative_to(page_dir).as_posix(), "source_type": "user-provided",
            "source": Path(os.path.relpath(original, page_dir)).as_posix(),
            "original_asset_id": identifier, "provenance_note": note.strip()}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--page", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--note", required=True, help="Actual source of the supplied original; no new approval is requested")
    args = parser.parse_args()
    try:
        entry = register_original(args.run, args.page, args.source, args.asset_id, args.note)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"preserve-asset: {error}\n")
    print(json.dumps({"asset_provenance": entry, "visual_inventory": {
        "role": "foreground", "path": entry["path"], "source_type": "user-provided"}},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
