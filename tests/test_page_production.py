"""Synthetic protocol fixtures; these do not measure model output or human review quality."""
import copy
import json
from pathlib import Path

import pytest
from content_density import semantic_claims, validate_content, visible_text
from page_production import CHECKS, execute, workspace
from PIL import Image, ImageChops
from preserved_assets import expected_patch


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def production(tmp_path):
    spec = json.loads((Path(__file__).resolve().parents[1] / "examples/page-spec.example.json").read_text(encoding="utf-8"))
    spec["style"].pop("tokens", None)
    first = spec["slides"][0]
    second = copy.deepcopy(first)
    second.update(id="s02", page_number=2, image_file="slides/02.png")
    spec["slides"].append(second)
    source = tmp_path / "host.png"
    Image.new("RGB", (1600, 900), "#f0faf0").save(source)
    evidence = tmp_path / "evidence.png"
    Image.new("RGB", (160, 90), "navy").save(evidence)
    from page_production import digest
    first["elements"][2]["preserve_asset"] = {"file": evidence.name, "sha256": digest(evidence.read_bytes()), "region": [1000, 150, 480, 270]}
    path = tmp_path / "page-spec.json"
    write(path, spec)
    return path, source


def fixture_review(path, slide_id, record):
    execute(path, "review-init", slide_id=slide_id, record=record)
    value = json.loads(record.read_text(encoding="utf-8"))
    slide = next(s for s in json.loads(path.read_text(encoding="utf-8"))["slides"] if s["id"] == slide_id)
    value.update(reviewer="Synthetic test fixture", observed_text="\n".join(visible_text(slide)), viewed_pixels=[1600, 900])
    value["checks"] = {name: {"status": "pass", "notes": "Synthetic protocol fixture", "targets": ["page"]} for name in CHECKS}
    write(record, value)


def test_prepare_is_idempotent_and_does_not_reset_approved_pages(production, tmp_path):
    path, source = production
    execute(path, "prepare")
    execute(path, "compose", slide_id="s01", source=source)
    fixture_review(path, "s01", tmp_path / "review.json")
    execute(path, "accept", slide_id="s01", record=tmp_path / "review.json")
    before = (workspace(path) / "state.json").read_bytes()
    execute(path, "prepare")
    execute(path, "compose", slide_id="s01", source=source)
    assert (workspace(path) / "state.json").read_bytes() == before
    assert json.loads(path.read_text(encoding="utf-8"))["slides"][0]["image_status"] == "approved"
    notes_spec = json.loads(path.read_text(encoding="utf-8"))
    notes_spec["slides"][0]["speaker_notes"] = "Changed speaker notes must only require re-export"
    write(path, notes_spec)
    assert execute(path, "prepare")["pages"]["s01"]["status"] == "approved"
    assert json.loads(path.read_text(encoding="utf-8"))["slides"][0]["speaker_notes"] == notes_spec["slides"][0]["speaker_notes"]
    spec = json.loads(path.read_text(encoding="utf-8"))
    declaration = spec["slides"][0]["elements"][2]["preserve_asset"]
    with Image.open(tmp_path / spec["slides"][0]["image_file"]) as image:
        x, y, w, h = declaration["region"]
        assert not ImageChops.difference(image.crop((x, y, x + w, y + h)), expected_patch(tmp_path, declaration)).getbbox()


@pytest.mark.parametrize("mutation", ["ratio", "resolution", "asset", "pending-review", "changed-image", "stale-contract"])
def test_failure_preserves_previous_image_and_state(production, tmp_path, mutation):
    path, source = production
    execute(path, "compose", slide_id="s01", source=source)
    target = tmp_path / "slides/01-cover.png"
    before = target.read_bytes()
    state_before = (workspace(path) / "state.json").read_bytes()
    if mutation == "ratio":
        Image.new("RGB", (600, 500)).save(source)
    elif mutation == "resolution":
        Image.new("RGB", (160, 90)).save(source)
    elif mutation == "asset":
        Image.new("RGB", (160, 90), "red").save(tmp_path / "evidence.png")
    else:
        record = tmp_path / "review.json"
        if mutation == "pending-review":
            execute(path, "review-init", slide_id="s01", record=record)
        else:
            fixture_review(path, "s01", record)
        if mutation == "changed-image":
            target.write_bytes(before + b"changed")
            before = target.read_bytes()
        elif mutation == "stale-contract":
            spec = json.loads(path.read_text(encoding="utf-8"))
            spec["slides"][0]["title"] += " revised"
            write(path, spec)
    with pytest.raises(ValueError):
        if mutation in ("ratio", "resolution", "asset"):
            execute(path, "compose", slide_id="s01", source=source)
        else:
            execute(path, "accept", slide_id="s01", record=record)
    assert target.read_bytes() == before
    assert (workspace(path) / "state.json").read_bytes() == state_before


