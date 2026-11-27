"""Offline regressions for selected-reference binding and recoverable generation.

Images, call records and observations are synthetic protocol fixtures, not
evidence of an actual provider request or visual approval.
"""
import copy
import hashlib
import json
import runpy

import pytest
from generation_delivery import CONTRACT, REVIEW, generation_helpers, review
from PIL import Image
from test_generate_backend import (
    ROOT,
    deck_spec,
    invoke,
    run_pipeline,
    write_generation_record,
    write_slide_image,
)
from test_generation_audit_followup import snapshot
from test_generation_delivery import fill_review, record_pages


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def record_one(root, deck, number, worker="synthetic-worker", *, dispatch=True):
    image = root / f"synthetic-source-{number}.png"
    write_slide_image(image)
    if dispatch:
        dispatched = invoke("--offline", "dispatch", deck, "--slide", number, "--agent-id", worker)
        assert dispatched.returncode == 0, dispatched.stderr
    recorded = invoke("--offline", "result", deck, "--slide", number, "--agent-id", worker,
                      "--backend-used", "built-in image tool", "--selected-source", image,
                      "--generation-record", write_generation_record(deck, number, image),
                      "--qa-note", "Synthetic protocol fixture; no model invocation")
    assert recorded.returncode == 0, recorded.stderr


def raw_style_deck(tmp_path, declaration=None):
    style = tmp_path / "style.png"
    Image.new("RGB", (1600, 900), "navy").save(style)
    spec = deck_spec("native-style")
    spec["slides"] = spec["slides"][:1]
    spec["approved_style_reference"] = declaration if declaration is not None else {"path": style.name, "role": "style only"}
    path = tmp_path / "deck_spec.json"
    write(path, spec)
    deck = tmp_path / spec["deck_name"]
    return path, deck, style, invoke("--offline", "prepare", "--spec", path, "--out-dir", deck)


@pytest.mark.parametrize("gate", ["dispatch", "result", "review", "assemble"])
def test_native_spec_reference_is_bound_and_rechecked_at_every_gate(tmp_path, gate):
    _, deck, style, prepared = raw_style_deck(tmp_path)
    assert prepared.returncode == 0, prepared.stderr
    reference = read(deck / CONTRACT)["style_reference"]
    original_hash = hashlib.sha256(style.read_bytes()).hexdigest()
    assert reference["sha256"] == reference["source_sha256"] == original_hash
    assert reference["kind"] == "single-page"
    assert read(deck / "prompts/slide_01.json")["input_images"][0]["sha256"] == original_hash
    if gate == "result":
        assert invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "worker").returncode == 0
    elif gate in {"review", "assemble"}:
        record_one(tmp_path, deck, 1)
        fill_review(deck)
        assert review(deck, deck / REVIEW)["status"] == "pass"
    Image.new("RGB", (1600, 900), "red").save(style)
    if gate == "dispatch":
        result = invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "worker")
    elif gate == "result":
        image = tmp_path / "synthetic-result.png"
        write_slide_image(image)
        result = invoke("--offline", "result", deck, "--slide", 1, "--agent-id", "worker",
                        "--backend-used", "built-in image tool", "--selected-source", image,
                        "--generation-record", write_generation_record(deck, 1, image), "--qa-note", "Synthetic fixture")
    elif gate == "review":
        result = invoke("--offline", "review", deck)
    else:
        result = invoke("--offline", "assemble", tmp_path, deck.name + ".pptx")
    assert result.returncode != 0 and "reference changed or missing" in result.stderr
    assert not (deck / (deck.name + ".pptx")).exists()


@pytest.mark.parametrize("declaration", [
    {"path": "https://example.invalid/style.png"},
    {"path": "missing.png"},
    {"path": "style.png", "sha256": "0" * 64},
    {},
])
def test_native_spec_cannot_prepare_an_unbound_style_reference(tmp_path, declaration):
    _, deck, _, result = raw_style_deck(tmp_path, declaration)
    assert result.returncode != 0
    assert not (deck / "slide_jobs.json").exists()


