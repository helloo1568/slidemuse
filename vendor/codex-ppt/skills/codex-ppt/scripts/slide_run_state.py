#!/usr/bin/env python3
"""State helpers for codex-ppt slide generation runs."""

from __future__ import annotations

import hashlib
import base64
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
PREPARATION_JOURNAL = ".slide_prepare_transaction.json"


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


def _prepared_path(deck_dir: Path, relative: str) -> Path:
    path = Path(relative)
    root = Path(deck_dir).resolve()
    if path.is_absolute() or not relative or ".." in path.parts:
        raise ValueError("Preparation outputs must remain inside the deck")
    target = root / path
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError("Preparation output is a symlink or escapes the deck")
    if target.exists() and not target.is_file():
        raise ValueError(f"Preparation output is not a regular file: {relative}")
    for parent in target.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Preparation output parent is not a directory: {relative}")
        if parent == root:
            break
    return target


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def recover_preparation(deck_dir: Path) -> None:
    """Rollback an uncommitted file group while holding the jobs lock."""
    journal = Path(deck_dir) / PREPARATION_JOURNAL
    if not journal.exists():
        return
    state = read_json(journal)
    if state.get("version") != "1.0" or not isinstance(state.get("previous"), dict):
        raise ValueError("Invalid preparation recovery journal; retain it for recovery")
    previous = []
    for relative, encoded in state["previous"].items():
        target = _prepared_path(deck_dir, relative)
        if target == journal or target.name.endswith(".lock"):
            raise ValueError("Invalid preparation recovery target")
        previous.append((target, None if encoded is None else base64.b64decode(encoded, validate=True)))
    for target, data in previous:
        if data is None:
            target.unlink(missing_ok=True)
        else:
            _write_bytes(target, data)
    journal.unlink()


@contextmanager
def preparation_lock(deck_dir: Path):
    deck_dir = Path(deck_dir)
    deck_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(deck_dir / ".slide_jobs.json.lock")):
        recover_preparation(deck_dir)
        yield


def commit_preparation(deck_dir: Path, files: Dict[str, bytes]) -> None:
    """Commit validated prompts, jobs and companions as one recoverable group.

    Caller owns preparation_lock. Removing the recovery journal is the commit
    point; any interrupted or failed replacement restores the previous group.
    """
    previous = {}
    pending = []
    for relative, data in files.items():
        target = _prepared_path(deck_dir, relative)
        if relative == PREPARATION_JOURNAL or target.name.endswith(".lock") or not isinstance(data, bytes):
            raise ValueError("Invalid prepared output")
        previous[relative] = base64.b64encode(target.read_bytes()).decode("ascii") if target.exists() else None
        pending.append((target, data))
    journal = Path(deck_dir) / PREPARATION_JOURNAL
    write_json(journal, {"version": "1.0", "previous": previous})
    try:
        for target, data in pending:
            _write_bytes(target, data)
        journal.unlink()
    except BaseException:
        recover_preparation(deck_dir)
        raise


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


def normalized_model(value: str) -> str:
    """Normalize only the documented OpenAI provider/operation wrappers."""
    value = value.strip()
    if value.startswith("openai/gpt-image-"):
        value = value.removeprefix("openai/")
        for suffix in ("/text-to-image", "/edit"):
            value = value.removesuffix(suffix)
    return value


def sample_method(jobs: Dict[str, Any], prompt_job: Dict[str, Any]) -> Dict[str, Any]:
    methods = [value for value in (jobs.get("sample_generation_method"), prompt_job.get("sample_generation_method"))
               if value is not None]
    if any(not isinstance(value, dict) for value in methods):
        raise ValueError("Sample generation method must be an object")
    if methods and any(value != methods[0] for value in methods[1:]):
        raise ValueError("Sample generation method differs between jobs and the dispatched prompt")
    return methods[0] if methods else {}


def validate_generation_record(value: Any, *, slide_id: str, request_sha256: str,
                               source_sha256: str, backend: str, expected_model: str | None = None) -> None:
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
    if expected_model is not None:
        if not isinstance(expected_model, str) or not expected_model.strip():
            raise ValueError("Approved sample model must be a non-empty name or null")
        if value["model"] is None:
            raise ValueError(f"Cannot verify approved sample model {expected_model}: actual model was not exposed")
        if normalized_model(value["model"]) != normalized_model(expected_model):
            raise ValueError(f"Model mismatch: approved sample uses {expected_model}, actual record names {value['model']}")


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
    with preparation_lock(deck_dir):
        return read_json(slide_jobs_path(deck_dir))


def load_job_snapshot(deck_dir: Path):
    with preparation_lock(deck_dir):
        return (read_json(slide_jobs_path(deck_dir)),
                read_json(run_state_path(deck_dir), default={"status": "created", "history": []}))


def save_jobs(deck_dir: Path, jobs: Dict[str, Any]) -> None:
    write_json(slide_jobs_path(deck_dir), jobs)


@contextmanager
def locked_jobs(deck_dir: Path):
    with preparation_lock(deck_dir):
        jobs = read_json(slide_jobs_path(deck_dir))
        yield jobs
        write_json(slide_jobs_path(deck_dir), jobs)


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
