#!/usr/bin/env python3
"""Resume host-generated Page Spec slides, compose protected evidence, and bind reviews."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import tempfile
import time
from pathlib import Path

from audit_page_content import text_present
from content_density import visible_text
from json_io import read_json
from PIL import Image, ImageOps
from preserved_assets import expected_patch, relative_file, validate_preserved_assets
from record_work import locked_log
from validate_page_spec import load_page_spec

CHECKS = ("semantic_coverage", "source_accuracy", "readability", "density", "visual_relationships")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def seal(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def save(path, value):
    atomic(path, encoded(value))


def store(root, data, suffix):
    """Content-addressed snapshots survive a crash before the state commit."""
    path = root / "artifacts" / (digest(data) + suffix)
    if path.exists() and path.read_bytes() != data:
        raise ValueError("Production snapshot changed")
    if not path.exists():
        atomic(path, data)
    return str(path.relative_to(root))


def fingerprint(spec, slide, base):
    intent = {key: value for key, value in slide.items() if key not in ("image_status", "speaker_notes", "notes")}
    intent["elements"] = [{key: value for key, value in e.items() if key not in ("notes", "prompt_record")}
                          for e in slide["elements"]]
    refs = spec["style"].get("tokens", {}).get("reference_images", [])
    return seal({"slide": intent, "canvas": spec["canvas"], "style": spec["style"],
                 "content_version": spec["content_version"], "authorization": spec["content_authorization"],
                 "references": {name: digest(relative_file(base, name).read_bytes()) for name in refs}})


def generation_input(spec, slide):
    return {"instructions": (
        "Use the actual host image tool under its tool rules. Preserve the confirmed style and visible text. "
        "Semantic fields describe meaning; when display.coverage exists, express them through mapped elements "
        "without adding repeated bullets. Keep speaker notes off the slide. "
        "Leave every preserve_asset.region blank for later local placement of the original evidence; "
        "do not redraw evidence, move its region or place other text there. Current canvas, visible text and "
        "preserve_asset.region override any older coordinates or wording in generation_prompt and bbox_hint. "
        "Return the independent generated original."),
        "canvas": spec["canvas"], "style": spec["style"], "slide": {k: v for k, v in slide.items() if k != "image_status"},
        "protected_regions": [{"element_id": e["id"], "region": e["preserve_asset"]["region"]}
                              for e in slide["elements"] if "preserve_asset" in e],
        "required_visible_text": visible_text(slide)}


def workspace(spec_path):
    return spec_path.parent / ("." + spec_path.stem + "-production")


def current(spec_path, spec, root, *, persist=True):
    state_path = root / "state.json"
    state = read_json(state_path) if state_path.exists() else {"version": "1.0", "pages": {}}
    if state.get("version") != "1.0" or not isinstance(state.get("pages"), dict):
        raise ValueError("Unsupported production state")
    if state_path.exists() and state.get("state_sha256") != seal({k: v for k, v in state.items() if k != "state_sha256"}):
        raise ValueError("Production state changed; retain it for recovery")
    pages = {}
    for slide in spec["slides"]:
        contract = fingerprint(spec, slide, spec_path.parent)
        old = state["pages"].get(slide["id"], {})
        if old.get("contract_sha256") == contract:
            for name, hash_name in (("image_snapshot", "image_sha256"), ("source_snapshot", "source_sha256"),
                                    ("review_snapshot", None), ("intent_snapshot", None), ("prompt_snapshot", None)):
                if name in old:
                    stored = relative_file(root, old[name])
                    expected = old[hash_name] if hash_name else stored.name[:64]
                    if not stored.is_file() or digest(stored.read_bytes()) != expected:
                        raise ValueError("Committed production snapshot changed")
            pages[slide["id"]] = old
        else:
            snapshot = store(root, encoded({"canvas": spec["canvas"], "style": spec["style"], "slide": slide}), ".json") if persist else None
            pages[slide["id"]] = {"contract_sha256": contract, "intent_snapshot": snapshot,
                                  "status": "pending", "history": [*old.get("history", []), *([{k: v for k, v in old.items() if k != "history"}] if old else [])]}
        if persist and "prompt_snapshot" not in pages[slide["id"]]:
            pages[slide["id"]]["prompt_snapshot"] = store(root, encoded(generation_input(spec, slide)), ".prompt.json")
    state["pages"] = pages
    return state


def validate_targets(spec_path, spec, root):
    inputs = {spec_path.resolve()}
    inputs.update(relative_file(spec_path.parent, e["preserve_asset"]["file"])
                  for s in spec["slides"] for e in s["elements"] if "preserve_asset" in e)
    inputs.update(relative_file(spec_path.parent, name) for name in spec["style"].get("tokens", {}).get("reference_images", []))
    for slide in spec["slides"]:
        target = relative_file(spec_path.parent, slide["image_file"])
        if target in inputs or target.is_relative_to(root) or target.suffix.lower() != ".png":
            raise ValueError("Production outputs must be independent PNGs outside the managed state directory")
        for element in slide["elements"]:
            if "preserve_asset" in element:
                x, y, w, h = element["preserve_asset"]["region"]
                if x + w > spec["canvas"]["width"] or y + h > spec["canvas"]["height"]:
                    raise ValueError("Protected region outside canvas")


def project(spec_path, spec, root, state):
    """Materialize committed state; rerunning prepare repairs interrupted projections."""
    for slide in spec["slides"]:
        page = state["pages"][slide["id"]]
        if page["status"] != "pending":
            data = relative_file(root, page["image_snapshot"]).read_bytes()
            if digest(data) != page["image_sha256"]:
                raise ValueError("Committed image snapshot changed")
            target = relative_file(spec_path.parent, slide["image_file"])
            if not target.exists() or digest(target.read_bytes()) != page["image_sha256"]:
                atomic(target, data)
        slide["image_status"] = page["status"]
    if encoded(read_json(spec_path)) != encoded(spec):
        save(spec_path, spec)
    lines = ["# 当前图片制作状态", "", "由当前 Page Spec 和制作记录生成；历史叙述不作为当前状态。", "",
             "| 页面 | 状态 | 原图像素 | 成品像素 | 放大 |", "|---|---|---|---|---|"]
    for slide in spec["slides"]:
        page = state["pages"][slide["id"]]
        lines.append(f"| {slide['id']} | {page['status']} | {page.get('source_pixels', '—')} | {page.get('final_pixels', '—')} | {page.get('upscaled', '—')} |")
    atomic(root / "status.md", ("\n".join(lines) + "\n").encode())


def commit(spec_path, spec, root, state):
    # This atomic state write is the commit point; all outputs are projections.
    state["state_sha256"] = seal({k: v for k, v in state.items() if k != "state_sha256"})
    save(root / "state.json", state)
    project(spec_path, spec, root, state)


def compose(spec_path, spec, root, state, slide, source, allow_upscale):
    started = time.monotonic()
    page = state["pages"][slide["id"]]
    target = relative_file(spec_path.parent, slide["image_file"])
    if source.resolve() == target:
        raise ValueError("Provide the independent host-generated original, not a final image")
    raw = source.read_bytes()
    if source.resolve().is_relative_to(root):
        candidates = [page, *page.get("history", [])]
        known = any(item.get("source_snapshot") and relative_file(root, item["source_snapshot"]) == source.resolve()
                    and item.get("source_sha256") == digest(raw) for item in candidates)
        if not known:
            raise ValueError("Managed inputs must be a retained, unchanged original source snapshot")
    with Image.open(io.BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    if image.getchannel("A").getextrema() != (255, 255):
        raise ValueError("Host-generated slide must be opaque")
    size = (int(spec["canvas"]["width"]), int(spec["canvas"]["height"]))
    ratio = size[0] / size[1]
    if abs(image.width - image.height * ratio) > max(1, ratio) + 1e-6:
        raise ValueError("Source aspect differs from canvas; do not stretch or pad a slide")
    upscaled = image.width < size[0] or image.height < size[1]
    if upscaled and not allow_upscale:
        raise ValueError("Source below target resolution; retain it or explicitly use --allow-upscale")
    if page.get("source_sha256") == digest(raw) and page["status"] != "pending":
        return
    original_size = list(image.size)
    image = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    regions = []
    for element in slide["elements"]:
        if "preserve_asset" in element:
            declaration = element["preserve_asset"]
            x, y, w, h = declaration["region"]
            if x + w > size[0] or y + h > size[1]:
                raise ValueError("Protected region outside canvas")
            image.paste(expected_patch(spec_path.parent, declaration), (x, y))
            regions.append({"element_id": element["id"], "region": [x, y, w, h]})
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    old = {key: value for key, value in page.items() if key != "history"}
    page.update({"status": "generated", "source_snapshot": store(root, raw, ".source"),
                 "source_sha256": digest(raw), "source_pixels": original_size,
                 "final_pixels": list(size), "upscaled": upscaled, "protected_regions": regions,
                 "image_snapshot": store(root, data, ".png"), "image_sha256": digest(data),
                 "compose_seconds": time.monotonic() - started})
    page.pop("review_snapshot", None)
    page["history"] = [*page.get("history", []), old]


def review_template(slide, page):
    if page["status"] == "pending":
        raise ValueError("Compose the page before requesting its review")
    return {"version": "1.0", "id": slide["id"], "contract_sha256": page["contract_sha256"],
            "image_sha256": page["image_sha256"], "reviewer": "", "observed_text": "",
            "viewed_pixels": None, "checks": {name: {"status": "pending", "notes": "", "targets": []} for name in CHECKS},
            "protected_regions": page.get("protected_regions", []),
            "scope": "Actual visual observations and source comparison; hash/text matches do not prove truth or independence."}


def accept(spec_path, slide, root, page, record):
    if page["status"] == "pending":
        raise ValueError("Compose the page before review")
    value = read_json(record)
    for key, expected in (("version", "1.0"), ("id", slide["id"]), ("contract_sha256", page["contract_sha256"]), ("image_sha256", page["image_sha256"])):
        if value.get(key) != expected:
            raise ValueError("Stale or mismatched production review")
    if not isinstance(value.get("reviewer"), str) or not value["reviewer"].strip():
        raise ValueError("Review requires an identified reviewer; independence is not inferred")
    pixels = value.get("viewed_pixels")
    if not isinstance(pixels, list) or len(pixels) != 2 or any(type(p) is not int or p <= 0 for p in pixels):
        raise ValueError("Declare the actual review viewport dimensions")
    text = value.get("observed_text")
    if not isinstance(text, str) or any(not text_present(t, text) for t in visible_text(slide)):
        raise ValueError("Review transcription misses required visible text")
    ids = {e["id"] for e in slide["elements"]} | {"page"}
    checks = value.get("checks", {})
    for name in CHECKS:
        check = checks.get(name, {})
        targets = check.get("targets")
        if (check.get("status") != "pass" or not isinstance(check.get("notes"), str) or not check["notes"].strip()
                or not isinstance(targets, list) or not targets or any(not isinstance(t, str) or t not in ids for t in targets)):
            raise ValueError(f"Review {name} needs actual pass, observations and valid targets")
    # Compare the current projection too; never certify a substituted final PNG.
    target = relative_file(spec_path.parent, slide["image_file"])
    if not target.is_file() or digest(target.read_bytes()) != page["image_sha256"]:
        raise ValueError("Final image changed since composition")
    validate_preserved_assets(slide, spec_path.parent, True)
    page["review_snapshot"] = store(root, encoded(value), ".review.json")
    page["status"] = "approved"


def execute(spec_path, action, *, slide_id=None, source=None, allow_upscale=False, record=None, element_id=None, region=None):
    spec_path = Path(spec_path).resolve()
    root = workspace(spec_path)
    if action == "status":
        spec, _ = load_page_spec(spec_path, strict=True, content=True)
        state = current(spec_path, spec, root, persist=False)
        return {"state": str(root / "state.json"), "pages": state["pages"]}
    root.mkdir(parents=True, exist_ok=True)
    with locked_log(root / "transaction"):
        spec, _ = load_page_spec(spec_path, strict=True, content=True)
        if any(type(v) is not int for v in spec["canvas"].values()):
            raise ValueError("Production canvas needs integer pixel dimensions")
        validate_targets(spec_path, spec, root)
        state = current(spec_path, spec, root)
        selected = next((s for s in spec["slides"] if s["id"] == slide_id), None)
        if action not in ("prepare", "status") and selected is None:
            raise ValueError("Provide an existing --slide ID")
        if action == "region":
            element = next((e for e in selected["elements"] if e["id"] == element_id and "preserve_asset" in e), None)
            if element is None:
                raise ValueError("Provide a protected --element ID")
            changed = copy.deepcopy(spec)
            changed_slide = next(s for s in changed["slides"] if s["id"] == slide_id)
            changed_element = next(e for e in changed_slide["elements"] if e["id"] == element_id)
            changed_element["preserve_asset"]["region"] = region
            changed_element["bbox_hint"] = region
            from validate_page_spec import validate_page_spec
            validate_page_spec(changed, spec_path.parent, strict=True, content=True)
            validate_targets(spec_path, changed, root)
            # Save the old intent before the single source of truth changes.
            store(root, spec_path.read_bytes(), ".page-spec.json")
            save(spec_path, changed)
            spec = changed
            state = current(spec_path, spec, root)
        elif action == "compose":
            if source is None:
                raise ValueError("compose requires --source")
            compose(spec_path, spec, root, state, selected, Path(source), allow_upscale)
        elif action == "review-init":
            if record is None or Path(record).exists():
                raise ValueError("Provide a new --record path; retain previous reviews")
            if Path(record).resolve() in {spec_path, *[relative_file(spec_path.parent, s["image_file"]) for s in spec["slides"]]} or Path(record).resolve().is_relative_to(root):
                raise ValueError("Review record must be independent of managed outputs")
            save(Path(record), review_template(selected, state["pages"][slide_id]))
        elif action == "accept":
            if record is None:
                raise ValueError("accept requires --record")
            accept(spec_path, selected, root, state["pages"][slide_id], Path(record))
        elif action not in ("prepare", "status"):
            raise ValueError("Unknown production action")
        commit(spec_path, spec, root, state)
        return {"state": str(root / "state.json"), "summary": str(root / "status.md"),
                "pages": {key: {k: v for k, v in page.items() if k != "history"} for key, page in state["pages"].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "status", "compose", "review-init", "accept", "region"))
    parser.add_argument("page_spec", type=Path)
    parser.add_argument("--slide")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--allow-upscale", action="store_true")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--element")
    parser.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    args = parser.parse_args()
    try:
        result = execute(args.page_spec, args.action, slide_id=args.slide, source=args.source,
                         allow_upscale=args.allow_upscale, record=args.record, element_id=args.element, region=args.region)
    except (ValueError, OSError) as error:
        parser.exit(2, f"produce: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
