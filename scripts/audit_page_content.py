#!/usr/bin/env python3
"""Compare a visual transcription of generated pages with approved Page Spec text."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from content_density import CONTENT_POLICIES, WORKFLOW_POLICY, visible_text
from json_io import checked_output_path, read_json, write_json
from validate_page_spec import load_page_spec, page_asset_names

NUMBER = re.compile(
    r"(?:(?P<sign>[-−]|(?<!\d)\+)[ \t]*|(?<![A-Za-z0-9]))"
    r"(?P<magnitude>(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][+\-−]?\d+)?)"
    r"(?P<ratio>[ \t]*(?:\r?\n[ \t]*)?[%‰])?"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number_spans(value: str):
    previous_number_end = -1
    for number in NUMBER.finditer(value):
        start, end = number.span()
        identifier = False
        if number["sign"] in ("-", "−"):
            before = start
            while before and value[before - 1] in " \t":
                before -= 1
            left = value[before - 1] if before else ""
            # Ranges keep two unsigned endpoints. An ASCII label joined to a
            # bare integer (A-32) keeps a boundary without implying a negative.
            if before == previous_number_end:
                start = number.start("magnitude")
            else:
                identifier = (number["sign"] == "-" and left.isascii() and left.isalpha()
                              and number["magnitude"].isdecimal() and number["ratio"] is None)
        if not identifier:
            previous_number_end = end
        yield start, end, identifier


def compact_chars(value: str) -> str:
    return "".join(char for char in value.replace("−", "-") if char.isalnum() or char in ".%‰+-/")


def compact(value: str) -> str:
    return compact_chars(unicodedata.normalize("NFKC", value).casefold())


def numbers(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value)
    return [value[start:end].replace("−", "-") for start, end, identifier in number_spans(value) if not identifier]


def compact_number(value: str) -> str:
    return compact(value)


def compact_with_number_offsets(value: str) -> tuple[str, dict[int, tuple[str, bool]]]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    parts, offsets = [], {}
    cursor = position = 0
    for start, end, identifier in number_spans(normalized):
        prefix = compact_chars(normalized[cursor:start])
        token = compact_chars(normalized[start:end])
        position += len(prefix)
        offsets[position] = (token, identifier)
        parts.extend((prefix, token))
        position += len(token)
        cursor = end
    parts.append(compact_chars(normalized[cursor:]))
    return "".join(parts), offsets


def text_present(expected: str, observed: str) -> bool:
    """Match each whole numeric token at its position inside the matched text."""
    wanted, required = compact_with_number_offsets(expected)
    if not required:
        return wanted in compact(observed)
    text, actual = compact_with_number_offsets(observed)
    start = text.find(wanted)
    while start != -1:
        if all(actual.get(start + offset) == token for offset, token in required.items()):
            return True
        start = text.find(wanted, start + 1)
    return False


def image_path(spec_path: Path, slide: dict) -> Path:
    if slide["image_status"] not in ("generated", "revision", "approved"):
        raise ValueError(f"Page image is not ready for transcription: {slide['id']}")
    root = spec_path.resolve().parent
    target = (root / slide["image_file"]).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"Missing or unsafe page image: {slide['image_file']}")
    return target


def template(spec_path: Path, slides: list[dict]) -> dict:
    return {"version": "1.0", "slides": [
        {"id": slide["id"], "image_sha256": sha256(image_path(spec_path, slide)),
         "status": "partial", "observed_text": ""}
        for slide in slides
    ]}


def observation_entries(observations) -> list[dict]:
    if (not isinstance(observations, dict) or observations.get("version") != "1.0"
            or not isinstance(observations.get("slides"), list)):
        raise ValueError("Observations must contain a JSON object with version 1.0 and a slides array")
    seen = set()
    for index, entry in enumerate(observations["slides"], 1):
        slide_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(slide_id, str) or not slide_id:
            raise ValueError(f"Observation entry {index} must be an object with a nonempty slide ID")
        if slide_id in seen:
            raise ValueError(f"Unknown or duplicate observation slide: {slide_id}")
        seen.add(slide_id)
    return observations["slides"]


def read_observations(path: Path) -> list[dict]:
    try:
        return observation_entries(read_json(path))
    except ValueError as error:
        raise ValueError(f"Invalid observation file {path}: {error}") from error


def audit(spec_path: Path, slides: list[dict], observations: dict) -> dict:
    entries = observation_entries(observations)
    policy = read_json(spec_path).get("content_policy") if spec_path.is_file() else None
    by_id = {slide["id"]: slide for slide in slides}
    seen = set()
    results = []
    for observation in entries:
        slide_id = observation["id"]
        if slide_id not in by_id:
            raise ValueError(f"Unknown observation slide: {slide_id}")
        seen.add(slide_id)
        slide = by_id[slide_id]
        current_hash = sha256(image_path(spec_path, slide))
        if observation.get("image_sha256") != current_hash:
            raise ValueError(f"Stale visual transcription for {slide_id}: image hash changed")
        status = observation.get("status")
        text = observation.get("observed_text")
        if status not in ("partial", "complete") or not isinstance(text, str):
            raise ValueError(f"{slide_id}: status must be partial/complete and observed_text must be a string")
        observed_numbers = {compact_number(number) for number in numbers(text)}
        findings = []
        expected = [
            (element["id"], element["text"])
            for element in slide["elements"]
            if element["kind"] == "text" and element["confirmation_status"] != "unresolved"
        ]
        expected += [("required_visible_values", value) for value in slide.get("required_visible_values", [])]
        if policy in CONTENT_POLICIES:
            declared = {value for _, value in expected} if policy == WORKFLOW_POLICY else set()
            expected += [("content_contract", value) for value in visible_text(slide, policy=policy)
                         if value not in declared]
        for element_id, value in expected:
            if compact(value) and not text_present(value, text):
                missing_numbers = [number for number in numbers(value) if compact_number(number) not in observed_numbers]
                findings.append({
                    "element_id": element_id,
                    "expected": value,
                    "kind": "missing_numeric" if missing_numbers else "missing_text",
                    "missing_numbers": missing_numbers,
                    "status": "issue" if status == "complete" else "needs_review",
                })
        results.append({"id": slide_id, "status": status, "findings": findings,
                        "unresolved_source_elements": [element["id"] for element in slide["elements"]
                                                       if element["confirmation_status"] == "unresolved"],
                        "unchecked_data_elements": [element["id"] for element in slide["elements"]
                                                    if element["kind"] in ("chart", "table")]})
    missing_slides = sorted(set(by_id) - seen)
    issues = sum(finding["status"] == "issue" for result in results for finding in result["findings"])
    incomplete = len(missing_slides) + sum(result["status"] != "complete" for result in results)
    return {"slides": results, "missing_observations": missing_slides, "issues": issues,
            "incomplete": incomplete, "pass": issues == 0 and incomplete == 0,
            "note": "Visual transcription is evidence, not authority. Chart/table data and unrecognized text still require review."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page_spec", type=Path)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--init", action="store_true", help="Create a hash-bound transcription template")
    parser.add_argument("--slide", action="append", default=[], help="Check or prepare only this slide ID")
    parser.add_argument("--output", type=Path, help="Write JSON audit report")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        run_cli(args)
    except (OSError, ValueError) as error:
        parser.exit(2, f"audit_page_content: {error}\n")


def run_cli(args) -> None:
    spec_path = args.page_spec.resolve()
    spec, _ = load_page_spec(spec_path)
    ids = set(args.slide)
    if ids - {slide["id"] for slide in spec["slides"]}:
        raise ValueError(f"Unknown slide IDs: {', '.join(sorted(ids - {slide['id'] for slide in spec['slides']}))}")
    slides = [slide for slide in spec["slides"] if not ids or slide["id"] in ids]
    inputs = [spec_path, *(spec_path.parent / name for name in page_asset_names(spec))]
    if args.init:
        checked_output_path(args.observations, inputs)
        if args.observations.exists():
            raise ValueError("observation file already exists")
        record = template(spec_path, slides)
        args.observations.parent.mkdir(parents=True, exist_ok=True)
        with args.observations.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        print(args.observations)
        return
    entries = read_observations(args.observations)
    if ids:
        entries = [item for item in entries if item["id"] in ids]
    report = audit(spec_path, slides, {"version": "1.0", "slides": entries})
    if args.output:
        output = checked_output_path(args.output, [args.observations, *inputs])
        write_json(output, report)
    print(json.dumps({"issues": report["issues"], "incomplete": report["incomplete"], "pass": report["pass"]}, ensure_ascii=False))
    if report["issues"] or (args.require_complete and report["incomplete"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
