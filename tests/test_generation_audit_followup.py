"""Synthetic offline regressions for preparation and delivery audit findings."""
import base64
import copy
import hashlib
import io
import json
import subprocess
import sys

import pytest
from generation_delivery import CONTRACT, REVIEW, generation_helpers, review
from PIL import Image, ImageDraw, ImageOps
from pptx import Presentation
from test_generate_backend import (
    ROOT,
    deck_spec,
    invoke,
    run_pipeline,
    write_generation_record,
    write_slide_image,
)
from test_generation_delivery import fill_review


def snapshot(deck):
    return {path.relative_to(deck).as_posix(): path.read_bytes() for path in deck.rglob("*")
            if path.is_file() and not path.name.endswith(".lock")}


def test_prepare_preserves_remote_references_and_resolves_local_images(tmp_path):
    spec = deck_spec()
    Image.new("RGB", (1600, 900), "navy").save(tmp_path / "style.png")
    spec["approved_style_reference"] = {"path": "style.png", "role": "style-only"}
    spec["slides"][0]["required_images"] = [
        {"path": "https://example.invalid/figure.png", "role": "strict input asset"},
        {"path": "assets/local.png", "role": "local evidence"},
        "![Remote evidence](https://example.invalid/markdown.png)",
    ]
    source = tmp_path / "spec.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    deck = tmp_path / "deck"
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck)
    assert result.returncode == 0, result.stderr
    images = json.loads((deck / "prompts/slide_01.json").read_text(encoding="utf-8"))["input_images"]
    assert [image["path"] for image in images] == [
        str((tmp_path / "style.png").resolve()), "https://example.invalid/figure.png",
        str((tmp_path / "assets/local.png").resolve()), "https://example.invalid/markdown.png",
    ]


@pytest.mark.parametrize("direct_vendor", [False, True])
def test_failed_force_prepare_retains_entire_previous_group(tmp_path, direct_vendor):
    deck = run_pipeline(tmp_path)
    source = tmp_path / "deck_spec.json"
    spec = json.loads(source.read_text(encoding="utf-8"))
    spec["slides"][0].update(title="Proposed replacement", speaker_notes="Proposed note")
    spec["slides"][1]["required_images"] = ["invalid-plain-path.png"]
    source.write_text(json.dumps(spec), encoding="utf-8")
    previous = snapshot(deck)
    arguments = ["--spec", source, "--out-dir", deck, "--force"]
    if direct_vendor:
        script = ROOT / "vendor/codex-ppt/skills/codex-ppt/scripts/prepare_slide_prompts.py"
        result = subprocess.run([sys.executable, str(script), *map(str, arguments)], capture_output=True, encoding="utf-8", check=False)
    else:
        result = invoke("--offline", "prepare", *arguments)
    assert result.returncode != 0 and "required_images" in result.stderr
    assert snapshot(deck) == previous


def test_force_prepare_cannot_replace_active_worker_inputs(tmp_path):
    deck = run_pipeline(tmp_path)
    assert invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "worker").returncode == 0
    source = tmp_path / "deck_spec.json"
    spec = json.loads(source.read_text(encoding="utf-8"))
    spec["slides"][0]["title"] = "Proposed replacement"
    source.write_text(json.dumps(spec), encoding="utf-8")
    previous = snapshot(deck)
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck, "--force")
    assert result.returncode != 0 and "dispatched" in result.stderr
    assert snapshot(deck) == previous
    original = tmp_path / "synthetic.png"
    write_slide_image(original)
    recorded = invoke("--offline", "result", deck, "--slide", 1, "--agent-id", "worker",
                      "--backend-used", "built-in image tool", "--selected-source", original,
                      "--generation-record", write_generation_record(deck, 1, original), "--qa-note", "SYNTHETIC fixture")
    assert recorded.returncode == 0, recorded.stderr


