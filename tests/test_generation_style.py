"""Offline style-reference protocol tests; fixtures are not real model results."""
import copy
import hashlib
import json

import pytest
from generation_delivery import CONTRACT, REVIEW, from_page_spec, review
from page_production import execute, workspace
from PIL import Image, ImageDraw
from style_reference import create_reference, resolve_reference
from test_generate_backend import (
    ROOT,
    invoke,
    write_generation_record,
    write_slide_image,
)
from test_generation_delivery import fill_review


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def selected_spec(tmp_path, count=1):
    spec = read(ROOT / "examples/page-spec.example.json")
    spec["content_policy"] = "1.1"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "Synthetic test outline; not an actual user artifact"}
    spec["style"].update(option=2, choice="Synthetic selected style")
    spec["style"]["tokens"]["reference_images"] = ["selected-overview.png"]
    overview = Image.new("RGB", (1600, 900), "ivory")
    ImageDraw.Draw(overview).rectangle((80, 120, 559, 389), fill="navy")
    overview.save(tmp_path / "selected-overview.png")
    for index in range(2, count + 1):
        page = copy.deepcopy(spec["slides"][0])
        page.update(id=f"s{index:02d}", page_number=index, image_file=f"slides/{index:02d}.png")
        spec["slides"].append(page)
    for page in spec["slides"]:
        page["generation_prompt"] = "OLD SIX-PAGE PREVIEW INSTRUCTION"
    path = tmp_path / "page-spec.json"
    write(path, spec)
    create_reference(path, "single-page-reference.png", box=[80, 120, 480, 270])
    return path


def prepared(tmp_path, count=1):
    path = selected_spec(tmp_path, count)
    deck = tmp_path / "deck"
    result = invoke("--offline", "prepare", "--page-spec", path, "--out-dir", deck)
    assert result.returncode == 0, result.stdout + result.stderr
    return path, deck


def dispatch(deck):
    result = invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "synthetic-worker")
    assert result.returncode == 0, result.stderr


def record(deck, source):
    return invoke("--offline", "result", deck, "--slide", 1, "--agent-id", "synthetic-worker",
                  "--backend-used", "built-in image tool", "--selected-source", source,
                  "--generation-record", write_generation_record(deck, 1, source),
                  "--qa-note", "Synthetic protocol fixture; no model invocation or visual approval")


def recorded(tmp_path):
    path, deck = prepared(tmp_path)
    source = tmp_path / "synthetic-output.png"
    write_slide_image(source)
    dispatch(deck)
    result = record(deck, source)
    assert result.returncode == 0, result.stderr
    return path, deck


def test_every_job_keeps_the_selected_single_page_baseline_and_both_hashes(tmp_path):
    path, deck = prepared(tmp_path, count=3)
    reference = resolve_reference(read(path), path.parent, required=True)
    jobs, contract = read(deck / "slide_jobs.json"), read(deck / CONTRACT)
    assert jobs["style_reference"] == contract["style_reference"] == reference
    assert contract["style_consistency_policy"] == "1.0"
    for entry, page in zip(jobs["slides"], contract["pages"]):
        job = read(deck / entry["job"])
        assert job["style_reference"] == reference
        assert job["requires_context_images"] is True
        assert len(job["input_images"]) == 1
        assert job["input_images"] == entry["input_images"] == page["input_images"]
        assert job["input_images"][0]["path"] == reference["path"]
        assert job["input_images"][0]["sha256"] == reference["sha256"]
        assert reference["source_path"] not in job["prompt"]
        assert "OLD SIX-PAGE PREVIEW INSTRUCTION" not in job["prompt"]
        assert "layout family" in job["prompt"]
        assert page["job_sha256"] == hashlib.sha256((deck / entry["job"]).read_bytes()).hexdigest()


def test_generate_and_produce_use_the_same_selected_reference_bytes(tmp_path):
    path, deck = prepared(tmp_path)
    state = execute(path, "request", slide_id="s01", route="isolated-api")
    page = state["pages"]["s01"]
    packet = read(workspace(path) / page["request_snapshot"])
    generated = read(deck / "prompts/slide_01.json")["style_reference"]
    for key in ("sha256", "source_sha256", "kind", "box", "option", "choice"):
        assert packet["style_reference"][key] == generated[key]
    assert hashlib.sha256((workspace(path) / packet["style_reference"]["reference_snapshot"]).read_bytes()).hexdigest() == generated["sha256"]