def test_force_preserves_unchanged_completion_contract_and_review(tmp_path):
    deck = record_pages(tmp_path, custom_prompt=True)
    fill_review(deck)
    before = read(deck / "slide_jobs.json")
    contract_before = (deck / CONTRACT).read_bytes()
    review_before = (deck / REVIEW).read_bytes()
    spec = read(tmp_path / "deck_spec.json")
    spec["max_concurrent_slides"] = 2  # Scheduling metadata does not change page approval.
    write(tmp_path / "deck_spec.json", spec)
    result = invoke("--offline", "prepare", "--spec", tmp_path / "deck_spec.json", "--out-dir", deck, "--force")
    assert result.returncode == 0, result.stderr
    after = read(deck / "slide_jobs.json")
    assert after["slides"] == before["slides"]
    assert (deck / CONTRACT).read_bytes() == contract_before
    assert (deck / REVIEW).read_bytes() == review_before
    assert review(deck, deck / REVIEW)["status"] == "pass"
    assert after["run_status"] == read(deck / "slide_run_state.json")["status"] == "slides_recorded"
    assert "preparation_history" not in after


@pytest.mark.parametrize("remove", [False, True])
def test_force_archives_replaced_work_and_reuses_unchanged_page(tmp_path, remove):
    deck = record_pages(tmp_path)
    fill_review(deck)
    old_jobs = read(deck / "slide_jobs.json")
    old_prompt = (deck / "prompts/slide_02.json").read_bytes()
    old_pixels = (deck / "origin_image/slide_02.png").read_bytes()
    old_review = (deck / REVIEW).read_bytes()
    source = tmp_path / "deck_spec.json"
    spec = read(source)
    if remove:
        spec["slides"].pop()
    else:
        spec["slides"][1]["title"] = "Updated approved evidence title"
    write(source, spec)
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck, "--force")
    assert result.returncode == 0, result.stderr
    jobs = read(deck / "slide_jobs.json")
    assert jobs["slides"][0] == old_jobs["slides"][0]
    archived = deck / jobs["preparation_history"][-1]["directory"]
    assert read(archived / "slide_jobs.json") == old_jobs
    assert (archived / "prompts/slide_02.json").read_bytes() == old_prompt
    assert (archived / "origin_image/slide_02.png").read_bytes() == old_pixels
    assert (archived / REVIEW).read_bytes() == old_review
    assert not (deck / REVIEW).exists()
    if remove:
        assert not (deck / "origin_image/slide_02.png").exists()
        assert not (deck / "prompts/slide_02.json").exists()
    else:
        assert jobs["slides"][1]["status"] == "pending" and jobs["slides"][1]["result"] is None
        record_one(tmp_path, deck, 2)
    fill_review(deck)
    assert review(deck, deck / REVIEW)["status"] == "pass"
    assembled = invoke("--offline", "assemble", tmp_path, deck.name + ".pptx")
    assert assembled.returncode == 0, assembled.stderr


@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_force_refuses_to_archive_missing_or_replaced_completed_outputs(tmp_path, remove, missing):
    deck = record_pages(tmp_path)
    fill_review(deck)
    source = tmp_path / "deck_spec.json"
    spec = read(source)
    if remove:
        spec["slides"].pop()
    else:
        spec["slides"][1]["title"] = "Updated approved evidence title"
    write(source, spec)
    image = deck / "origin_image/slide_02.png"
    if missing:
        image.unlink()
    else:
        Image.new("RGB", (1600, 900), "red").save(image)
    before = snapshot(deck)
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck, "--force")
    assert result.returncode != 0 and "Completed slide image changed or missing" in result.stderr
    assert snapshot(deck) == before


def test_force_does_not_reset_a_blocked_page_or_destroy_completed_sibling(tmp_path):
    deck = run_pipeline(tmp_path)
    record_one(tmp_path, deck, 1)
    assert invoke("--offline", "blocker", deck, "--slide", 2, "--reason", "Synthetic temporary outage").returncode == 0
    before = read(deck / "slide_jobs.json")["slides"]
    result = invoke("--offline", "prepare", "--spec", tmp_path / "deck_spec.json", "--out-dir", deck, "--force")
    assert result.returncode == 0, result.stderr
    assert read(deck / "slide_jobs.json")["slides"] == before
    assert [slide["status"] for slide in before] == ["recorded", "blocked"]


