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
from PIL import Image, ImageChops, ImageOps
from preserved_assets import expected_patch, relative_file, validate_preserved_assets
from record_work import locked_log
from style_reference import resolve_reference
from validate_page_spec import load_page_spec

CHECKS = ("semantic_coverage", "source_accuracy", "readability", "density", "visual_relationships")
STYLE_CHECK = "style_consistency"
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


def needs_style_reference(spec):
    """New selections and old selections with visual inputs need an explicit baseline."""
    style = spec["style"]
    return style["decision"] in {"selected", "delegated"} and bool(
        spec.get("content_policy") == WORKFLOW_POLICY or style.get("generation_reference")
        or style.get("tokens", {}).get("reference_images"))


def reference_identity(reference):
    return {key: reference.get(key) for key in ("kind", "sha256", "source_sha256", "box", "option", "choice")}


def retained_style_reference(root, reference):
    """Archive the actual single-page input separately from its selection evidence."""
    binding = reference_identity(reference)
    for path_key, hash_key, snapshot_key, suffix in (
        ("path", "sha256", "reference_snapshot", ".style-reference"),
        ("source_path", "source_sha256", "source_snapshot", ".style-source"),
    ):
        path = Path(reference[path_key])
        raw = path.read_bytes()
        if digest(raw) != reference[hash_key]:
            raise ValueError("Style reference changed while preparing its production record")
        binding[snapshot_key] = store(root, raw, suffix + path.suffix.lower())
    return binding


def verify_style_reference(root, binding):
    if not isinstance(binding, dict):
        raise TypeError("Production style reference must retain its identity and snapshots")
    for snapshot_key, hash_key in (("reference_snapshot", "sha256"), ("source_snapshot", "source_sha256")):
        if not isinstance(binding.get(snapshot_key), str) or not isinstance(binding.get(hash_key), str):
            raise TypeError("Production style reference must retain its identity and snapshots")
        path = relative_file(root, binding[snapshot_key])
        if (not path.is_file() or path.name[:64] != binding[hash_key]
                or digest(path.read_bytes()) != binding[hash_key]):
            raise ValueError("Production style reference snapshot changed")


def bind_current_style(spec_path, spec, root, page):
    """New production/review operations use today's selected reference, never a substitute page."""
    reference = resolve_reference(spec, spec_path.parent, required=needs_style_reference(spec))
    previous = page.get("style_reference")
    if reference is None:
        if previous is not None:
            raise ValueError("Production style reference no longer matches the current selection")
        return
    if previous is not None:
        verify_style_reference(root, previous)
        if reference_identity(previous) != reference_identity(reference):
            raise ValueError("Production style reference no longer matches the current selection")
    else:
        binding = retained_style_reference(root, reference)
        if page["status"] == "approved":
            old = {key: value for key, value in page.items() if key != "history"}
            page["history"] = [*page.get("history", []), old]
            page["status"] = "generated"
            page.pop("review_snapshot", None)
        page["style_reference"] = binding


