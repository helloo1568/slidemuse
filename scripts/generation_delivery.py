"""Guarded generation contracts, image review, and lossless image-deck assembly."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import runpy
import tempfile
from pathlib import Path

from audit_page_content import text_present
from content_density import prompt_elements, validate_content, visible_text
from json_io import read_json
from PIL import Image, ImageOps
from pptx import Presentation
from pptx.util import Inches
from speaker_notes import canonical_notes, read_notes

CONTRACT = "slidemuse-content.json"
REVIEW = "content-review.json"
CONTENT_CHECKS = ("evidence_accuracy", "readability", "density", "visual_relationships")
CHECKS = (*CONTENT_CHECKS, "style_consistency")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inside(root, value):
    root = root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes generation deck: {value}")
    return path


def prepare_spec(spec):
    """Preserve exact approved content inside every upstream prompt."""
    spec = copy.deepcopy(spec)
    if not isinstance(spec.get("slides"), list) or not spec["slides"]:
        raise ValueError("Generation spec requires slides")
    if "canvas" in spec:
        canvas = spec["canvas"]
        if (not isinstance(canvas, dict) or set(canvas) != {"width", "height"}
                or any(type(value) is not int or value <= 0 for value in canvas.values())):
            raise ValueError("Generation canvas requires positive integer width and height")
    policy = spec.get("content_policy")
    for number, slide in enumerate(spec["slides"], 1):
        if not isinstance(slide, dict):
            raise TypeError("Generation slide must be an object")
        if "number" in slide and (type(slide["number"]) is not int or slide["number"] != number):
            raise ValueError("Generation pages must be consecutive and ordered")
        slide["number"] = number
        validate_content(slide, required=True)
        context = slide.get("local_context", {})
        approved_content = {
            key: slide[key] for key in ("id", "core_message", "key_points", "explanation", "boundary",
                                       "density", "display", "required_visible_values")
            if key in slide}
        if "elements" in slide:
            approved_content["elements"] = prompt_elements(slide["elements"])
        slide["local_context"] = {"original_context": context, "approved_content": approved_content,
                                  "required_visible_text": visible_text(slide, policy=policy)}
        slide["constraints"] = [*slide.get("constraints", []),
            ("Render ONE independent full-canvas slide, not thumbnails, preview grids or a contact sheet. "
             "Use the current page and the selected single-page style baseline. Preserve its palette, typography hierarchy, "
             "background texture, graphic language, whitespace and layout family. Additional calibrated samples cannot "
             "replace that baseline. Do not copy old wording, data, other style options or multi-page grids. "
             "Render every required_visible_text item exactly; keep evidence, explanation and boundaries visible. "
             "Use approved text and graphics to express semantic fields without adding redundant bullets. "
             "Review semantic coverage separately. Keep recorded sources and speaker_notes off the image. "
             "Do not replace substantive content with decoration or invent evidence.")]
    return spec


def from_page_spec(path):
    from style_reference import resolve_reference
    from validate_page_spec import load_page_spec
    spec, _ = load_page_spec(path, strict=True, content=True)
    for slide in spec["slides"]:
        if any("preserve_asset" in e for e in slide["elements"]):
            raise ValueError("Protected evidence requires the Page Spec production pipeline: use slidemuse.py produce prepare; do not regenerate its pixels through generate")
    result = {"deck_name": spec["title"], "language": "Chinese", "goal": spec["title"],
            "canvas": dict(spec["canvas"]),
            "selected_image_backend": "built-in image tool", "style": spec["style"],
            "content_version": spec["content_version"], "content_authorization": spec["content_authorization"],
            "slides": [{**s, "number": s["page_number"], "local_context": {"page_spec_sha256": sha(path)}}
                       for s in spec["slides"]]}
    if "content_policy" in spec:
        result["content_policy"] = spec["content_policy"]
    style = spec["style"]
    references = style.get("tokens", {}).get("reference_images", [])
    required = (style["decision"] in {"selected", "delegated"}
                and (spec.get("content_policy") == "1.1" or bool(references) or "generation_reference" in style))
    reference = resolve_reference(spec, path.parent, required=required)
    result["style"] = copy.deepcopy(style)
    # Keep the selection source in the audit contract. Only its declared
    # single-page crop (or explicit single-page reference) is an image input.
    result["style"].get("tokens", {}).pop("reference_images", None)
    result["style"].pop("generation_reference", None)
    if spec.get("content_policy") == "1.1":
        for page in result["slides"]:
            page.pop("generation_prompt", None)
    if reference is not None:
        result["style_reference"] = reference
        result["approved_style_reference"] = {
            "path": reference["path"], "sha256": reference["sha256"],
            "role": "selected single-page visual baseline; style only; preserve current approved content",
            "fidelity": "preserve palette, typography hierarchy, texture, graphic language, whitespace and layout family"}
    return result


def generation_helpers():
    helper = Path(__file__).resolve().parents[1] / "vendor/codex-ppt/skills/codex-ppt/scripts/slide_run_state.py"
    return runpy.run_path(str(helper))


def prepared_contract_files(deck, spec, jobs, prepared_files):
    """Build companion bytes before the helper commits any prepared output."""
    if len(jobs["slides"]) != len(spec["slides"]):
        raise ValueError("Prepared jobs do not match the approved content")
    reference = spec.get("style_reference")
    if reference != jobs.get("style_reference"):
        raise ValueError("Selected style reference differs between the specification and prepared jobs")
    validate_reference = generation_helpers()["validate_style_reference"]
    pages = []
    for entry, slide in zip(jobs["slides"], sorted(spec["slides"], key=lambda s: s.get("number", 0))):
        if entry["status"] == "accepted" and sha(inside(deck, entry["out"])) != entry["result"]["final_image_sha256"]:
            raise ValueError("Provided sample changed during preparation")
        job = json.loads(prepared_files[entry["job"]])
        if job.get("style_reference") != reference:
            raise ValueError("Every job must retain the selected style baseline")
        validate_reference(reference, job["input_images"])
        pages.append({"id": entry["slide_id"], "number": entry["number"],
                      "expected_text": visible_text(slide, policy=spec.get("content_policy")), "content": slide,
                      "input_images": job["input_images"],
                      "job_sha256": hashlib.sha256(prepared_files[entry["job"]]).hexdigest()})
    jobs["slidemuse_content_policy"] = "1.0"
    contract = {"version": "1.0", "pages": pages,
                "style_consistency_policy": "1.0", "style_reference": reference,
                **({"canvas": dict(spec["canvas"])} if "canvas" in spec else {}),
                "speaker_notes_policy": "explicit-only", "generation_evidence_policy": "1.0",
                "scope": "Declared content; evidence accuracy and readability require actual review."}
    files = {CONTRACT: (json.dumps(contract, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}
    if any("speaker_notes" in slide for slide in spec["slides"]):
        notes = "\n\n".join(f"## Slide {slide['number']}: {slide['title']}\n{slide.get('speaker_notes', '')}"
                             for slide in spec["slides"])
        files["speech.md"] = (notes + "\n").encode("utf-8")
    return files


def save_contract(deck, spec):
    """Compatibility entry point; keep the jobs and content snapshot together."""
    helpers = generation_helpers()
    with helpers["preparation_lock"](deck):
        jobs = read_json(deck / "slide_jobs.json")
        prompts = {entry["job"]: inside(deck, entry["job"]).read_bytes() for entry in jobs["slides"]}
        files = prepared_contract_files(deck, spec, jobs, prompts)
        files["slide_jobs.json"] = (json.dumps(jobs, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        helpers["commit_preparation"](deck, files)


def checked_images(deck, jobs, ratio=None):
    slides = jobs.get("slides", [])
    if not slides:
        raise ValueError("No generation jobs; prepare and record all pages first")
    if [s.get("number") for s in slides] != list(range(1, len(slides) + 1)):
        raise ValueError("Generation pages must be consecutive and ordered")
    images = []
    validate_generation = None
    validate_dispatch = None
    sample_method = None
    if jobs.get("generation_evidence_policy") == "1.0":
        helpers = generation_helpers()
        validate_generation = helpers["validate_generation_record"]
        validate_dispatch = helpers["validate_dispatch_inputs"]
        sample_method = helpers["sample_method"]
    for slide in slides:
        label = slide["slide_id"]
        if label != f"slide_{slide['number']:02d}":
            raise ValueError("Generation page ID differs from page number")
        if slide.get("status") not in ("recorded", "accepted"):
            raise ValueError(f"{label}: unfinished generation job ({slide.get('status')})")
        path = inside(deck, slide["out"])
        if not path.is_file() or (slide.get("result") or {}).get("final_image_sha256") != sha(path):
            raise ValueError(f"{label}: missing image or recorded image hash changed")
        if validate_generation:
            result = slide.get("result") or {}
            image_hash = sha(path)
            if result.get("selected_source_sha256") != image_hash:
                raise ValueError(f"{label}: final image differs from its recorded original")
            if result.get("source_kind") == "generated":
                request_hash = validate_dispatch(deck, slide)
                method = sample_method(jobs, read_json(inside(deck, slide["job"])))
                validate_generation(result.get("generation_record"), slide_id=label,
                                    request_sha256=request_hash, source_sha256=image_hash,
                                    backend=result.get("backend_used"), expected_model=method.get("model"))
            elif result.get("source_kind") == "provided" and result.get("accepted_sample") is True:
                if not isinstance(result.get("source_ref"), str) or not result["source_ref"].strip():
                    raise ValueError(f"{label}: provided sample requires its actual source reference")
            else:
                raise ValueError(f"{label}: missing generation evidence or declared provided sample")
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = ImageOps.exif_transpose(im).size
        canvas = jobs.get("canvas")
        if canvas is not None:
            if (not isinstance(canvas, dict) or set(canvas) != {"width", "height"}
                    or any(type(value) is not int or value <= 0 for value in canvas.values())):
                raise ValueError("Generation canvas requires positive integer width and height")
            if w < canvas["width"] or h < canvas["height"]:
                raise ValueError(f"{label}: image resolution {w}x{h} is below approved canvas "
                                 f"{canvas['width']}x{canvas['height']}; do not silently upscale")
        if ratio and abs(w - h * ratio) > max(1, ratio) + 1e-6:
            raise ValueError(f"{label}: image aspect ratio differs from export")
        images.append(path)
    actual = {p.resolve() for p in (deck / "origin_image").iterdir()
              if p.is_file() and re.fullmatch(r"slide_\d+\.(png|jpe?g|gif|bmp)", p.name, re.IGNORECASE)}
    if actual != set(images):
        raise ValueError("Missing, extra or duplicate final slide images")
    return images


def check_contract(deck, jobs):
    contract = read_json(deck / CONTRACT)
    if (contract.get("generation_evidence_policy") == "1.0"
            and jobs.get("generation_evidence_policy") != "1.0"):
        raise ValueError("Generation evidence policy changed; retain the current source records")
    pages = contract.get("pages", [])
    if contract.get("canvas") != jobs.get("canvas"):
        raise ValueError("Generation canvas differs from the approved content contract")
    if contract.get("style_consistency_policy") == "1.0":
        if contract.get("style_reference") != jobs.get("style_reference"):
            raise ValueError("Selected style baseline differs from the approved contract")
        validate_reference = generation_helpers()["validate_style_reference"]
        validate_reference(contract.get("style_reference"))
    if [p["id"] for p in pages] != [s["slide_id"] for s in jobs["slides"]]:
        raise ValueError("Content contract page order differs from jobs")
    for page, slide in zip(pages, jobs["slides"]):
        if page["job_sha256"] != sha(inside(deck, slide["job"])):
            raise ValueError(f"{page['id']}: prompt changed; refresh approved content and review")
        if contract.get("style_consistency_policy") == "1.0":
            job = read_json(inside(deck, slide["job"]))
            if (job.get("style_reference") != contract.get("style_reference")
                    or job.get("input_images") != page.get("input_images")
                    or slide.get("input_images") != page.get("input_images")):
                raise ValueError(f"{page['id']}: selected style or actual image inputs changed")
            validate_reference(job.get("style_reference"), job.get("input_images", []))
    return contract


def style_identity(reference):
    return {key: reference[key] for key in ("sha256", "source_sha256")} if reference is not None else None


def review(deck, record, initialize=False, *, _locked=False):
    if not _locked:
        with generation_helpers()["preparation_lock"](deck):
            return review(deck, record, initialize, _locked=True)
    jobs = read_json(deck / "slide_jobs.json")
    images = checked_images(deck, jobs)
    contract = check_contract(deck, jobs)
    style_required = contract.get("style_consistency_policy") == "1.0"
    reference = style_identity(contract.get("style_reference"))
    if initialize:
        if record.exists():
            raise ValueError("Review record already exists; retain it and choose a new path")
        write(record, {"version": "1.0", "contract_sha256": sha(deck / CONTRACT), "slides": [
            {"id": p["id"], "image_sha256": sha(image), "observed_text": "", "notes": "",
             **({"style_reference": reference} if style_required else {}),
             "checks": {**dict.fromkeys(CONTENT_CHECKS, "pending"),
                        **({"style_consistency": {"status": "pending", "notes": "", "targets": []}}
                           if style_required else {})}} for p, image in zip(contract["pages"], images)]})
        return {"status": "awaiting_review", "record": str(record)}
    data = read_json(record)
    if data.get("version") != "1.0" or data.get("contract_sha256") != sha(deck / CONTRACT):
        raise ValueError("Stale or unsupported content review")
    if [r.get("id") for r in data.get("slides", [])] != [p["id"] for p in contract["pages"]]:
        raise ValueError("Review must cover every page once, in order")
    findings = []
    for page, image, item in zip(contract["pages"], images, data["slides"]):
        if item.get("image_sha256") != sha(image):
            raise ValueError(f"{page['id']}: stale image review")
        text = item.get("observed_text", "")
        if not isinstance(text, str):
            raise TypeError("observed_text must be a transcription string")
        missing = [s for s in page["expected_text"] if not text_present(s, text)]
        checks = item.get("checks", {})
        passed = all(checks.get(c) == "pass" for c in CONTENT_CHECKS)
        if style_required:
            if "style_reference" not in item or item["style_reference"] != reference:
                raise ValueError(f"{page['id']}: style review must bind the selected source and reference image hashes")
            style_check = checks.get("style_consistency")
            passed = passed and (isinstance(style_check, dict) and style_check.get("status") == "pass"
                                 and isinstance(style_check.get("notes"), str) and bool(style_check["notes"].strip())
                                 and style_check.get("targets") == ["page"])
        if missing or not passed or not str(item.get("notes", "")).strip():
            findings.append({"id": page["id"], "missing_text": missing, "checks": checks})
    return {"status": "pass" if not findings else "incomplete_or_failed", "findings": findings,
            "style_review": "checked" if style_required else "legacy_not_checked",
            "scope": "Checks recorded content observations and any required style observations; does not OCR, authenticate evidence or automatically judge visual similarity."}


def assemble(argv, vendor_script):
    parser = argparse.ArgumentParser(description="Assemble recorded, unchanged images; retain exact source media.")
    parser.add_argument("base_dir", type=Path)
    parser.add_argument("output")
    parser.add_argument("--aspect-ratio", "--ar", choices=("16:9", "4:3"), default="16:9")
    args = parser.parse_args(argv)
    name = args.output if args.output.lower().endswith(".pptx") else args.output + ".pptx"
    if Path(name).name != name or any(c in name for c in ("/", "\\")):
        raise ValueError("Output must be a PPTX filename, not a path")
    deck = inside(args.base_dir, Path(name).stem)
    if not (deck / "slide_jobs.json").is_file():
        raise ValueError("Missing slide_jobs.json; prepare and record every page before assembly")
    with generation_helpers()["preparation_lock"](deck):
        jobs = read_json(deck / "slide_jobs.json")
        ratio = 16 / 9 if args.aspect_ratio == "16:9" else 4 / 3
        images = checked_images(deck, jobs, ratio)
        if jobs.get("slidemuse_content_policy") == "1.0" and not (deck / CONTRACT).is_file():
            raise ValueError("Current generation job is missing its content contract")
        if (deck / CONTRACT).exists():
            report = review(deck, deck / REVIEW, _locked=True)
            if report["status"] != "pass":
                raise ValueError("Content review incomplete or failed; run generate review and inspect findings")
        contract = read_json(deck / CONTRACT) if (deck / CONTRACT).exists() else {}
        if contract.get("speaker_notes_policy") == "explicit-only":
            notes = {i: canonical_notes(p["content"].get("speaker_notes", ""))
                     for i, p in enumerate(contract["pages"], 1)}
        else:
            notes = runpy.run_path(str(vendor_script))["load_speaker_notes"](str(deck))
        before = [sha(p) for p in images]
        embedded_hashes = []
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(10), Inches(10 / ratio)
        for i, path in enumerate(images, 1):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != before[i - 1]:
                raise ValueError("Source image changed during assembly")
            media = raw
            with Image.open(io.BytesIO(raw)) as image:
                if image.getexif().get(274, 1) in range(2, 9):
                    normalized = io.BytesIO()
                    transposed = ImageOps.exif_transpose(image)
                    if transposed.mode == "CMYK":
                        transposed = transposed.convert("RGB")
                    transposed.save(normalized, format="PNG")
                    media = normalized.getvalue()
            embedded_hashes.append(hashlib.sha256(media).hexdigest())
            picture = slide.shapes.add_picture(io.BytesIO(media), 0, 0, width=prs.slide_width, height=prs.slide_height)
            if hashlib.sha256(picture.image.blob).hexdigest() != embedded_hashes[-1]:
                raise ValueError("Image embedding changed source media")
            if notes.get(i, ""):
                slide.notes_slide.notes_text_frame.text = notes[i]
        target = deck / name
        fd, temporary = tempfile.mkstemp(dir=deck, suffix=".pptx")
        os.close(fd)
        try:
            prs.save(temporary)
            reopened = Presentation(temporary)
            if len(reopened.slides) != len(images) or before != [sha(p) for p in images]:
                raise ValueError("Images changed during assembly")
            for i, slide in enumerate(reopened.slides, 1):
                if (hashlib.sha256(slide.shapes[0].image.blob).hexdigest() != embedded_hashes[i - 1]
                        or read_notes(slide) != canonical_notes(notes.get(i, ""))):
                    raise ValueError("Exported media/notes differ from input")
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    print(json.dumps({"output": str(target), "slides": len(images),
                      "content_review": "pass" if (deck / CONTRACT).exists() else "legacy_not_checked",
                      "visual_review": "Render the actual PPTX in Office before delivery."}, ensure_ascii=True))
    return 0