@pytest.mark.parametrize("previous_status", ["pending", "blocked", "recorded"])
def test_force_applies_an_explicit_provided_sample_and_archives_previous_origin(tmp_path, previous_status):
    deck = run_pipeline(tmp_path)
    if previous_status == "blocked":
        assert invoke("--offline", "blocker", deck, "--slide", 1, "--reason", "Synthetic unavailable provider").returncode == 0
    elif previous_status == "recorded":
        record_one(tmp_path, deck, 1)
    image = deck / "origin_image/slide_01.png"
    if not image.exists():
        write_slide_image(image)
    before = read(deck / "slide_jobs.json")
    source = tmp_path / "deck_spec.json"
    spec = read(source)
    spec["slides"][0].update(sample_approved=True, image_origin={
        "kind": "provided", "source_ref": "Synthetic user-supplied sample",
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
    write(source, spec)
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck, "--force")
    assert result.returncode == 0, result.stderr
    jobs = read(deck / "slide_jobs.json")
    slide = jobs["slides"][0]
    assert slide["status"] == "accepted" and slide["result"]["source_kind"] == "provided"
    assert slide["result"]["source_ref"] == "Synthetic user-supplied sample"
    assert jobs["slides"][1] == before["slides"][1]
    archive = deck / jobs["preparation_history"][-1]["directory"]
    assert read(archive / "slide_jobs.json")["slides"][0] == before["slides"][0]
    unchanged = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck, "--force")
    assert unchanged.returncode == 0, unchanged.stderr
    assert read(deck / "slide_jobs.json")["slides"][0] == slide


@pytest.mark.parametrize("artifact", [REVIEW, "speech.md"])
def test_preparation_archive_identity_includes_independent_observations(tmp_path, monkeypatch, artifact):
    script = ROOT / "vendor/codex-ppt/skills/codex-ppt/scripts/prepare_slide_prompts.py"
    monkeypatch.syspath_prepend(str(script.parent))
    archive = runpy.run_path(str(script))["_archive_previous_preparation"]
    jobs = {"slides": [], "updated_at": "same synthetic instant"}
    write(tmp_path / "slide_jobs.json", jobs)
    (tmp_path / artifact).write_bytes(b"first synthetic observation")
    first_files = {}
    first = archive(tmp_path, jobs, first_files)
    for name, raw in first_files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (tmp_path / artifact).write_bytes(b"second synthetic observation")
    second_files = {}
    second = archive(tmp_path, jobs, second_files)
    assert second["jobs_sha256"] == first["jobs_sha256"]
    assert second["directory"] != first["directory"]
    assert (tmp_path / first["directory"] / artifact).read_bytes() == b"first synthetic observation"
    assert second_files[f"{second['directory']}/{artifact}"] == b"second synthetic observation"
    assert archive(tmp_path, jobs, {})["directory"] == second["directory"]


def test_removing_a_page_cannot_delete_a_still_selected_style_reference(tmp_path):
    deck = record_pages(tmp_path)
    spec = read(tmp_path / "deck_spec.json")
    spec["slides"].pop()
    spec["approved_style_reference"] = {"path": str(deck / "origin_image/slide_02.png"), "role": "style only"}
    write(tmp_path / "deck_spec.json", spec)
    before = snapshot(deck)
    result = invoke("--offline", "prepare", "--spec", tmp_path / "deck_spec.json", "--out-dir", deck, "--force")
    assert result.returncode != 0 and "still an input reference" in result.stderr
    assert snapshot(deck) == before