def test_successful_force_prepare_commits_matching_prompts_contract_and_notes(tmp_path):
    deck = run_pipeline(tmp_path)
    source = tmp_path / "deck_spec.json"
    spec = json.loads(source.read_text(encoding="utf-8"))
    spec["slides"][0].update(title="Updated approved title", speaker_notes="Updated approved note")
    source.write_text(json.dumps(spec), encoding="utf-8")
    result = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck, "--force")
    assert result.returncode == 0, result.stderr
    jobs = json.loads((deck / "slide_jobs.json").read_text(encoding="utf-8"))
    contract = json.loads((deck / CONTRACT).read_text(encoding="utf-8"))
    for job, page in zip(jobs["slides"], contract["pages"]):
        assert page["job_sha256"] == hashlib.sha256((deck / job["job"]).read_bytes()).hexdigest()
    assert contract["pages"][0]["content"]["title"] == "Updated approved title"
    assert "Updated approved note" in (deck / "speech.md").read_text(encoding="utf-8")
    assert not (deck / ".slide_prepare_transaction.json").exists()


def test_mid_commit_io_failure_restores_all_previous_files(tmp_path, monkeypatch):
    helpers = generation_helpers()
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "one.json").write_bytes(b"old-one")
    (deck / "two.json").write_bytes(b"old-two")
    scope = helpers["commit_preparation"].__globals__
    original_write = scope["_write_bytes"]
    calls = []

    def fail_once(path, data):
        calls.append(path.name)
        if len(calls) == 3:
            raise OSError("Synthetic interrupted replacement")
        original_write(path, data)

    monkeypatch.setitem(scope, "_write_bytes", fail_once)
    with helpers["preparation_lock"](deck), pytest.raises(OSError, match="Synthetic"):
        helpers["commit_preparation"](deck, {"one.json": b"new-one", "new.json": b"new", "two.json": b"new-two"})
    assert snapshot(deck) == {"one.json": b"old-one", "two.json": b"old-two"}


def test_status_recovers_interrupted_preparation_before_reading_jobs(tmp_path):
    deck = run_pipeline(tmp_path)
    previous = snapshot(deck)
    names = ["slide_jobs.json", "prompts/slide_01.json", "uncommitted.json"]
    (deck / ".slide_prepare_transaction.json").write_text(json.dumps({"version": "1.0", "previous": {
        name: base64.b64encode(previous[name]).decode() if name in previous else None for name in names
    }}), encoding="utf-8")
    for name in names:
        (deck / name).write_bytes(b"partial synthetic replacement")
    result = invoke("--offline", "status", deck, "--json")
    assert result.returncode == 0, result.stderr
    assert snapshot(deck) == previous


def model_fixture(tmp_path, *, method=None, canvas=None):
    spec = deck_spec("model-fixture")
    spec["slides"] = spec["slides"][:1]
    if method is not None:
        spec["sample_generation_method"] = copy.deepcopy(method)
    if canvas is not None:
        spec["canvas"] = canvas
    source = tmp_path / "spec.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    deck = tmp_path / spec["deck_name"]
    prepared = invoke("--offline", "prepare", "--spec", source, "--out-dir", deck)
    assert prepared.returncode == 0, prepared.stderr
    assert invoke("--offline", "dispatch", deck, "--slide", 1, "--agent-id", "worker").returncode == 0
    return deck


def record_model(deck, source, model):
    record = write_generation_record(deck, 1, source)
    value = json.loads(record.read_text(encoding="utf-8"))
    value["model"] = model
    record.write_text(json.dumps(value), encoding="utf-8")
    return invoke("--offline", "result", deck, "--slide", 1, "--agent-id", "worker",
                  "--backend-used", "built-in image tool", "--selected-source", source,
                  "--generation-record", record, "--qa-note", "SYNTHETIC protocol fixture; not actual visual approval")


