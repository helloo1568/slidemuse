#!/usr/bin/env python3
"""Record that a codex-ppt slide job was dispatched to a subagent."""

from __future__ import annotations

import argparse
from pathlib import Path

from slide_run_state import (
    deck_dir_from_target,
    dispatch_slots_available,
    find_slide,
    locked_jobs,
    now_iso,
    rel_to_deck,
    resolve_deck_path,
    set_run_status,
    sha256_file,
    update_jobs_run_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck", help="Deck directory or slide_jobs.json")
    parser.add_argument("--slide", required=True, help="slide_01 or 1")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--agent-nickname")
    parser.add_argument("--prompt-file", help="Prompt file path. Defaults to the job file in slide_jobs.json.")
    args = parser.parse_args()

    deck_dir = deck_dir_from_target(args.deck)
    with locked_jobs(deck_dir) as jobs:
        slide = find_slide(jobs, args.slide)
        if slide.get("status") != "pending":
            raise SystemExit(f"{slide['slide_id']} must be pending before dispatch; got {slide.get('status')}")
        if dispatch_slots_available(jobs) == 0:
            raise SystemExit("No dispatch slots available; wait for an active slide to finish or record its blocker.")

        prompt_ref = args.prompt_file or slide.get("job")
        if not prompt_ref:
            raise SystemExit(f"{slide['slide_id']} has no prompt job path.")
        prompt_path = resolve_deck_path(deck_dir, prompt_ref)
        try:
            prompt_path.relative_to(deck_dir)
        except ValueError as exc:
            raise SystemExit(f"Prompt file must live inside deck dir: {prompt_path}") from exc
        if not prompt_path.exists():
            raise SystemExit(f"Prompt file does not exist: {prompt_path}")
        job_ref = slide.get("job")
        if not isinstance(job_ref, str) or not job_ref.strip():
            raise SystemExit(f"{slide['slide_id']} has no canonical job file.")
        job_path = resolve_deck_path(deck_dir, job_ref)
        if not job_path.is_relative_to(deck_dir) or not job_path.is_file() or not prompt_path.is_file():
            raise SystemExit("Canonical job and worker prompt must be files inside the deck")

        slide["dispatch"] = {
            "agent_id": args.agent_id,
            "agent_nickname": args.agent_nickname,
            "prompt": rel_to_deck(deck_dir, prompt_path),
            "prompt_sha256": sha256_file(prompt_path),
            "job_sha256": sha256_file(job_path),
            "dispatched_at": now_iso(),
        }
        slide["status"] = "dispatched"
        update_jobs_run_status(jobs)
        run_status = jobs.get("run_status")
        if run_status == "slides_dispatched":
            set_run_status(deck_dir, "slides_dispatched", "all slide jobs dispatched")
    print(f"{slide['slide_id']} -> dispatched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