def test_upscale_disclosed_and_region_change_invalidates_only_affected_page(production, tmp_path):
    path, source = production
    Image.new("RGB", (800, 450), "white").save(source)
    for slide in ("s01", "s02"):
        execute(path, "compose", slide_id=slide, source=source, allow_upscale=True)
        fixture_review(path, slide, tmp_path / f"{slide}.json")
        execute(path, "accept", slide_id=slide, record=tmp_path / f"{slide}.json")
    result = execute(path, "region", slide_id="s01", element_id="agronomist", region=[1050, 200, 480, 270])
    assert result["pages"]["s01"]["status"] == "pending"
    element = json.loads(path.read_text(encoding="utf-8"))["slides"][0]["elements"][2]
    assert element["bbox_hint"] == element["preserve_asset"]["region"] == [1050, 200, 480, 270]
    assert result["pages"]["s02"]["status"] == "approved"
    assert result["pages"]["s02"]["upscaled"] is True
    assert result["pages"]["s02"]["source_pixels"] == [800, 450]
    previous = result["pages"]["s02"]["source_snapshot"]
    source.unlink()
    # Restore from the retained original, never from the previous composited page.
    execute(path, "compose", slide_id="s01", source=workspace(path) / previous, allow_upscale=True)
    with pytest.raises(ValueError, match="Stale"):
        execute(path, "accept", slide_id="s01", record=tmp_path / "s01.json")


def test_prepare_restores_interrupted_projection_from_committed_snapshot(production, tmp_path):
    path, source = production
    execute(path, "compose", slide_id="s01", source=source)
    target = tmp_path / "slides/01-cover.png"
    before = target.read_bytes()
    target.unlink()
    execute(path, "prepare")
    assert target.read_bytes() == before


def test_failed_projection_recovers_after_atomic_state_commit(production, tmp_path, monkeypatch):
    import page_production
    path, source = production
    original_atomic = page_production.atomic
    target = tmp_path / "slides/01-cover.png"

    def fail_final(path, data):
        if path == target:
            raise OSError("Synthetic interruption after commit")
        original_atomic(path, data)

    monkeypatch.setattr(page_production, "atomic", fail_final)
    with pytest.raises(OSError, match="interruption"):
        execute(path, "compose", slide_id="s01", source=source)
    assert not target.exists()
    assert execute(path, "status")["pages"]["s01"]["status"] == "generated"
    monkeypatch.setattr(page_production, "atomic", original_atomic)
    execute(path, "prepare")
    assert target.exists()


def test_invalid_region_retains_specification_and_current_approval(production):
    path, source = production
    execute(path, "compose", slide_id="s01", source=source)
    before = path.read_bytes()
    state_before = (workspace(path) / "state.json").read_bytes()
    with pytest.raises(ValueError, match="outside canvas"):
        execute(path, "region", slide_id="s01", element_id="agronomist", region=[1500, 200, 480, 270])
    assert path.read_bytes() == before
    assert (workspace(path) / "state.json").read_bytes() == state_before


def test_status_does_not_create_workspace(production):
    path, _ = production
    assert execute(path, "status")["pages"]["s01"]["status"] == "pending"
    assert not workspace(path).exists()


def test_semantics_can_be_encoded_by_a_chart_without_forcing_repeated_bullets():
    slide = {"title": "Result", "role": "comparison", "core_message": "Semantic conclusion",
             "key_points": ["Meaning A", "Meaning B", "Meaning C"], "explanation": "Shared denominator",
             "boundary": "Scope restriction", "source_refs": ["Synthetic table 1"], "required_visible_values": ["32%"],
             "elements": [{"id": "chart", "kind": "chart", "confirmation_status": "confirmed"},
                          {"id": "caption", "kind": "text", "confirmation_status": "confirmed", "text": "A 32%; B 12%; same area. Synthetic table 1; limited scope."}]}
    slide["display"] = {"coverage": [{"claim": claim, "element_ids": ["chart", "caption"]} for claim in sorted(semantic_claims(slide))]}
    validate_content(slide, required=True)
    assert "Semantic conclusion" not in visible_text(slide)
    assert "32%" in visible_text(slide)
    from evaluate_benchmark import project_review_contract
    slide["page_number"] = 1
    slide["id"] = "s01"
    slide["elements"][0]["data"] = {"values": [32, 12]}
    contract = project_review_contract({"title": "Synthetic", "canvas": {"width": 1600, "height": 900}, "slides": [slide]})
    assert contract["slides"][0]["display"] == slide["display"]
    assert contract["slides"][0]["explanation"] == "Shared denominator"
    slide["display"]["coverage"].pop()
    with pytest.raises(ValueError, match="every semantic"):
        validate_content(slide, required=True)
