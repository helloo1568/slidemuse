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
import uuid
from pathlib import Path

from audit_page_content import text_present
from content_density import WORKFLOW_POLICY, prompt_elements, visible_text
from json_io import read_json
from PIL import Image, ImageOps
from preserved_assets import expected_patch, relative_file, validate_preserved_assets
from record_work import locked_log
from validate_page_spec import load_page_spec

CHECKS = ("semantic_coverage", "source_accuracy", "readability", "density", "visual_relationships")
ROUTES = ("host", "fresh-host", "isolated-worker", "isolated-api")
FAILURE_KINDS = ("multi-page", "style-drift", "text", "chart", "tool-error", "other")


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
    contract = {"slide": intent, "canvas": spec["canvas"], "style": spec["style"],
                "references": {name: digest(relative_file(base, name).read_bytes()) for name in refs}}
    if spec.get("content_policy") == WORKFLOW_POLICY:
        contract["content_policy"] = WORKFLOW_POLICY
        contract["style"] = {key: value for key, value in spec["style"].items() if key != "authorization"}
        if slide.get("depends_on_slide_count"):
            contract["slide_count"] = len(spec["slides"])
    else:
        # Keep existing production snapshots readable under their original policy.
        contract.update(content_version=spec["content_version"], authorization=spec["content_authorization"])
    return seal(contract)


def generation_input(spec, slide):
    content = {k: v for k, v in slide.items() if k not in {"image_status", "image_file", "image_origin", "source_refs", "speaker_notes", "notes", "generation_prompt"}}
    style = copy.deepcopy(spec["style"])
    style.pop("authorization", None)
    # Preview references stay in Page Spec for selection and integrity, not in the generation packet.
    style.get("tokens", {}).pop("reference_images", None)
    content["elements"] = prompt_elements(slide["elements"])
    return {"instructions": (
        "Generate ONE independent full-canvas slide using the actual authorized image model. "
        "Never output a contact sheet, thumbnails, multiple slides, or a preview grid. "
        "Use only this page packet and its explicitly selected single-page style anchor; ignore prior preview instructions. "
        "Preserve the confirmed style and visible text. "
        "Use the exact visible text list for wording. Express semantic fields through the approved text and graphics. "
        "Keep recorded sources and speaker notes off the slide. "
        "Leave every preserve_asset.region blank for later local placement of the original evidence; "
        "do not redraw evidence, move its region or place other text there. Current canvas, visible text and "
        "preserve_asset.region override any older coordinates or wording in bbox_hint. "
        "Return the independent generated original."),
        "canvas": spec["canvas"], "style": style, "slide": content,
        "protected_regions": [{"element_id": e["id"], "region": e["preserve_asset"]["region"]}
                              for e in slide["elements"] if "preserve_asset" in e],
        "required_visible_text": visible_text(slide, policy=spec.get("content_policy"))}


def workspace(spec_path):
    return spec_path.parent / ("." + spec_path.stem + "-production")


def provided_image(spec_path, slide, page):
    if any(previous.get("source_snapshot") or previous.get("generation_snapshot")
           for previous in (page, *page.get("history", []))):
        raise ValueError("A generated page cannot bypass production review by changing its origin to provided")
    data = relative_file(spec_path.parent, slide["image_file"]).read_bytes()
    if digest(data) != slide["image_origin"]["sha256"]:
        raise ValueError(f"Provided image changed since its recorded approval: {slide['id']}")
    return data


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
                                    ("review_snapshot", None), ("intent_snapshot", None), ("prompt_snapshot", None),
                                    ("request_snapshot", None), ("generation_snapshot", None),
                                    ("generation_request_snapshot", None)):
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
        if slide.get("image_origin"):
            data = provided_image(spec_path, slide, pages[slide["id"]])
            pages[slide["id"]].update(source_kind="provided", status=slide["image_status"], image_sha256=digest(data))
            if persist:
                suffix = Path(slide["image_file"]).suffix.lower()
                pages[slide["id"]]["image_snapshot"] = store(root, data, suffix)
        if persist:
            pages[slide["id"]]["prompt_snapshot"] = store(root, encoded(generation_input(spec, slide)), ".prompt.json")
    state["pages"] = pages
    return state


def route_blocked(page, route):
    failures = [f for f in page.get("generation_failures", []) if f["route"] == route]
    return len(failures) >= 2 and failures[-1]["kind"] == failures[-2]["kind"]