def test_retry_keeps_completed_sibling_and_archives_actual_blocked_attempt(tmp_path):
    deck = run_pipeline(tmp_path)
    record_one(tmp_path, deck, 1)
    assert invoke("--offline", "dispatch", deck, "--slide", 2, "--agent-id", "failed-worker").returncode == 0
    assert invoke("--offline", "blocker", deck, "--slide", 2, "--agent-id", "failed-worker",
                  "--reason", "Synthetic temporary tool outage").returncode == 0
    before = read(deck / "slide_jobs.json")
    contract_before = (deck / CONTRACT).read_bytes()
    result = invoke("--offline", "retry", deck, "--slide", 2, "--reason", "Synthetic tool recovered")
    assert result.returncode == 0, result.stderr
    after = read(deck / "slide_jobs.json")
    assert after["slides"][0] == before["slides"][0]
    retried = after["slides"][1]
    assert retried["status"] == "pending" and retried["dispatch"] is None and retried["blocker"] is None
    attempt = retried["attempt_history"][-1]
    assert attempt["previous"] == before["slides"][1]
    assert (deck / attempt["snapshots"]["job"]).read_bytes() == (deck / "prompts/slide_02.json").read_bytes()
    assert (deck / CONTRACT).read_bytes() == contract_before
    record_one(tmp_path, deck, 2, worker="retry-worker")
    fill_review(deck)
    assert review(deck, deck / REVIEW)["status"] == "pass"
    assert invoke("--offline", "assemble", tmp_path, deck.name + ".pptx").returncode == 0


def test_retry_while_sibling_is_active_respects_dispatch_slots(tmp_path):
    spec = deck_spec("limited-retry")
    spec["max_concurrent_slides"] = 1
    source = tmp_path / "deck_spec.json"
    write(source, spec)
    deck = tmp_path / spec["deck_name"]
    assert invoke("--offline", "prepare", "--spec", source, "--out-dir", deck).returncode == 0
    assert invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "first").returncode == 0
    assert invoke("--offline", "blocker", deck, "--slide", 1, "--reason", "Synthetic timeout").returncode == 0
    assert invoke("--offline", "dispatch", deck, "--slide", 2, "--agent-id", "active").returncode == 0
    active = copy.deepcopy(read(deck / "slide_jobs.json")["slides"][1])
    assert invoke("--offline", "retry", deck, "--slide", 1, "--reason", "Synthetic recovery").returncode == 0
    assert read(deck / "slide_jobs.json")["slides"][1] == active
    result = invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "retry-worker")
    assert result.returncode != 0 and "No dispatch slots" in result.stderr


@pytest.mark.parametrize("status", ["pending", "dispatched", "recorded"])
def test_retry_refuses_pages_that_are_not_blocked_without_mutating_them(tmp_path, status):
    deck = run_pipeline(tmp_path)
    if status == "recorded":
        record_one(tmp_path, deck, 1)
    elif status == "dispatched":
        assert invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "worker").returncode == 0
    before = snapshot(deck)
    result = invoke("--offline", "retry", deck, "--slide", 1, "--reason", "Synthetic retry")
    assert result.returncode != 0 and "must be blocked" in result.stderr
    assert snapshot(deck) == before


def test_preparation_transaction_restores_removed_files_and_discards_partial_archive(tmp_path, monkeypatch):
    helpers = generation_helpers()
    (tmp_path / "old.png").write_bytes(b"retained original")
    (tmp_path / "jobs.json").write_bytes(b"old state")
    scope = helpers["commit_preparation"].__globals__
    original_write = scope["_write_bytes"]

    def fail_new_jobs(path, raw):
        if path.name == "jobs.json" and raw == b"new state":
            raise OSError("Synthetic disk failure")
        original_write(path, raw)

    monkeypatch.setitem(scope, "_write_bytes", fail_new_jobs)
    with helpers["preparation_lock"](tmp_path), pytest.raises(OSError, match="Synthetic"):
        helpers["commit_preparation"](tmp_path, {
            ".generation-history/old.png": b"retained original", "old.png": None, "jobs.json": b"new state"})
    assert (tmp_path / "old.png").read_bytes() == b"retained original"
    assert (tmp_path / "jobs.json").read_bytes() == b"old state"
    assert not (tmp_path / ".generation-history/old.png").exists()