def validate_style_review(spec_path, spec, root, page, review, generation_packet):
    """Check recorded comparison bindings, without claiming to measure visual similarity."""
    binding = page.get("style_reference")
    if binding is None:
        # Historical approvals remain readable; they are not retroactively style-calibrated.
        if (review.get("style_reference") is not None or generation_packet.get("style_reference") is not None
                or spec["style"].get("generation_reference") is not None):
            raise ValueError("Selected style reference has no corresponding production review binding")
        return
    verify_style_reference(root, binding)
    reference = resolve_reference(spec, spec_path.parent, required=needs_style_reference(spec))
    if reference is None or reference_identity(binding) != reference_identity(reference):
        raise ValueError("Production style reference no longer matches the current selection")
    if review.get("style_reference") != binding:
        raise ValueError("Review style reference differs from the current selected reference")
    check = review.get("checks", {}).get(STYLE_CHECK, {})
    if (not isinstance(check, dict) or check.get("status") != "pass"
            or not isinstance(check.get("notes"), str) or not check["notes"].strip()
            or check.get("targets") != ["page"]):
        raise ValueError("Review style_consistency needs an actual pass, comparison observations and page target")


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
    # Never attach an overview grid. request_page supplies the selected independent reference.
    style.get("tokens", {}).pop("reference_images", None)
    style.pop("generation_reference", None)
    content["elements"] = prompt_elements(slide["elements"])
    return {"instructions": (
        "Generate ONE independent full-canvas slide using the actual authorized image model. "
        "Never output a contact sheet, thumbnails, multiple slides, or a preview grid. "
        "Use only this page packet and its explicitly selected single-page visual reference; ignore prior preview instructions. "
        "Attach the image in style_reference.reference_snapshot when present, never style_reference.source_snapshot. "
        "Preserve its palette, typography hierarchy, background and materials, graphic language, whitespace and layout family. "
        "Adapt the design to this page's confirmed content; never copy old reference text or data, or an overview grid. "
        "Preserve the confirmed style and visible text. "
        "Keep the reference's visual language without treating its exact composition as a fixed template. "
        "Respect explicitly approved layouts and compose for the role of the current page. "
        "Give the main message or evidence priority; use imagery only when it reinforces that message. "
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


def provided_image(spec_path, slide, page, root=None):
    if any(previous.get("source_snapshot") or previous.get("generation_snapshot")
           for previous in (page, *page.get("history", []))):
        raise ValueError("A generated page cannot bypass production review by changing its origin to provided")
    target = relative_file(spec_path.parent, slide["image_file"])
    if not target.exists() and root is not None:
        # A removed provided page may return after a self-contained draft move.
        # Only restore missing projections; changed user files must still fail.
        for previous in (page, *reversed(page.get("history", []))):
            if (previous.get("source_kind") == "provided" and previous.get("image_snapshot")
                    and previous.get("image_sha256") == slide["image_origin"]["sha256"]):
                target = relative_file(root, previous["image_snapshot"])
                break
    data = target.read_bytes()
    if digest(data) != slide["image_origin"]["sha256"]:
        raise ValueError(f"Provided image changed since its recorded approval: {slide['id']}")
    return data


def verify_snapshots(root, value):
    """Validate retained files before reusing an active or restored page."""
    if isinstance(value, list):
        for item in value:
            verify_snapshots(root, item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_snapshot") and item is not None:
                stored = relative_file(root, item)
                hash_key = {"image_snapshot": "image_sha256", "source_snapshot": "source_sha256", "reference_snapshot": "sha256",
                            "derived_input_snapshot": "derived_input_sha256", "correction_snapshot": "correction_sha256"}.get(key)
                expected = value.get(hash_key) if hash_key else stored.name[:64]
                if not stored.is_file() or digest(stored.read_bytes()) != expected:
                    raise ValueError("Committed production snapshot changed")
            else:
                verify_snapshots(root, item)


def current(spec_path, spec, root, *, persist=True):
    state_path = root / "state.json"
    state = read_json(state_path) if state_path.exists() else {"version": "1.0", "pages": {}}
    if (state.get("version") != "1.0" or not isinstance(state.get("pages"), dict)
            or not isinstance(state.get("archived_pages", {}), dict)):
        raise ValueError("Unsupported production state")
    if state_path.exists() and state.get("state_sha256") != seal({k: v for k, v in state.items() if k != "state_sha256"}):
        raise ValueError("Production state changed; retain it for recovery")
    archived = state.get("archived_pages", {}).copy()
    if set(archived) & set(state["pages"]):
        raise ValueError("Production page cannot be both active and archived")
    active_ids = {slide["id"] for slide in spec["slides"]}
    archived.update({key: page for key, page in state["pages"].items() if key not in active_ids})
    pages = {}
    for slide in spec["slides"]:
        contract = fingerprint(spec, slide, spec_path.parent)
        restored = archived.pop(slide["id"], {})
        old = state["pages"].get(slide["id"], restored)
        if old:
            verify_snapshots(root, old)
        if old.get("contract_sha256") == contract:
            pages[slide["id"]] = old
        else:
            snapshot = store(root, encoded({"canvas": spec["canvas"], "style": spec["style"], "slide": slide}), ".json") if persist else None
            pages[slide["id"]] = {"contract_sha256": contract, "intent_snapshot": snapshot,
                                  "status": "pending", "history": [*old.get("history", []), *([{k: v for k, v in old.items() if k != "history"}] if old else [])]}
        if slide.get("image_origin"):
            data = provided_image(spec_path, slide, pages[slide["id"]], root)
            pages[slide["id"]].update(source_kind="provided", status=slide["image_status"], image_sha256=digest(data))
            if persist:
                suffix = Path(slide["image_file"]).suffix.lower()
                pages[slide["id"]]["image_snapshot"] = store(root, data, suffix)
        if persist:
            pages[slide["id"]]["prompt_snapshot"] = store(root, encoded(generation_input(spec, slide)), ".prompt.json")
    state["pages"] = pages
    state["archived_pages"] = archived
    return state


def route_blocked(page, route):
    failures = [f for f in page.get("generation_failures", []) if f["route"] == route]
    return len(failures) >= 2 and failures[-1]["kind"] == failures[-2]["kind"]


def request_page(spec_path, spec, slide, root, state, route):
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
    bind_current_style(spec_path, spec, root, page)
    page.pop("request_reference", None)
    if page.get("style_reference"):
        packet["style_reference"] = copy.deepcopy(page["style_reference"])
        page["request_reference"] = str(relative_file(root, page["style_reference"]["reference_snapshot"]))
    # Only old/text-only workflows may use another approved page as their primary anchor.
    candidates = [s for s in spec["slides"] if s["id"] != slide["id"]
                  and state["pages"][s["id"]]["status"] == "approved"]
    candidates.sort(key=lambda s: (s.get("role") == "cover", s["page_number"]))
    if not page.get("style_reference") and candidates:
        anchor = candidates[0]
        approved = state["pages"][anchor["id"]]
        if not anchor.get("image_origin"):
            verified_generation(root, approved, anchor["id"])
        reference = relative_file(root, approved["image_snapshot"])
        if digest(reference.read_bytes()) != approved["image_sha256"]:
            raise ValueError("Approved style anchor changed")
        page["request_reference"] = str(reference)
        packet["style_anchor"] = {"slide_id": anchor["id"], "image_snapshot": approved["image_snapshot"],
                                  "image_sha256": approved["image_sha256"],
                                  "use": "Preserve the design language and layout family; never copy old text or data"}
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
    reference = resolve_reference(spec, spec_path.parent)
    if reference:
        inputs.update((Path(reference["path"]), Path(reference["source_path"])))
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
            data = provided_image(spec_path, slide, page, root)
            target = relative_file(spec_path.parent, slide["image_file"])
            if not target.exists():
                atomic(target, data)
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
    packet = read_json(request_path)
    verify_snapshots(root, packet)
    if "style_reference" in packet:
        verify_style_reference(root, packet["style_reference"])
    validate_generation_record(read_json(evidence_path), packet, digest(request_path.read_bytes()),
                               page.get("source_sha256"), slide_id,
                               legacy_route=page.get("generation_request_route"))
    if page.get("derivation_snapshot"):
        derivation_path = relative_file(root, page["derivation_snapshot"])
        if not derivation_path.is_file() or digest(derivation_path.read_bytes()) != derivation_path.name[:64]:
            raise ValueError("Local correction record changed")
        derivation = read_json(derivation_path)
        expected = {"version": "1.0", "slide_id": slide_id, "contract_sha256": page["contract_sha256"],
                    "source_sha256": page.get("source_sha256"), "input_snapshot": page.get("derived_input_snapshot"),
                    "input_sha256": page.get("derived_input_sha256"), "correction_snapshot": page.get("correction_snapshot"),
                    "correction_sha256": page.get("correction_sha256"), "output_sha256": page.get("image_sha256")}
        if "derived_input_pixels" in page:
            expected.update(input_pixels=page["derived_input_pixels"], upscaled=page.get("upscaled"))
        if (not isinstance(derivation, dict) or any(derivation.get(key) != value for key, value in expected.items())
                or not isinstance(derivation.get("operation"), str) or not derivation["operation"].strip()):
            raise ValueError("Local correction differs from its retained input, original or output")
        for field in ("derived_input", "correction"):
            reference = page.get(field + "_snapshot")
            if not reference or digest(relative_file(root, reference).read_bytes()) != page.get(field + "_sha256"):
                raise ValueError("Local correction input changed")
    return packet


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
        verify_snapshots(root, packet)
        if "style_reference" in packet:
            verify_style_reference(root, packet["style_reference"])
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
            generation_packet = verified_generation(root, page, slide["id"])
            review = read_json(relative_file(root, page["review_snapshot"]))
            if (actual != page.get("image_sha256") or review.get("image_sha256") != actual
                    or review.get("contract_sha256") != page["contract_sha256"] or review.get("id") != slide["id"]):
                raise ValueError(f"Approved image or review changed for {slide['id']}; review the current image again")
            validate_style_review(spec_path, spec, root, page, review, generation_packet)
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
    for key in ("derivation_snapshot", "derived_input_snapshot", "derived_input_sha256", "derived_input_pixels",
                "correction_snapshot", "correction_sha256"):
        page.pop(key, None)
    page.update({"status": "generated", "source_snapshot": store(root, raw, ".source"),
                 "source_sha256": digest(raw), "source_pixels": original_size,
                 "final_pixels": list(size), "upscaled": upscaled, "protected_regions": regions,
                 "image_snapshot": store(root, data, ".png"), "image_sha256": digest(data),
                 "compose_seconds": time.monotonic() - started, **provenance})
    page.pop("review_snapshot", None)
    page["history"] = [*page.get("history", []), old]


def refine(spec_path, spec, root, state, slide, source, base_image, operation, allow_upscale=False):
    """Register a declared local correction without relabeling it as a model result."""
    if slide.get("image_origin"):
        raise ValueError("Local production corrections require a retained generated original")
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError("Describe the authorized local correction with --operation")
    target = relative_file(spec_path.parent, slide["image_file"])
    if source.resolve() == target or source.resolve().is_relative_to(root):
        raise ValueError("Keep the corrected image independent of the final image and managed snapshots")
    page = state["pages"][slide["id"]]
    input_hash = digest(base_image.read_bytes())
    retained = None
    for previous in (page, *reversed(page.get("history", []))):
        for kind in ("image", "source"):
            if previous.get(kind + "_sha256") == input_hash and previous.get(kind + "_snapshot"):
                verify_snapshots(root, previous)
                verified_generation(root, previous, slide["id"])
                retained = (previous, previous[kind + "_snapshot"], kind)
                break
        if retained:
            break
    if retained is None:
        raise ValueError("--base-image must match a retained, unchanged original or composed image of this page")
    previous, input_snapshot, input_kind = retained
    raw = source.read_bytes()
    with Image.open(io.BytesIO(raw)) as opened:
        if opened.format != "PNG":
            raise ValueError("Local corrections must be saved as lossless PNG")
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    size = (int(spec["canvas"]["width"]), int(spec["canvas"]["height"]))
    if image.size != size or image.getchannel("A").getextrema() != (255, 255):
        raise ValueError("Local correction must be opaque and match the current canvas pixel dimensions")
    with Image.open(relative_file(root, input_snapshot)) as opened:
        input_pixels = ImageOps.exif_transpose(opened).size
    with Image.open(relative_file(root, previous["source_snapshot"])) as opened:
        original_pixels = ImageOps.exif_transpose(opened).size
    enlarges = any(before < after for pixels in (input_pixels, original_pixels) for before, after in zip(pixels, size))
    prior_size = previous.get("final_pixels", [])
    already_allowed = (previous.get("upscaled") is True and len(prior_size) == 2
                       and all(before >= after for before, after in zip(prior_size, size)))
    if enlarges and not (allow_upscale or already_allowed):
        raise ValueError("Local correction enlarges retained pixels; explicitly use --allow-upscale and do not claim native resolution")
    upscaled = enlarges or (input_kind == "image" and previous.get("upscaled") is True)
    image = image.convert("RGB")
    regions = []
    for element in slide["elements"]:
        if "preserve_asset" in element:
            declaration = element["preserve_asset"]
            x, y, width, height = declaration["region"]
            patch = expected_patch(spec_path.parent, declaration)
            if ImageChops.difference(image.crop((x, y, x + width, y + height)), patch).getbbox() is not None:
                raise ValueError("Local correction changed protected evidence pixels")
            regions.append({"element_id": element["id"], "region": declaration["region"]})
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    correction_snapshot = store(root, raw, ".correction")
    derivation = {"version": "1.0", "slide_id": slide["id"], "contract_sha256": page["contract_sha256"],
                  "operation": operation.strip(), "source_sha256": previous["source_sha256"],
                  "input_snapshot": input_snapshot, "input_sha256": input_hash,
                  "input_pixels": list(input_pixels), "upscaled": upscaled,
                  "correction_snapshot": correction_snapshot, "correction_sha256": digest(raw),
                  "output_sha256": digest(data)}
    old = {key: value for key, value in page.items() if key != "history"}
    provenance = {key: previous[key] for key in ("source_snapshot", "source_sha256", "source_pixels", "generation_snapshot",
                                                "generation_request_snapshot", "generation_request_route") if key in previous}
    page.update({**provenance, "status": "generated", "image_snapshot": store(root, data, ".png"),
                 "image_sha256": digest(data), "source_pixels": list(original_pixels), "final_pixels": list(size), "upscaled": upscaled,
                 "protected_regions": regions, "derivation_snapshot": store(root, encoded(derivation), ".derivation.json"),
                 "derived_input_snapshot": input_snapshot, "derived_input_sha256": input_hash, "derived_input_pixels": list(input_pixels),
                 "correction_snapshot": correction_snapshot, "correction_sha256": digest(raw)})
    page.pop("review_snapshot", None)
    page["history"] = [*page.get("history", []), old]


def review_template(slide, page):
    if page["status"] == "pending":
        raise ValueError("Compose the page before requesting its review")
    value = {"version": "1.0", "id": slide["id"], "contract_sha256": page["contract_sha256"],
             "image_sha256": page["image_sha256"], "reviewer": "", "observed_text": "",
             "viewed_pixels": None, "checks": {name: {"status": "pending", "notes": "", "targets": []} for name in CHECKS},
             "design_review_guidance": {
                 "density": "At presentation scale, identify what the audience should notice first and which areas feel cramped or empty without purpose.",
                 "visual_relationships": "Check that imagery supports the message and the composition fits the page role rather than copying the visual reference layout by default.",
             },
             "protected_regions": page.get("protected_regions", []),
             "scope": "Actual visual observations and source comparison; hash/text matches do not prove truth or independence."}
    if page.get("style_reference"):
        value["style_reference"] = copy.deepcopy(page["style_reference"])
        value["checks"][STYLE_CHECK] = {"status": "pending", "notes": "", "targets": []}
        value["scope"] += (
            " Compare the current image with style_reference.reference_snapshot (paths relative to production state): "
            "palette, typography hierarchy, background/materials, graphics and imagery, whitespace and layout rhythm. "
            "source_snapshot retains the selected preview for provenance; never use an overview grid as the generation attachment.")
    return value


def accept(spec_path, spec, slide, root, page, record, *, policy=None):
    if page["status"] == "pending":
        raise ValueError("Compose the page before review")
    generation_packet = verified_generation(root, page, slide["id"])
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
    validate_style_review(spec_path, spec, root, page, value, generation_packet)
    # Compare the current projection too; never certify a substituted final PNG.
    target = relative_file(spec_path.parent, slide["image_file"])
    if not target.is_file() or digest(target.read_bytes()) != page["image_sha256"]:
        raise ValueError("Final image changed since composition")
    validate_preserved_assets(slide, spec_path.parent, True)
    page["review_snapshot"] = store(root, encoded(value), ".review.json")
    page["status"] = "approved"


def execute(spec_path, action, *, slide_id=None, source=None, allow_upscale=False, record=None, element_id=None, region=None,
            route=None, failure_kind=None, evidence=None, generation_record=None, base_image=None, operation=None):
    spec_path = Path(spec_path).resolve()
    root = workspace(spec_path)
    if action == "status":
        spec, _ = load_page_spec(spec_path, strict=True, content=True)
        state = current(spec_path, spec, root, persist=False)
        return {"state": str(root / "state.json"), "pages": state["pages"], "archived_pages": state["archived_pages"]}
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
            request_page(spec_path, spec, selected, root, state, route)
        elif action == "failure":
            record_failure(state["pages"][slide_id], route, failure_kind, evidence)
        elif action == "compose":
            if source is None:
                raise ValueError("compose requires --source")
            bind_current_style(spec_path, spec, root, state["pages"][slide_id])
            compose(spec_path, spec, root, state, selected, Path(source), allow_upscale, generation_record)
        elif action == "refine":
            if source is None or base_image is None:
                raise ValueError("refine requires --source and --base-image")
            bind_current_style(spec_path, spec, root, state["pages"][slide_id])
            refine(spec_path, spec, root, state, selected, Path(source), Path(base_image), operation, allow_upscale)
        elif action == "review-init":
            if record is None or Path(record).exists():
                raise ValueError("Provide a new --record path; retain previous reviews")
            if Path(record).resolve() in {spec_path, *[relative_file(spec_path.parent, s["image_file"]) for s in spec["slides"]]} or Path(record).resolve().is_relative_to(root):
                raise ValueError("Review record must be independent of managed outputs")
            page = state["pages"][slide_id]
            bind_current_style(spec_path, spec, root, page)
            template = review_template(selected, page)
            target = relative_file(spec_path.parent, selected["image_file"])
            if not target.is_file() or digest(target.read_bytes()) != page["image_sha256"]:
                raise ValueError("Final image changed since composition; register an independent correction with refine, or run prepare to restore the committed image")
            save(Path(record), template)
        elif action == "accept":
            if record is None:
                raise ValueError("accept requires --record")
            bind_current_style(spec_path, spec, root, state["pages"][slide_id])
            accept(spec_path, spec, selected, root, state["pages"][slide_id], Path(record), policy=spec.get("content_policy"))
        elif action not in ("prepare", "status"):
            raise ValueError("Unknown production action")
        commit(spec_path, spec, root, state)
        return {"state": str(root / "state.json"), "summary": str(root / "status.md"),
                "pages": {key: {k: v for k, v in page.items() if k != "history"} for key, page in state["pages"].items()},
                "archived_page_ids": sorted(state["archived_pages"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "status", "request", "failure", "compose", "refine", "review-init", "accept", "region"))
    parser.add_argument("page_spec", type=Path)
    parser.add_argument("--slide")
    parser.add_argument("--route", choices=ROUTES)
    parser.add_argument("--failure-kind", choices=FAILURE_KINDS)
    parser.add_argument("--evidence", help="Actual failed tool call or result evidence; never fabricate")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--base-image", type=Path, help="Retained original or composed image used as the local correction input")
    parser.add_argument("--operation", help="Actual authorized local correction; not a model invocation")
    parser.add_argument("--generation-record", type=Path, help="Actual tool/model/result evidence bound to this request and original image")
    parser.add_argument("--allow-upscale", action="store_true")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--element")
    parser.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    args = parser.parse_args()
    try:
        result = execute(args.page_spec, args.action, slide_id=args.slide, source=args.source,
                         allow_upscale=args.allow_upscale, record=args.record, element_id=args.element, region=args.region,
                         route=args.route, failure_kind=args.failure_kind, evidence=args.evidence, generation_record=args.generation_record,
                         base_image=args.base_image, operation=args.operation)
    except (ValueError, TypeError, OSError) as error:
        parser.exit(2, f"produce: {error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
