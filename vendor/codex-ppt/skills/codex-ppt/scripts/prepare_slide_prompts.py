#!/usr/bin/env python3
"""Prepare per-slide image generation jobs for codex-ppt.

This script is deterministic. It does not call an image model. It turns a
structured deck spec into one self-contained JSON job file per slide.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image, ImageOps

from slide_run_state import (
    DEFAULT_MAX_CONCURRENT_SLIDES,
    now_iso,
    rel_to_deck,
    commit_preparation,
    preparation_lock,
    read_json,
    sha256_file,
    update_jobs_run_status,
    validate_dispatch_inputs,
    validate_generation_record,
    sample_method,
    validate_style_reference,
)


def _die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        _die(f"Spec file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON in {path}: {exc}")
    if not isinstance(data, dict):
        _die("Deck spec must be a JSON object.")
    return data


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> List[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _parse_markdown_image(value: str) -> Optional[Dict[str, str]]:
    match = _MARKDOWN_IMAGE_RE.search(value)
    if not match:
        return None
    alt_text = match.group(1).strip()
    path = match.group(2).strip()
    description = value[: match.start()].strip(" \t\n\r:-;")
    role_parts = [part for part in [description, alt_text] if part]
    return {
        "path": path,
        "role": " — ".join(role_parts) if role_parts else "reference image",
    }


def _resolve_image_path(path: str, *, base_dir: Path) -> str:
    path = path.strip()
    if not path:
        return path
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", path):
        return path
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / candidate).resolve())


def _normalize_input_image(entry: Any, *, slide_number: int, image_index: int, base_dir: Path) -> Dict[str, Any]:
    if isinstance(entry, dict):
        image = dict(entry)
        raw_path = image.get("path") or image.get("attachment") or image.get("markdown")
        if isinstance(raw_path, str):
            parsed = _parse_markdown_image(raw_path)
            if parsed:
                image["path"] = parsed["path"]
                image.setdefault("role", parsed["role"])
        if isinstance(image.get("path"), str):
            image["path"] = _resolve_image_path(image["path"], base_dir=base_dir)
        return image
    if isinstance(entry, str):
        parsed = _parse_markdown_image(entry)
        if not parsed:
            _die(
                f"Slide {slide_number}: required_images entry {image_index} must be an "
                "object or a Markdown image reference like ![alt](path)."
            )
        lowered = entry.lower()
        fidelity = ""
        if "strict input asset" in lowered:
            fidelity = "strict input asset; preserve the supplied image content"
        return {
            "path": _resolve_image_path(parsed["path"], base_dir=base_dir),
            "role": parsed["role"],
            "fidelity": fidelity,
        }
    _die(f"Slide {slide_number}: required_images entry {image_index} has unsupported type.")


def _slide_images(slide: Dict[str, Any], *, slide_number: int, base_dir: Path) -> List[Dict[str, Any]]:
    images: List[Dict[str, Any]] = []
    for index, image in enumerate(_as_list(slide.get("required_images") or slide.get("input_images")), start=1):
        images.append(_normalize_input_image(image, slide_number=slide_number, image_index=index, base_dir=base_dir))
    return images


def _sample_generation_method(spec: Dict[str, Any], *, base_dir: Path) -> Optional[Dict[str, Any]]:
    method = spec.get("sample_generation_method") or spec.get("image_generation_method")
    if method is None:
        return None
    if not isinstance(method, dict):
        _die("sample_generation_method must be an object when present.")
    method = dict(method)
    for key in ("approved_sample_path", "sample_slide_path", "sample_output_path"):
        if isinstance(method.get(key), str):
            method[key] = _resolve_image_path(method[key], base_dir=base_dir)
    return method


def _bind_style_reference(spec: Dict[str, Any], *, base_dir: Path) -> Optional[Dict[str, Any]]:
    """Bind native deck specifications to the same immutable baseline as Page Spec.

    Preparing a job stays offline. Remote baseline URLs must first be saved as
    a local, approved single-page image; a path alone cannot bind its pixels.
    """
    selected = spec.get("approved_style_reference")
    reference = spec.get("style_reference")
    if selected is None:
        validate_style_reference(reference)
        return None
    if not isinstance(selected, dict):
        raise ValueError("approved_style_reference must be an object when present")
    selected = dict(selected)
    value = selected.get("path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("approved_style_reference requires the approved single-page image path")
    candidate = Path(value.strip()).expanduser()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value.strip()) and not candidate.is_absolute():
        raise ValueError("Save the remote approved_style_reference as a local image before prepare; preparation does not download it")
    path = (base_dir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not path.is_file():
        raise ValueError(f"Missing approved style reference: {path}")
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if selected.get("sha256") is not None and selected["sha256"] != actual_hash:
        raise ValueError("Approved style reference SHA-256 differs from its actual image")
    with Image.open(io.BytesIO(raw)) as opened:
        opened.verify()
    with Image.open(io.BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
        width, height = image.size
    selected.update(path=str(path), sha256=actual_hash)
    if reference is None:
        style = spec.get("style", {})
        reference = {"kind": "single-page", "path": str(path), "sha256": actual_hash,
                     "source_path": str(path), "source_sha256": actual_hash,
                     "box": [0, 0, width, height], "option": style.get("option"),
                     "choice": style.get("choice", style.get("name"))}
        spec["style_reference"] = reference
    validate_style_reference(reference, [selected])
    spec["approved_style_reference"] = selected
    return selected


def _method_backend_label(method: Optional[Dict[str, Any]]) -> Optional[str]:
    if not method:
        return None
    for key in ("backend_used", "selected_backend", "backend", "tool_name"):
        value = method.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _format_block(title: str, value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, (dict, list)):
        body = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        body = str(value).strip()
    return f"## {title}\n{body}\n"


def _format_input_images(images: Iterable[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for idx, image in enumerate(images, start=1):
        path = str(image.get("path") or image.get("attachment") or "").strip()
        role = str(image.get("role") or "reference image").strip()
        fidelity = str(image.get("fidelity") or image.get("constraints") or "").strip()
        if not path:
            _die(f"Input image {idx} is missing path or attachment.")
        if fidelity:
            lines.append(f"- Image {idx}: {path} — {role}; {fidelity}")
        else:
            lines.append(f"- Image {idx}: {path} — {role}")
    return "\n".join(lines)


def _slide_number(slide: Dict[str, Any], fallback: int) -> int:
    raw = slide.get("number", fallback)
    try:
        number = int(raw)
    except (TypeError, ValueError):
        _die(f"Invalid slide number: {raw}")
    if number <= 0:
        _die(f"Slide number must be positive: {number}")
    return number


def _build_prompt(
    *,
    deck: Dict[str, Any],
    slide: Dict[str, Any],
    number: int,
    global_style_reference: Optional[Dict[str, Any]],
    base_dir: Path,
) -> str:
    title = str(slide.get("title") or f"Slide {number}").strip()
    style = deck.get("style", {})
    images: List[Dict[str, Any]] = []
    if global_style_reference:
        images.append(global_style_reference)
    images.extend(_slide_images(slide, slide_number=number, base_dir=base_dir))
    required_background = {
        key: value
        for key, value in {
            "deck_context": deck.get("deck_context"),
            "slide_local_context": slide.get("local_context"),
        }.items()
        if value not in (None, "", [], {})
    }

    canvas = deck.get("canvas", {"width": 1600, "height": 900})
    if not isinstance(canvas, dict):
        _die("canvas must declare positive width and height.")
    width, height = canvas.get("width"), canvas.get("height")
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v <= 0 for v in (width, height)):
        _die("canvas must declare positive finite width and height.")
    if float(width).is_integer() and float(height).is_integer():
        divisor = math.gcd(int(width), int(height))
        aspect = f"{int(width) // divisor}:{int(height) // divisor}"
    else:
        aspect = f"{width}:{height}"

    prompt_parts = [
        "# Codex PPT Slide Image Prompt\n",
        _format_block("Canvas", {
            "type": f"{aspect} full-slide PowerPoint image",
            "width": width,
            "height": height,
            "language": deck.get("language", "Chinese"),
            "slide_number": number,
            "render_slide_number": False,
        }),
        _format_block("Deck Goal", deck.get("goal")),
        _format_block("Required Background", required_background),
        _format_block("Global Style", style),
    ]

    if images:
        prompt_parts.append("## Input Images\n")
        prompt_parts.append(_format_input_images(images))
        prompt_parts.append("\n")

    prompt_parts.extend(
        [
            _format_block("Slide", {
                "number": number,
                "title": title,
                "role": slide.get("role"),
                "intent": slide.get("intent"),
            }),
            _format_block("Text", {
                "title": title,
                "key_points": _string_list(slide.get("key_points")),
                "speaker_focus": slide.get("speaker_focus"),
            }),
            _format_block("Layout", slide.get("layout")),
            _format_block("Visual Elements", slide.get("visual_elements")),
            _format_block("Source Image Rules", slide.get("source_image_rules")),
            _format_block("Constraints", _string_list(slide.get("constraints"))),
        ]
    )

    if global_style_reference:
        prompt_parts.append(
            "## Style Reference Rule\n"
            "Use Image 1 as the selected visual style baseline. Preserve its palette, "
            "typographic hierarchy, background texture, graphic language, whitespace, "
            "and layout family while composing the current page's approved content. "
            "Do not copy the reference's old wording, data, or any multi-page grid. "
            "Additional calibrated samples must not replace this selected baseline. "
            "Attach only input_images in their declared order; source_path is audit provenance, "
            "not an additional image to attach.\n"
        )

    if images:
        prompt_parts.append(
            "## Input Image Handling Rules\n"
            "For any input image marked as a strict input asset, include it visibly and "
            "preserve its content. Do not redraw, replace, relabel, or invent a similar "
            "figure. Scale and crop only as needed for composition while keeping the "
            "important labels, arrows, data, and relationships recognizable.\n"
        )

    prompt_parts.append(
        "## Universal Constraints\n"
        "- The final image itself must contain the title and key points.\n"
        "- Render Chinese text exactly and legibly; avoid garbled characters.\n"
        "- Keep the confirmed deck style consistent while varying layout by slide role.\n"
        "- No watermark, unrelated logo, or extra slide number.\n"
    )
    return "\n".join(part for part in prompt_parts if part)


def _job_images(
    slide: Dict[str, Any],
    *,
    number: int,
    global_style_reference: Optional[Dict[str, Any]],
    base_dir: Path,
) -> List[Dict[str, Any]]:
    images: List[Dict[str, Any]] = []
    if global_style_reference:
        images.append(global_style_reference)
    images.extend(_slide_images(slide, slide_number=number, base_dir=base_dir))
    return images


def _history_path(deck_dir: Path, value: str) -> Path:
    path = (deck_dir / value).resolve()
    if not path.is_relative_to(deck_dir):
        raise ValueError("Generation history inputs must remain inside the deck")
    return path


def _retain_unchanged_slide(deck_dir: Path, old_jobs: dict, previous: dict, current: dict, raw_job: bytes) -> bool:
    """Reuse completed work only while its exact request and result remain valid."""
    if previous.get("status") not in {"pending", "blocked", "recorded", "accepted"}:
        return False
    if (current.get("status") == "accepted"
            and (previous.get("status") != "accepted" or previous.get("result") != current.get("result"))):
        # Importing an explicitly provided sample changes the page's origin even
        # when its generated prompt is identical to an earlier queued request.
        return False
    if (previous.get("job") != current["job"] or previous.get("out") != current["out"]
            or previous.get("input_images") != current["input_images"]):
        return False
    job_path = _history_path(deck_dir, previous["job"])
    if not job_path.is_file() or job_path.read_bytes() != raw_job:
        return False
    if previous["status"] == "accepted" and previous.get("result") != current.get("result"):
        return False
    if previous["status"] in {"recorded", "accepted"}:
        result = previous.get("result") or {}
        image = _history_path(deck_dir, previous["out"])
        if not image.is_file() or sha256_file(image) != result.get("final_image_sha256"):
            raise ValueError("Completed slide image changed or missing; retain the current deck and recover its recorded image before preparing again")
        if previous["status"] == "recorded":
            if old_jobs.get("generation_evidence_policy") != "1.0":
                return False
            request_hash = validate_dispatch_inputs(deck_dir, previous)
            method = sample_method(old_jobs, json.loads(raw_job))
            validate_generation_record(result.get("generation_record"), slide_id=previous["slide_id"],
                                       request_sha256=request_hash, source_sha256=sha256_file(image),
                                       backend=result.get("backend_used"), expected_model=method.get("model"))
            if result.get("selected_source_sha256") != result.get("final_image_sha256"):
                raise ValueError("Completed slide differs from its recorded original")
    return True


def _archive_previous_preparation(deck_dir: Path, jobs: dict, files: dict) -> dict:
    """Retain the old requests, call records, observations and pixels before replacement."""
    names = {"slide_jobs.json", "slide_run_state.json", "slidemuse-content.json", "content-review.json", "speech.md"}
    for slide in jobs.get("slides", []):
        names.update(value for value in (slide.get("job"), slide.get("out"),
                                        (slide.get("dispatch") or {}).get("prompt")) if isinstance(value, str))
    retained = {}
    for name in sorted(names):
        path = _history_path(deck_dir, name)
        if not path.exists():
            continue
        if not path.is_file():
            raise ValueError(f"Generation history input is not a file: {name}")
        retained[path.relative_to(deck_dir).as_posix()] = path.read_bytes()
    for slide in jobs.get("slides", []):
        if slide.get("status") in {"recorded", "accepted"}:
            name = _history_path(deck_dir, slide["out"]).relative_to(deck_dir).as_posix()
            raw = retained.get(name)
            if raw is None or hashlib.sha256(raw).hexdigest() != (slide.get("result") or {}).get("final_image_sha256"):
                raise ValueError("Completed slide image changed or missing; retain the current deck and recover its recorded image before preparing again")
    # Reviews and notes can change independently of slide_jobs.json. Identify
    # the complete snapshot so each legitimate observation can be preserved.
    manifest = [(name, hashlib.sha256(raw).hexdigest()) for name, raw in sorted(retained.items())]
    identity = hashlib.sha256(json.dumps(manifest, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    prefix = f".generation-history/preparations/{identity}"
    for name, raw in retained.items():
        destination = f"{prefix}/{name}"
        existing = _history_path(deck_dir, destination)
        if existing.exists() and existing.read_bytes() != raw:
            raise ValueError("Retained generation history changed; preserve it for recovery")
        files[destination] = raw
    return {"directory": prefix, "jobs_sha256": hashlib.sha256(retained["slide_jobs.json"]).hexdigest(),
            "snapshot_sha256": identity, "archived_at": now_iso(),
            "reason": "replaced preparation; records and original output bytes retained"}


def _write_template(path: Path) -> None:
    template = {
        "deck_name": "example-deck",
        "language": "Chinese",
        "goal": "Explain the core idea of the source article.",
        "deck_context": {
            "source_summary": "Short source-wide summary that workers may need when a slide refers to the broader article.",
            "core_claim": "The central thesis that should stay consistent across the deck.",
            "canonical_terms": ["Term one", "Term two", "Term three"],
        },
        "selected_image_backend": "built-in image tool",
        "max_concurrent_slides": 6,
        "sample_generation_method": {
            "backend_used": "built-in image tool",
            "tool_name": "image_gen",
            "mode": "generate",
            "prompt_source": "the approved sample slide job prompt",
            "size": "16:9 landscape, 2560x1440 target",
            "quality": "medium",
            "approved_sample_path": "/absolute/path/to/approved-sample-slide.png",
            "input_context_preparation": "view_image local required images before built-in generation",
            "handoff_rule": "Subagents must use this same backend/tool/mode; return a blocker if unavailable.",
        },
        "style": {
            "name": "手绘技术解释风",
            "visual_direction": "clean hand-drawn technical explainer",
            "color_palette": "white background, black marker lines, pale yellow highlights",
            "typography": "large readable Chinese headings, compact handwritten annotations",
        },
        "approved_style_reference": {
            "path": "/absolute/path/to/approved-sample-slide.png",
            "role": "approved sample slide style reference",
            "fidelity": "match style only; do not copy layout or content",
        },
        "slides": [
            {
                "number": 1,
                "title": "Cover",
                "role": "cover",
                "intent": "Open the talk",
                "key_points": ["Point one", "Point two"],
                "local_context": {
                    "required_background": "Facts, lists, definitions, comparisons, or prior-slide references this slide needs to be self-contained.",
                },
                "layout": {"composition": "large title with one supporting visual"},
                "visual_elements": {"main_visual": "topic-specific hand-drawn metaphor"},
                "constraints": ["Keep text sparse"],
                "sample_approved": True,
            },
            {
                "number": 2,
                "title": "Evidence",
                "role": "data evidence",
                "intent": "Explain a supplied result figure",
                "key_points": ["Preserve the original figure", "Add two callouts"],
                "required_images": [
                    {
                        "path": "/absolute/path/to/result_01.png",
                        "role": "strict input asset and main evidence figure",
                        "fidelity": "preserve data, axes, labels, legends, colors, and values",
                    },
                    "strict input asset and comparison chart\n\n![Result chart](assets/figures/result_02.png)",
                ],
                "layout": {"composition": "source figure left, explanation cards right"},
            },
        ],
    }
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None, companion=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", help="Deck spec JSON file.")
    parser.add_argument("--out-dir", help="Deck project directory.")
    parser.add_argument("--write-template", help="Write an example deck spec JSON and exit.")
    parser.add_argument(
        "--selected-backend",
        help="Confirmed image backend label, such as `built-in image tool` or `scripts/image_gen.py`.",
    )
    parser.add_argument(
        "--max-concurrent-slides",
        type=int,
        default=None,
        help=f"Maximum slide subagents to dispatch at once. Defaults to {DEFAULT_MAX_CONCURRENT_SLIDES}.",
    )
    parser.add_argument("--force", action="store_true", help="Refresh inactive jobs; preserve unchanged results and archive replaced work.")
    args = parser.parse_args(argv)

    if args.write_template:
        _write_template(Path(args.write_template))
        return 0

    if not args.spec or not args.out_dir:
        _die("Use --spec and --out-dir, or --write-template.")

    spec_path = Path(args.spec)
    spec = _read_json(spec_path)
    spec_dir = spec_path.resolve().parent
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        _die("Deck spec must include a non-empty slides array.")

    numbered_slides: List[tuple[int, Dict[str, Any], int]] = []
    seen_slide_numbers: Dict[int, int] = {}
    for fallback, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            _die(f"Slide entry {fallback} must be an object.")
        number = _slide_number(slide, fallback)
        if number in seen_slide_numbers:
            _die(
                f"Duplicate slide number {number}: slide entries "
                f"{seen_slide_numbers[number]} and {fallback} would both write slide_{number:02d}.json."
            )
        seen_slide_numbers[number] = fallback
        numbered_slides.append((fallback, slide, number))

    with preparation_lock(Path(args.out_dir)):
        return _prepare_locked(args, spec, spec_dir, slides, numbered_slides, companion)


def _prepare_locked(args, spec, spec_dir, slides, numbered_slides, companion):
    out_dir = Path(args.out_dir).resolve()
    prompts_dir = out_dir / "prompts"
    if (out_dir / "origin_image").exists() and not (out_dir / "origin_image").is_dir():
        _die("origin_image must be a directory; prior files were retained.")
    prepared_files = {}
    old_jobs = read_json(out_dir / "slide_jobs.json", default={})
    if any(page.get("status") == "dispatched" for page in old_jobs.get("slides", [])):
        _die("Cannot prepare while slide workers are dispatched; record or block their results first.")
    old_slides = {entry["slide_id"]: entry for entry in old_jobs.get("slides", [])}
    replaced_slides = set(old_slides)

    global_style_reference = _bind_style_reference(spec, base_dir=spec_dir)
    style_reference = spec.get("style_reference")
    validate_style_reference(style_reference)

    sample_generation_method = _sample_generation_method(spec, base_dir=spec_dir)
    max_concurrent_slides = args.max_concurrent_slides
    if max_concurrent_slides is None:
        max_concurrent_slides = int(spec.get("max_concurrent_slides", DEFAULT_MAX_CONCURRENT_SLIDES))
    if max_concurrent_slides < 1:
        _die("max_concurrent_slides must be >= 1.")
    selected_backend = (
        args.selected_backend
        or spec.get("selected_image_backend")
        or spec.get("image_backend")
        or _method_backend_label(sample_generation_method)
    )
    slide_job_entries: List[Dict[str, Any]] = []

    for fallback, slide, number in numbered_slides:
        use_style_reference = bool(slide.get("use_approved_style_reference", True))
        if style_reference is not None and not use_style_reference:
            _die("Every slide must retain the selected style baseline; it cannot be disabled per page.")
        slide_style_reference = global_style_reference if use_style_reference else None
        prompt = _build_prompt(
            deck=spec,
            slide=slide,
            number=number,
            global_style_reference=slide_style_reference,
            base_dir=spec_dir,
        )
        images = _job_images(slide, number=number, global_style_reference=slide_style_reference, base_dir=spec_dir)
        validate_style_reference(style_reference, images)
        job = {
            "slide": number,
            "title": slide.get("title", f"Slide {number}"),
            "prompt": prompt,
            "out": f"slide_{number:02d}.png",
            "input_images": images,
            "requires_context_images": bool(images),
            "expected_backend": selected_backend,
            "sample_generation_method": sample_generation_method,
            **({"style_reference": style_reference} if style_reference is not None else {}),
            **({"canvas": spec["canvas"]} if "canvas" in spec else {}),
            "generation_contract": {
                "must_use_selected_image_backend": True,
                "must_match_sample_generation_method": bool(sample_generation_method),
                "forbidden_final_image_methods": [
                    "local drawing/rendering scripts",
                    "Pillow-generated slides",
                    "SVG/HTML/CSS/canvas screenshots",
                    "python-pptx/PptxGenJS/native PPT layout screenshots",
                    "manually composited text/image overlays",
                ],
                "must_return": ["backend_used", "selected_source", "qa_note"],
            },
        }
        prompt_path = prompts_dir / f"slide_{number:02d}.json"
        if prompt_path.exists() and not args.force:
            _die(f"Slide job file already exists: {prompt_path} (use --force)")
        raw_job = (json.dumps(job, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        prepared_files[rel_to_deck(out_dir, prompt_path)] = raw_job
        slide_id = f"slide_{number:02d}"
        final_image = out_dir / "origin_image" / f"{slide_id}.png"
        sample_approved = bool(slide.get("sample_approved") or slide.get("approved_sample"))
        status = "accepted" if sample_approved and final_image.exists() else "pending"
        sample_result = None
        if status == "accepted":
            origin = slide.get("image_origin", {})
            sample_hash = sha256_file(final_image)
            if (not isinstance(origin, dict) or origin.get("kind") != "provided"
                    or not isinstance(origin.get("source_ref"), str) or not origin["source_ref"].strip()
                    or origin.get("sha256") != sample_hash):
                _die("An existing approved sample requires image_origin with kind=provided, source_ref and its current sha256.")
            sample_result = {"final_image": rel_to_deck(out_dir, final_image),
                             "final_image_sha256": sample_hash, "selected_source_sha256": sample_hash,
                             "accepted_sample": True, "source_kind": "provided", "source_ref": origin["source_ref"]}
        entry = {
                "slide_id": slide_id,
                "number": number,
                "title": slide.get("title", f"Slide {number}"),
                "job": rel_to_deck(out_dir, prompt_path),
                "out": rel_to_deck(out_dir, final_image),
                "input_images": images,
                "requires_context_images": bool(images),
                "status": status,
                "dispatch": None,
                "result": sample_result,
                "blocker": None,
            }
        previous = old_slides.get(slide_id)
        if previous and _retain_unchanged_slide(out_dir, old_jobs, previous, entry, raw_job):
            entry = copy.deepcopy(previous)
            replaced_slides.discard(slide_id)
        slide_job_entries.append(entry)

    slide_jobs = {
        "run_status": "jobs_prepared",
        "deck_name": spec.get("deck_name"),
        "selected_backend": selected_backend,
        "sample_generation_method": sample_generation_method,
        **({"style_reference": style_reference} if style_reference is not None else {}),
        **({"canvas": spec["canvas"]} if "canvas" in spec else {}),
        "max_concurrent_slides": max_concurrent_slides,
        "generation_evidence_policy": "1.0",
        "slides": slide_job_entries,
        "updated_at": now_iso(),
    }
    if companion is not None:
        prepared_files.update(companion(out_dir, spec, slide_jobs, prepared_files))
    history = copy.deepcopy(old_jobs.get("preparation_history", []))
    if not isinstance(history, list):
        raise ValueError("Generation preparation history must be a list")
    changed_files = any((out_dir / name).is_file() and (out_dir / name).read_bytes() != raw
                        for name, raw in prepared_files.items())
    if old_jobs and (replaced_slides or changed_files):
        history.append(_archive_previous_preparation(out_dir, old_jobs, prepared_files))
        previous_contract = out_dir / "slidemuse-content.json"
        if ("slidemuse-content.json" in prepared_files and previous_contract.is_file()
                and previous_contract.read_bytes() != prepared_files["slidemuse-content.json"]
                and (out_dir / "content-review.json").exists()):
            # Its exact observations remain in the archived preparation. A new
            # contract must not inherit approval or block review --init forever.
            prepared_files["content-review.json"] = None
        # Removed pages must not remain as extra final images in the new deck.
        current_ids = {entry["slide_id"] for entry in slide_job_entries}
        current_paths = {entry[key] for entry in slide_job_entries for key in ("out", "job")}
        input_paths = set()
        for entry in slide_job_entries:
            for image in entry["input_images"]:
                value = image.get("path")
                if isinstance(value, str) and Path(value).is_absolute():
                    input_paths.add(Path(value).resolve())
        if style_reference is not None:
            input_paths.update(Path(style_reference[key]).resolve() for key in ("path", "source_path"))
        for slide_id in set(old_slides) - current_ids:
            for key in ("out", "job"):
                name = old_slides[slide_id].get(key)
                if isinstance(name, str) and name not in current_paths:
                    expected = f"origin_image/{slide_id}.png" if key == "out" else f"prompts/{slide_id}.json"
                    if name != expected:
                        raise ValueError("Removed page uses a custom managed path; retain and reconcile it before preparing again")
                    if _history_path(out_dir, name) in input_paths:
                        raise ValueError("Removed page is still an input reference; save that reference under an independent path before preparing again")
                    prepared_files[name] = None
    if history:
        slide_jobs["preparation_history"] = history
    update_jobs_run_status(slide_jobs)
    state = read_json(out_dir / "slide_run_state.json", default={"status": "created", "history": []})
    status = slide_jobs["run_status"]
    if state.get("status") != status:
        state.setdefault("history", []).append({"from": state.get("status"), "to": status,
                                                "at": now_iso(), "note": "prepared slide prompt jobs"})
    state.update(status=status, updated_at=now_iso())
    for name, value in (("slide_jobs.json", slide_jobs), ("slide_run_state.json", state)):
        prepared_files[name] = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (out_dir / "origin_image").mkdir(parents=True, exist_ok=True)
    commit_preparation(out_dir, prepared_files)

    print(f"Wrote {len(slides)} slide job file(s) to {prompts_dir}")
    print(f"Wrote slide job state to {out_dir / 'slide_jobs.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