def request_page(spec, slide, root, state, route):
    if route not in ROUTES:
        raise ValueError("Choose a real generation route")
    page = state["pages"][slide["id"]]
    if slide.get("image_origin"):
        raise ValueError("Provided images use their explicit import path; new generation must remove image_origin")
    if page["status"] == "approved":
        raise ValueError("Page is already approved; revise its contract before regeneration")
    if route_blocked(page, route):
        raise ValueError("Two repeated failures on this route; change isolation method or report blocked")
    packet = generation_input(spec, slide)
    packet.update(request_id=uuid.uuid4().hex, route=route, contract_sha256=page["contract_sha256"])
    # Only reviewed full-page originals/projections can anchor the next page.
    candidates = [s for s in spec["slides"] if s["id"] != slide["id"]
                  and state["pages"][s["id"]]["status"] == "approved"]
    candidates.sort(key=lambda s: (s.get("role") == "cover", s["page_number"]))
    page.pop("request_reference", None)
    if candidates:
        anchor = candidates[0]
        approved = state["pages"][anchor["id"]]
        if not anchor.get("image_origin"):
            verified_generation(root, approved, anchor["id"])
        reference = relative_file(root, approved["image_snapshot"])
        if digest(reference.read_bytes()) != approved["image_sha256"]:
            raise ValueError("Approved style anchor changed")
        page["request_reference"] = str(reference)
        packet["style_anchor"] = {"slide_id": anchor["id"], "use": "Style only; never reproduce the anchor's text or layout"}
    page["request_snapshot"] = store(root, encoded(packet), ".request.json")
    page["request_sha256"] = digest(encoded(packet))
    page["request_route"] = route


def record_failure(page, route, kind, evidence):
    if route not in ROUTES or kind not in FAILURE_KINDS or not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("Provide route, failure kind and actual call/result evidence")
    if page.get("request_route") != route or not page.get("request_snapshot"):
        raise ValueError("Prepare the independent request before recording a failed call")
    failures = page.setdefault("generation_failures", [])
    if route_blocked(page, route):
        raise ValueError("Route already blocked; change isolation method")
    if any(f["evidence"] == evidence for f in failures):
        raise ValueError("Failure evidence already recorded")
    failures.append({"route": route, "kind": kind, "evidence": evidence,
                     "request_snapshot": page["request_snapshot"]})


def validate_targets(spec_path, spec, root):
    inputs = {spec_path.resolve()}
    inputs.update(relative_file(spec_path.parent, e["preserve_asset"]["file"])
                  for s in spec["slides"] for e in s["elements"] if "preserve_asset" in e)
    inputs.update(relative_file(spec_path.parent, name) for name in spec["style"].get("tokens", {}).get("reference_images", []))
    for slide in spec["slides"]:
        target = relative_file(spec_path.parent, slide["image_file"])
        if not slide.get("image_origin") and (
                target in inputs or target.is_relative_to(root) or target.suffix.lower() != ".png"):
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
        if slide.get("image_origin"):
            provided_image(spec_path, slide, page)
            continue
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


