#!/usr/bin/env python3
import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from deck_run_state import load_deck, load_jobs, now_iso, read_json, resolve_inside, run_dir_from_target, save_deck, save_jobs, set_run_status, sha256_file, write_json


SCRIPT_DIR = Path(__file__).resolve().parent


def run(command):
    print("+ " + " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def final_output_path(run_dir, deck):
    output = Path(deck.get("output", "final/deck_edited.pptx"))
    if output.is_absolute():
        return output
    return run_dir / output


def assert_pages_ready(run_dir, jobs):
    problems = []
    for page in jobs.get("pages", []):
        if page.get("status") not in {"recorded", "accepted"}:
            problems.append(f"{page['page_id']} status={page.get('status')}")
            continue
        result = page.get("result") or {}
        if result.get("validation_passed") is not True:
            problems.append(f"{page['page_id']} validation_passed={result.get('validation_passed')}")
        outputs = result.get("outputs") or {}
        hashes = result.get("hashes") or {}
        if not {"page_manifest", "validation"}.issubset(outputs) or set(outputs) != set(hashes):
            problems.append(f"{page['page_id']} missing recorded output hashes; validate and record the page again")
            continue
        files = [(outputs[key], digest) for key, digest in hashes.items()]
        files.extend((result.get("asset_hashes") or {}).items())
        for relative_path, expected_hash in files:
            try:
                path = resolve_inside(run_dir, relative_path)
            except ValueError:
                problems.append(f"{page['page_id']} recorded artifact is outside the run: {relative_path}")
                continue
            if not path.is_file() or sha256_file(path) != expected_hash:
                problems.append(
                    f"{page['page_id']} recorded artifact changed or missing: {relative_path}; "
                    "repair affected outputs, validate and record the page again"
                )
    if problems:
        raise SystemExit("Pages are not ready for finalize:\n" + "\n".join(problems))


def recorded_deck(run_dir, deck, jobs):
    """Bind compilation and validation to the exact artifacts accepted by record."""
    pages, recorded = deck.get("pages", []), jobs.get("pages", [])
    ids = [page.get("page_id") for page in pages]
    if (not pages or len(pages) != len(recorded) or len(ids) != len(set(ids))
            or any(not value for value in ids)
            or ids != [page.get("page_id") for page in recorded]
            or int(deck.get("page_count", len(pages))) != len(pages)
            or deck.get("run_id") != jobs.get("run_id")):
        raise SystemExit("Recorded page identities/order differ from the deck; reconcile the run before finalize")
    bound = copy.deepcopy(deck)
    bound["job_dir"] = str(run_dir)
    bound["page_count"] = len(pages)
    for index, (page, record) in enumerate(zip(bound["pages"], recorded), 1):
        if page.get("page_index", index) != index or record.get("page_index", index) != index:
            raise SystemExit("Recorded page indices differ from deck order")
        outputs, hashes = record["result"]["outputs"], record["result"]["hashes"]
        page.update(manifest=outputs["page_manifest"], validation=outputs["validation"],
                    manifest_sha256=hashes["page_manifest"], validation_sha256=hashes["validation"])
    return bound


def main():
    parser = argparse.ArgumentParser(description="Build and validate the final editable PPTX from recorded pages.")
    parser.add_argument("run", help="Run directory or deck_manifest.json")
    args = parser.parse_args()

    run_dir = run_dir_from_target(args.run)
    deck = load_deck(run_dir)
    jobs = load_jobs(run_dir)
    assert_pages_ready(run_dir, jobs)
    assembly = recorded_deck(run_dir, deck, jobs)

    out = final_output_path(run_dir, assembly).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    validation = out.parent / "validation.json"
    assembly_path = out.with_name(out.stem + "-assembly.json")
    with tempfile.TemporaryDirectory(prefix=".finalize-", dir=out.parent) as temporary:
        stage = Path(temporary)
        staged_deck, staged_out, staged_validation = stage / "assembly.json", stage / out.name, stage / "validation.json"
        write_json(staged_deck, assembly)
        run([sys.executable, SCRIPT_DIR / "build_pptx_from_manifest.py", "--deck-manifest", staged_deck, "--out", staged_out])
        run([sys.executable, SCRIPT_DIR / "validate_pptx.py", staged_out, "--deck-manifest", staged_deck, "--report", staged_validation])
        # Inputs must still be the same recorded revision when publishing.
        assert_pages_ready(run_dir, jobs)
        if load_jobs(run_dir) != jobs or load_deck(run_dir) != deck:
            raise SystemExit("Run changed during finalize; retain the existing output and finalize the current records again")
        report = read_json(staged_validation)
        report.update(pptx=str(out), deck_manifest=str(assembly_path))
        write_json(staged_validation, report)
        os.replace(staged_out, out)
        os.replace(staged_deck, assembly_path)
        os.replace(staged_validation, validation)
    set_run_status(run_dir, "deck_built", "final pptx built")
    set_run_status(run_dir, "deck_validated", "final pptx validation passed")

    for page in jobs.get("pages", []):
        page["status"] = "accepted"
        page["accepted"] = True
        page["accepted_at"] = now_iso()
    jobs["run_status"] = "complete"
    jobs["updated_at"] = now_iso()
    save_jobs(run_dir, jobs)
    assembly["completed_at"] = now_iso()
    save_deck(run_dir, assembly)
    summary = {
        "schema_version": 1,
        "run_id": deck.get("run_id"),
        "status": "complete",
        "page_count": len(jobs.get("pages", [])),
        "output": str(out),
        "validation": str(validation),
        "completed_at": now_iso(),
    }
    write_json(out.parent / "run_summary.json", summary)
    set_run_status(run_dir, "complete", "final deck complete")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
