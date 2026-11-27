#!/usr/bin/env python3
"""State helpers for codex-ppt slide generation runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from filelock import FileLock


ACTIVE_SLIDE_STATUSES = {"dispatched"}
DISPATCHABLE_SLIDE_STATUSES = {"pending"}
TERMINAL_SLIDE_STATUSES = {"recorded", "accepted", "blocked"}
DEFAULT_MAX_CONCURRENT_SLIDES = 6


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@contextmanager
def locked_json(path: Path, default: Any = None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with FileLock(str(lock_path)):
        data = read_json(path, default=default)
        try:
            yield data
        except Exception:
            raise
        else:
            write_json(path, data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_generation_record(value: Any, *, slide_id: str, request_sha256: str,
                               source_sha256: str, backend: str) -> None:
    """Check call-record bindings; a declaration does not authenticate a provider."""
    required = {"version", "slide_id", "request_sha256", "source_sha256", "backend", "model", "result_ref"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Generation record requires version, slide_id, request_sha256, source_sha256, backend, model and result_ref")
    if (value["version"] != "1.0" or value["slide_id"] != slide_id
            or value["request_sha256"] != request_sha256 or value["source_sha256"] != source_sha256
            or value["backend"] != backend):
        raise ValueError("Generation record differs from the dispatched request, source image or backend")
    if any(not isinstance(value[key], str) or not value[key].strip() for key in ("backend", "result_ref")):
        raise ValueError("Record the actual image tool/backend and call/result locator")
    if value["model"] is not None and (not isinstance(value["model"], str) or not value["model"].strip()):
        raise ValueError("Model must be its actual name, or null when the host does not expose it")


def validate_dispatch_inputs(deck_dir: Path, slide: Dict[str, Any]) -> str:
    """Bind the canonical page job and optional custom worker handoff separately."""
    dispatch = slide.get("dispatch") or {}
    for reference, hash_key, label in ((slide.get("job"), "job_sha256", "canonical job"),
                                       (dispatch.get("prompt"), "prompt_sha256", "worker prompt")):
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"Dispatched {label} is missing")
        path = resolve_deck_path(deck_dir, reference)
        if not path.is_relative_to(Path(deck_dir).resolve()) or not path.is_file():
            raise ValueError(f"Dispatched {label} must remain a file inside the deck")
        if dispatch.get(hash_key) != sha256_file(path):
            raise ValueError(f"Dispatched {label} changed; prepare and dispatch the approved inputs again")
    return dispatch["job_sha256"]


def deck_dir_from_target(target: str) -> Path:
    path = Path(target).expanduser().resolve()
    if path.is_dir():
        return path
    if path.name == "slide_jobs.json":
        return path.parent
    raise ValueError(f"Expected deck directory or slide_jobs.json: {target}")


def slide_jobs_path(deck_dir: Path) -> Path:
    return Path(deck_dir) / "slide_jobs.json"


def run_state_path(deck_dir: Path) -> Path:
    return Path(deck_dir) / "slide_run_state.json"


def load_jobs(deck_dir: Path) -> Dict[str, Any]:
    return read_json(slide_jobs_path(deck_dir))


def save_jobs(deck_dir: Path, jobs: Dict[str, Any]) -> None:
    write_json(slide_jobs_path(deck_dir), jobs)


def locked_jobs(deck_dir: Path):
    return locked_json(slide_jobs_path(deck_dir))


def load_run_state(deck_dir: Path) -> Dict[str, Any]:
    return read_json(run_state_path(deck_dir), default={"status": "created", "history": []})


def save_run_state(deck_dir: Path, state: Dict[str, Any]) -> None:
    write_json(run_state_path(deck_dir), state)


def locked_run_state(deck_dir: Path) -> Any:
    return locked_json(run_state_path(deck_dir), default={"status": "created", "history": []})


def set_run_status(deck_dir: Path, status: str, note: str | None = None) -> Dict[str, Any]:
    with locked_run_state(deck_dir) as state:
        if state.get("status") != status:
            state.setdefault("history", []).append(
                {"from": state.get("status"), "to": status, "at": now_iso(), "note": note}
            )
        state["status"] = status
        state["updated_at"] = now_iso()
    return state


def normalize_slide_id(value: Any) -> str:
    text = str(value).strip()
    if text.startswith("slide_"):
        suffix = text.removeprefix("slide_")
        if suffix.isdigit():
            return f"slide_{int(suffix):02d}"
    if text.isdigit():
        return f"slide_{int(text):02d}"
    raise ValueError(f"Invalid slide id: {value}")


def find_slide(jobs: Dict[str, Any], slide: Any) -> Dict[str, Any]:
    slide_id = normalize_slide_id(slide)
    for entry in jobs.get("slides", []):
        if entry.get("slide_id") == slide_id or str(entry.get("number")) == str(slide):
            return entry
    raise KeyError(f"Slide not found in slide_jobs.json: {slide_id}")


def resolve_deck_path(deck_dir: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path(deck_dir) / path
    return path.resolve()


def rel_to_deck(deck_dir: Path, value: Path) -> str:
    return Path(value).resolve().relative_to(Path(deck_dir).resolve()).as_posix()


def ensure_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing {label}: {path}")
    return path


def active_slides(jobs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [slide for slide in jobs.get("slides", []) if slide.get("status") in ACTIVE_SLIDE_STATUSES]


def dispatchable_slides(jobs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [slide for slide in jobs.get("slides", []) if slide.get("status") in DISPATCHABLE_SLIDE_STATUSES]


def max_concurrent_slides(jobs: Dict[str, Any]) -> int:
    value = jobs.get("max_concurrent_slides", DEFAULT_MAX_CONCURRENT_SLIDES)
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid max_concurrent_slides: {value}") from exc
    if value < 1:
        raise ValueError("max_concurrent_slides must be >= 1")
    return value


def dispatch_slots_available(jobs: Dict[str, Any]) -> int:
    return max(0, max_concurrent_slides(jobs) - len(active_slides(jobs)))


def update_jobs_run_status(jobs: Dict[str, Any]) -> None:
    slides = jobs.get("slides", [])
    if slides and all(slide.get("status") in {"dispatched", "recorded", "accepted"} for slide in slides):
        jobs["run_status"] = "slides_dispatched"
    if slides and all(slide.get("status") in {"recorded", "accepted"} for slide in slides):
        jobs["run_status"] = "slides_recorded"
    if slides and all(slide.get("status") in TERMINAL_SLIDE_STATUSES for slide in slides):
        if any(slide.get("status") == "blocked" for slide in slides):
            jobs["run_status"] = "blocked"
    jobs["updated_at"] = now_iso()


def slide_ids(slides: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(slide.get("slide_id")) for slide in slides]