def validate_generation_record(value, packet, request_hash, source_hash, slide_id, *, legacy_route=None):
    """Require actual call/result locators; this checks bindings, not provider authenticity."""
    required = {"version", "slide_id", "request_sha256", "source_sha256", "backend", "model", "result_ref"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Generation record requires version, slide_id, request_sha256, source_sha256, backend, model and result_ref")
    if not isinstance(packet, dict) or not isinstance(packet.get("slide"), dict):
        raise TypeError("Generation evidence requires a retained independent page request")
    route = packet.get("route")
    # v2.27 stored the route in sealed state, not in the request packet itself.
    # Never apply this compatibility rule to a partial or altered modern packet.
    if not any(key in packet for key in ("route", "request_id", "contract_sha256")):
        route = legacy_route
    if (value["version"] != "1.0" or value["slide_id"] != slide_id
            or value["request_sha256"] != request_hash or value["source_sha256"] != source_hash
            or packet["slide"].get("id") != slide_id or route not in ROUTES):
        raise ValueError("Generation record differs from the independent request or original source")
    if any(not isinstance(value[key], str) or not value[key].strip() for key in ("backend", "result_ref")):
        raise ValueError("Record the actual image tool/backend and call/result locator")
    if value["model"] is not None and (not isinstance(value["model"], str) or not value["model"].strip()):
        raise ValueError("Model must be its actual name, or null when the host does not expose it")


def verified_generation(root, page, slide_id):
    if not page.get("generation_snapshot") or not page.get("generation_request_snapshot"):
        raise ValueError("Missing generation call evidence; record the actual request and result before approval or export")
    evidence_path = relative_file(root, page["generation_snapshot"])
    request_path = relative_file(root, page["generation_request_snapshot"])
    for path in (evidence_path, request_path):
        if not path.is_file() or digest(path.read_bytes()) != path.name[:64]:
            raise ValueError("Generation evidence snapshot changed")
    validate_generation_record(read_json(evidence_path), read_json(request_path), digest(request_path.read_bytes()),
                               page.get("source_sha256"), slide_id,
                               legacy_route=page.get("generation_request_route"))


def missing_historical_request():
    return ValueError(
        "This retained original has no matching historical request. Restore its actual request and call evidence "
        "from a trusted backup, or retain this workspace and copy the Page Spec into a separate new project "
        "directory with independent image paths, then request and generate a NEW original. "
        "Never bind a newly prepared request to this old image."
    )


def request_for_record(root, page, source_hash, value, slide_id):
    """Find the current request, or the unchanged request of a retained original."""
    if not isinstance(value, dict):
        raise TypeError("Generation record must be an object")
    candidates = (page, *reversed(page.get("history", [])))
    retained = [p for p in candidates if p.get("source_sha256") == source_hash and p.get("source_snapshot")]
    for candidate in candidates:
        if candidate is not page and candidate not in retained:
            continue
        reference = candidate.get("request_snapshot")
        if not reference:
            continue
        request = relative_file(root, reference)
        if request.name[:64] != value.get("request_sha256"):
            continue
        raw_request = request.read_bytes()
        request_hash = digest(raw_request)
        if request_hash != request.name[:64]:
            raise ValueError("Retained generation request changed")
        packet = json.loads(raw_request.decode("utf-8-sig"))
        legacy = isinstance(packet, dict) and not any(
            key in packet for key in ("route", "request_id", "contract_sha256"))
        route = candidate.get("request_route")
        if legacy:
            # An old route is acceptable only alongside the source already bound
            # to this request in sealed state/history; no fresh call is invented.
            if candidate not in retained:
                continue
            original = relative_file(root, candidate["source_snapshot"])
            if digest(original.read_bytes()) != source_hash:
                raise ValueError("Retained original changed")
        elif candidate is page and route_blocked(page, route):
            raise ValueError("Generation route is blocked; prepare a request using an available alternative")
        validate_generation_record(value, packet, request_hash, source_hash, slide_id, legacy_route=route)
        return reference, route if legacy else packet["route"]
    if retained:
        raise missing_historical_request()
    if not page.get("request_snapshot"):
        raise ValueError("Prepare an independent request before recording a generated original")
    raise ValueError("Generation record differs from the independent request or original source")


def source_evidence(root, page, slide, raw, record):
    source_hash = digest(raw)
    if record is not None:
        evidence = Path(record).read_bytes()
        value = json.loads(evidence.decode("utf-8-sig"))
        reference, route = request_for_record(root, page, source_hash, value, slide["id"])
        return {"generation_snapshot": store(root, evidence, ".generation.json"),
                "generation_request_snapshot": reference, "generation_request_route": route}
    # Exact retained originals may be recomposited for authorized local corrections.
    # Their existing call record stays bound to the original request and bytes.
    for previous in (page, *reversed(page.get("history", []))):
        if previous.get("source_sha256") == source_hash and previous.get("generation_snapshot"):
            verified_generation(root, previous, slide["id"])
            return {key: previous[key] for key in ("generation_snapshot", "generation_request_snapshot", "generation_request_route")
                    if key in previous}
    if any(previous.get("source_sha256") == source_hash and previous.get("source_snapshot")
           and not previous.get("request_snapshot") for previous in (page, *page.get("history", []))):
        raise missing_historical_request()
    raise ValueError("New generated originals require --generation-record with actual call evidence and a prepared request")


def approved_image_hashes(spec_path, spec):
    """Read-only export gate for current production and explicitly provided images."""
    root = workspace(spec_path)
    managed = (root / "state.json").is_file()
    required = managed or spec.get("content_policy") == WORKFLOW_POLICY
    state = current(spec_path, spec, root, persist=False) if managed else None
    hashes = {}
    for slide in spec["slides"]:
        target = relative_file(spec_path.parent, slide["image_file"])
        actual = digest(target.read_bytes())
        origin = slide.get("image_origin")
        if origin:
            provided_image(spec_path, slide, state["pages"][slide["id"]] if state else {})
        elif required:
            page = state["pages"][slide["id"]] if state else {}
            if page.get("status") != "approved" or not page.get("review_snapshot"):
                raise ValueError(f"Missing current production approval for {slide['id']}; existing user images need an explicit image_origin")
            verified_generation(root, page, slide["id"])
            review = read_json(relative_file(root, page["review_snapshot"]))
            if (actual != page.get("image_sha256") or review.get("image_sha256") != actual
                    or review.get("contract_sha256") != page["contract_sha256"] or review.get("id") != slide["id"]):
                raise ValueError(f"Approved image or review changed for {slide['id']}; review the current image again")
        hashes[slide["id"]] = actual
    return hashes


def compose(spec_path, spec, root, state, slide, source, allow_upscale, generation_record=None):
    started = time.monotonic()
    page = state["pages"][slide["id"]]
    if slide.get("image_origin"):
        raise ValueError("Provided images use their explicit import path; new generation must remove image_origin")
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
    provenance = source_evidence(root, page, slide, raw, generation_record)
    if page.get("source_sha256") == digest(raw) and page["status"] != "pending":
        changed = any(page.get(key) != value for key, value in provenance.items())
        if changed:
            old = {key: value for key, value in page.items() if key != "history"}
            page["history"] = [*page.get("history", []), old]
            page["status"] = "generated"
            page.pop("review_snapshot", None)
        page.update(provenance)
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
                 "compose_seconds": time.monotonic() - started, **provenance})
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