@pytest.mark.parametrize("policy", ["1.0", "1.1"])
def test_selected_overview_cannot_fall_back_to_text_or_be_attached_whole(tmp_path, policy):
    path = selected_spec(tmp_path)
    spec = read(path)
    spec["content_policy"] = policy
    spec["style"].pop("generation_reference")
    write(path, spec)
    result = invoke("--offline", "prepare", "--page-spec", path, "--out-dir", tmp_path / "deck")
    assert result.returncode != 0 and "style-reference" in result.stderr
    assert not (tmp_path / "deck/slide_jobs.json").exists()


def test_locked_existing_single_page_is_preserved_as_the_first_image(tmp_path):
    path = selected_spec(tmp_path)
    spec = read(path)
    spec["style"].pop("generation_reference")
    spec["style"].update(decision="locked-reference")
    spec["style"]["tokens"]["reference_images"] = ["single-page-reference.png"]
    write(path, spec)
    result = invoke("--offline", "prepare", "--page-spec", path, "--out-dir", tmp_path / "deck")
    assert result.returncode == 0, result.stderr
    job = read(tmp_path / "deck/prompts/slide_01.json")
    reference = job["style_reference"]
    assert reference["kind"] == "single-page"
    assert reference["path"] == reference["source_path"] == str(tmp_path / "single-page-reference.png")
    assert reference["sha256"] == reference["source_sha256"]
    assert job["input_images"][0]["path"] == reference["path"]


@pytest.mark.parametrize("change", ["disable", "overview"])
def test_raw_adapter_jobs_cannot_disable_or_attach_the_selected_overview(tmp_path, change):
    path = selected_spec(tmp_path)
    spec = from_page_spec(path)
    if change == "disable":
        spec["slides"][0]["use_approved_style_reference"] = False
    else:
        spec["slides"][0]["required_images"] = [{"path": str(tmp_path / "selected-overview.png")}]
    source = tmp_path / "adapted.json"
    write(source, spec)
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", tmp_path / "deck")
    assert result.returncode != 0 and "style" in result.stderr.lower()
    assert not (tmp_path / "deck/slide_jobs.json").exists()


@pytest.mark.parametrize("changed", ["selected-overview.png", "single-page-reference.png"])
@pytest.mark.parametrize("gate", ["dispatch", "result", "review", "assemble"])
def test_changed_selection_or_derived_reference_invalidates_existing_jobs(tmp_path, changed, gate):
    _, deck = prepared(tmp_path)
    source = tmp_path / "synthetic-output.png"
    write_slide_image(source)
    if gate != "dispatch":
        dispatch(deck)
    if gate in {"review", "assemble"}:
        result = record(deck, source)
        assert result.returncode == 0, result.stderr
    if gate == "assemble":
        fill_review(deck)
        assert review(deck, deck / REVIEW)["status"] == "pass"
        (deck / "deck.pptx").write_bytes(b"previous delivery")
    Image.new("RGB", (1600, 900), "red").save(tmp_path / changed)
    if gate == "dispatch":
        failed = invoke("--offline", gate, deck, "--slide", 1, "--agent-id", "synthetic-worker")
    elif gate == "result":
        failed = record(deck, source)
    elif gate == "review":
        failed = invoke("--offline", gate, deck, "--init")
    else:
        failed = invoke("--offline", gate, tmp_path, "deck.pptx")
    assert failed.returncode != 0 and "style reference changed" in failed.stderr.lower()
    if gate == "assemble":
        assert (deck / "deck.pptx").read_bytes() == b"previous delivery"


@pytest.mark.parametrize("problem", ["missing", "flag-only", "blank-observation", "wrong-target", "wrong-hash", "missing-binding"])
def test_style_review_requires_actual_observations_and_correct_reference_identity(tmp_path, problem):
    _, deck = recorded(tmp_path)
    fill_review(deck)
    assert review(deck, deck / REVIEW)["status"] == "pass"
    value = read(deck / REVIEW)
    page = value["slides"][0]
    if problem == "missing":
        page["checks"].pop("style_consistency")
    elif problem == "flag-only":
        page["checks"]["style_consistency"] = "pass"
    elif problem == "blank-observation":
        page["checks"]["style_consistency"]["notes"] = " "
    elif problem == "wrong-target":
        page["checks"]["style_consistency"]["targets"] = ["unrelated"]
    elif problem == "wrong-hash":
        page["style_reference"]["source_sha256"] = "0" * 64
    else:
        page.pop("style_reference")
    write(deck / REVIEW, value)
    if problem in {"wrong-hash", "missing-binding"}:
        with pytest.raises(ValueError, match="style review must bind"):
            review(deck, deck / REVIEW)
    else:
        assert review(deck, deck / REVIEW)["status"] == "incomplete_or_failed"