@pytest.mark.parametrize("actual", [None, "gpt-image-2", "gpt-image-1.5"])
def test_result_rejects_unknown_or_different_explicit_sample_model(tmp_path, actual):
    deck = model_fixture(tmp_path, method={"backend_used": "built-in image tool", "model": "gpt-image-2.6"})
    source = tmp_path / "synthetic.png"
    write_slide_image(source)
    previous = snapshot(deck)
    result = record_model(deck, source, actual)
    assert result.returncode != 0 and "model" in result.stderr.lower()
    assert snapshot(deck) == previous


def test_method_match_only_claims_properties_supported_by_call_record(tmp_path):
    deck = model_fixture(tmp_path, method={"backend_used": "built-in image tool", "model": "gpt-image-2.6", "mode": "generate"})
    source = tmp_path / "synthetic.png"
    write_slide_image(source)
    result = record_model(deck, source, "openai/gpt-image-2.6/text-to-image")
    assert result.returncode == 0, result.stderr
    recorded = json.loads((deck / "slide_jobs.json").read_text(encoding="utf-8"))["slides"][0]["result"]
    assert recorded["sample_generation_method_matched"] is False
    assert recorded["unverified_sample_method_fields"] == ["mode"]


def test_review_and_assembly_recheck_recorded_model_against_approved_sample(tmp_path):
    deck = model_fixture(tmp_path, method={"backend_used": "built-in image tool", "model": "gpt-image-2.6"})
    source = tmp_path / "synthetic.png"
    write_slide_image(source)
    assert record_model(deck, source, "gpt-image-2.6").returncode == 0
    fill_review(deck)
    jobs_path = deck / "slide_jobs.json"
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs["slides"][0]["result"]["generation_record"]["model"] = "gpt-image-2"
    jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
    with pytest.raises(ValueError, match="Model mismatch"):
        review(deck, deck / REVIEW)
    target = deck / f"{deck.name}.pptx"
    target.write_bytes(b"previous delivery")
    result = invoke("--offline", "assemble", tmp_path, target.name)
    assert result.returncode != 0 and "Model mismatch" in result.stderr
    assert target.read_bytes() == b"previous delivery"


@pytest.mark.parametrize("size", [(16, 9), (2560, 1439), (2559, 1440)])
def test_review_rejects_recorded_image_below_declared_canvas(tmp_path, size):
    deck = model_fixture(tmp_path, canvas={"width": 2560, "height": 1440})
    source = tmp_path / "synthetic.png"
    write_slide_image(source, size)
    assert record_model(deck, source, None).returncode == 0
    with pytest.raises(ValueError, match="resolution"):
        review(deck, deck / REVIEW, initialize=True)
    assert not (deck / REVIEW).exists()


@pytest.mark.parametrize("orientation,mode", [(n, "RGB") for n in range(2, 9)] + [(6, "CMYK")])
def test_generation_assembly_applies_exif_without_changing_original(tmp_path, orientation, mode):
    deck = model_fixture(tmp_path, canvas={"width": 1600, "height": 900})
    source = tmp_path / "synthetic.jpg"
    width, height = (900, 1600) if orientation >= 5 else (1600, 900)
    image = Image.new("RGB", (width, height), "navy")
    ImageDraw.Draw(image).rectangle((0, 0, width // 3, height // 4), fill="yellow")
    image = image.convert(mode)
    exif = Image.Exif()
    exif[274] = orientation
    image.save(source, format="JPEG", exif=exif)
    original = source.read_bytes()
    assert record_model(deck, source, None).returncode == 0
    fill_review(deck)
    result = invoke("--offline", "assemble", tmp_path, f"{deck.name}.pptx")
    assert result.returncode == 0, result.stderr
    presentation = Presentation(deck / f"{deck.name}.pptx")
    with Image.open(io.BytesIO(presentation.slides[0].shapes[0].image.blob)) as embedded, Image.open(source) as image:
        expected = ImageOps.exif_transpose(image)
        assert embedded.size == expected.size == (1600, 900)
        assert embedded.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
    assert source.read_bytes() == original
    assert (deck / "origin_image/slide_01.png").read_bytes() == original