def accept(spec_path, slide, root, page, record, *, policy=None):
    if page["status"] == "pending":
        raise ValueError("Compose the page before review")
    verified_generation(root, page, slide["id"])
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
    if not isinstance(text, str) or any(not text_present(t, text) for t in visible_text(slide, policy=policy)):
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


def execute(spec_path, action, *, slide_id=None, source=None, allow_upscale=False, record=None, element_id=None, region=None,
            route=None, failure_kind=None, evidence=None, generation_record=None):
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
        elif action == "request":
            request_page(spec, selected, root, state, route)
        elif action == "failure":
            record_failure(state["pages"][slide_id], route, failure_kind, evidence)
        elif action == "compose":
            if source is None:
                raise ValueError("compose requires --source")
            compose(spec_path, spec, root, state, selected, Path(source), allow_upscale, generation_record)
        elif action == "review-init":
            if record is None or Path(record).exists():
                raise ValueError("Provide a new --record path; retain previous reviews")
            if Path(record).resolve() in {spec_path, *[relative_file(spec_path.parent, s["image_file"]) for s in spec["slides"]]} or Path(record).resolve().is_relative_to(root):
                raise ValueError("Review record must be independent of managed outputs")
            save(Path(record), review_template(selected, state["pages"][slide_id]))
        elif action == "accept":
            if record is None:
                raise ValueError("accept requires --record")
            accept(spec_path, selected, root, state["pages"][slide_id], Path(record), policy=spec.get("content_policy"))
        elif action not in ("prepare", "status"):
            raise ValueError("Unknown production action")
        commit(spec_path, spec, root, state)
        return {"state": str(root / "state.json"), "summary": str(root / "status.md"),
                "pages": {key: {k: v for k, v in page.items() if k != "history"} for key, page in state["pages"].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "status", "request", "failure", "compose", "review-init", "accept", "region"))
    parser.add_argument("page_spec", type=Path)
    parser.add_argument("--slide")
    parser.add_argument("--route", choices=ROUTES)
    parser.add_argument("--failure-kind", choices=FAILURE_KINDS)
    parser.add_argument("--evidence", help="Actual failed tool call or result evidence; never fabricate")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--generation-record", type=Path, help="Actual tool/model/result evidence bound to this request and original image")
    parser.add_argument("--allow-upscale", action="store_true")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--element")
    parser.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    args = parser.parse_args()
    try:
        result = execute(args.page_spec, args.action, slide_id=args.slide, source=args.source,
                         allow_upscale=args.allow_upscale, record=args.record, element_id=args.element, region=args.region,
                         route=args.route, failure_kind=args.failure_kind, evidence=args.evidence, generation_record=args.generation_record)
    except (ValueError, TypeError, OSError) as error:
        parser.exit(2, f"produce: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
