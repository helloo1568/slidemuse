"""Shared content requirements, separate from human judgments of evidence quality."""
from __future__ import annotations

import unicodedata

ROLES = {"cover", "agenda", "section-divider", "concept", "process", "comparison", "timeline",
         "data-evidence", "architecture", "case-study", "summary", "qa"}
BRIEF_ROLES = {"cover", "agenda", "section-divider", "summary", "qa"}
MODES = {"standard": (3, 5), "evidence-led": (1, 5), "brief": (1, 2), "detailed": (3, 8)}
WORKFLOW_POLICY = "1.1"
CONTENT_POLICIES = {"1.0", WORKFLOW_POLICY}


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def validate_content(slide, *, required=False):
    """Check declared content only; a recorded source does not prove source truth."""
    if required and (not isinstance(slide.get("title"), str) or not slide["title"].strip()):
        raise ValueError("Every page requires a readable title")
    validate_display(slide)
    role = slide.get("role")
    if role not in ROLES:
        if required or role is not None:
            raise ValueError("Content page must declare a supported role")
        return
    density = slide.get("density", {})
    if not isinstance(density, dict) or set(density) - {"mode", "reason"}:
        raise ValueError("density accepts only mode and reason")
    mode = density.get("mode", "standard")
    if mode not in MODES:
        raise ValueError("Unknown density mode")
    if mode != "standard" and not str(density.get("reason", "")).strip():
        raise ValueError("Non-standard density requires a reason tied to the page content")
    points = slide.get("key_points")
    if points is not None:
        if not isinstance(points, list) or any(not isinstance(p, str) or not normalized(p) for p in points):
            raise ValueError("key_points must be nonempty readable strings")
        if len({normalized(p) for p in points}) != len(points):
            raise ValueError("key_points contain duplicate wording")
    if role in BRIEF_ROLES:
        return
    if points is None:
        if required:
            raise ValueError("Content page requires key_points")
    else:
        low, high = MODES[mode]
        if not low <= len(points) <= high:
            raise ValueError(f"Content density {mode} requires {low}-{high} key_points")
    if required:
        for key in ("core_message", "explanation"):
            if not isinstance(slide.get(key), str) or not slide[key].strip():
                raise ValueError(f"Content page requires {key}")
    refs = slide.get("source_refs")
    if refs is not None and (
        not isinstance(refs, list)
        or any(not isinstance(item, str) or not item.strip() for item in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("source_refs must be a list of unique nonempty records when provided")


def semantic_claims(slide):
    """Stable paths whose meaning must survive a display rewrite."""
    claims = {key for key in ("core_message", "explanation", "boundary") if slide.get(key)}
    claims.update(f"key_points/{index}" for index, _ in enumerate(slide.get("key_points", [])))
    return claims


def validate_display(slide):
    display = slide.get("display")
    if display is None:
        return
    if not isinstance(display, dict) or set(display) != {"coverage"} or not isinstance(display["coverage"], list):
        raise ValueError("display requires only a coverage array")
    elements = {e["id"]: e for e in slide.get("elements", [])}
    claims = semantic_claims(slide)
    sources = slide.get("source_refs")
    legacy_source_claims = {f"source_refs/{index}" for index, _ in enumerate(sources)} if isinstance(sources, list) else set()
    known_claims = claims | legacy_source_claims
    seen = set()
    for item in display["coverage"]:
        if not isinstance(item, dict) or set(item) != {"claim", "element_ids"}:
            raise ValueError("Display coverage needs claim and element_ids")
        claim, ids = item["claim"], item["element_ids"]
        if not isinstance(claim, str) or claim in seen or claim not in known_claims:
            raise ValueError("Unknown or duplicate display claim")
        if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids)
                or len(set(ids)) != len(ids) or any(i not in elements for i in ids)):
            raise ValueError("Display coverage must name existing unique elements")
        for identifier in ids:
            element = elements[identifier]
            if element.get("confirmation_status") == "unresolved" or element.get("kind") not in ("text", "image", "chart", "table"):
                raise ValueError("Display coverage needs confirmed text or evidence")
            if element.get("kind") == "text" and not str(element.get("text", "")).strip():
                raise ValueError("Display text must be nonempty")
        seen.add(claim)
    if not claims.issubset(seen):
        raise ValueError("Display coverage must map every semantic claim, including boundaries")


def visible_text(slide, *, policy=None):
    """One visible-content list for generator prompts and image observations."""
    values = [slide.get("title", "")]
    if "display" in slide:
        validate_display(slide)
    elif policy != WORKFLOW_POLICY:
        values += [slide.get("core_message", ""), *slide.get("key_points", []),
                   slide.get("explanation", ""), slide.get("boundary", "")]
    values += slide.get("required_visible_values", [])
    values += [e["text"] for e in slide.get("elements", [])
               if e.get("kind") == "text" and e.get("confirmation_status") != "unresolved"]
    # Structured table/chart contents stay in the contract for separate visual review;
    # only explicitly declared visible strings must match a transcription.
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value.strip()))


def prompt_elements(elements):
    """Keep exact element content and geometry, with provenance in the saved specification."""
    return [{key: value for key, value in element.items() if key not in {"source_ref", "notes", "prompt_record"}}
            for element in elements]
