"""Offline production protocol fixtures; no real model or visual approval is implied."""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from content_density import visible_text
from page_production import CHECKS, digest, encoded, execute, seal, store, workspace
from PIL import Image
from update_data_bindings import export_draft, plan_update
from validate_page_spec import load_page_spec

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_bytes(encoded(value))


def produce(path, original, slide_id, *, approve=True):
    page = execute(path, "request", slide_id=slide_id, route="host")["pages"][slide_id]
    record = path.parent / f"call-{slide_id}.json"
    write(record, {"version": "1.0", "slide_id": slide_id, "request_sha256": page["request_sha256"],
                   "source_sha256": digest(original.read_bytes()), "backend": "synthetic-test-fixture",
                   "model": None, "result_ref": "Offline synthetic production protocol result"})
    execute(path, "compose", slide_id=slide_id, source=original, generation_record=record)
    if approve:
        record = path.parent / f"review-{slide_id}-{page['request_sha256']}.json"
        execute(path, "review-init", slide_id=slide_id, record=record)
        review = json.loads(record.read_bytes())
        spec = json.loads(path.read_bytes())
        slide = next(s for s in spec["slides"] if s["id"] == slide_id)
        review.update(reviewer="Synthetic protocol fixture", viewed_pixels=[1600, 900],
                      observed_text="\n".join(visible_text(slide, policy="1.1")))
        review["checks"] = {name: {"status": "pass", "notes": "Synthetic protocol fixture", "targets": ["page"]}
                            for name in review["checks"]}
        write(record, review)
        execute(path, "accept", slide_id=slide_id, record=record)


def production_case(tmp_path, *, approved=True, visible=False, style_reference=False):
    source = tmp_path / "source"
    base = source / "nested"
    base.mkdir(parents=True)
    spec = json.loads((ROOT / "examples/page-spec.example.json").read_bytes())
    spec["content_policy"] = "1.1"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "Synthetic authorized production outline"}
    spec["style"].pop("tokens", None)
    spec["style"].update(decision="skipped", authorization="Synthetic fixture skips previews")
    first = spec["slides"][0]
    first.update(title="Synthetic count", speaker_notes="Notes count 120")
    first["elements"] = [{"id": "count", "kind": "text", "role": "evidence", "native_intent": "native",
                          "confirmation_status": "confirmed", "source_ref": "Synthetic fixture", "text": "Count 110"}]
    second = copy.deepcopy(first)
    second.update(id="s02", page_number=2, image_file="slides/02.png")
    second["elements"][0]["text"] = "Unchanged page"
    spec["slides"].append(second)
    path = base / "page-spec.json"
    write(path, spec)
    if style_reference:
        from test_page_production import selected_style_fixture
        selected_style_fixture(path)
    original = base / "original.png"
    Image.new("RGB", (1600, 900), "navy").save(original)
    produce(path, original, "s01")
    # Retain a real, superseded production request, original and review in history.
    spec = json.loads(path.read_bytes())
    spec["slides"][0]["elements"][0]["text"] = "Count 120"
    write(path, spec)
    Image.new("RGB", (1600, 900), "white").save(original)
    produce(path, original, "s01")
    # s02's request uses s01's full-size image as an absolute-path style anchor.
    produce(path, original, "s02", approve=approved)
    contract = {"version": "1.0", "documents": {"page_spec": "nested/page-spec.json"},
                "inputs": {"count": {"value": 120, "unit": "items", "source_ref": "Synthetic fixture"}},
                "formulas": {}, "bindings": [{"document": "page_spec", "pointer": "/slides/1/speaker_notes",
                                              "template": "Notes count {count:.0f}"}]}
    if visible:
        contract["bindings"].append({"document": "page_spec", "pointer": "/slides/0/elements/0/text",
                                     "template": "Count {count:.0f}"})
    contract_path = source / "bindings.json"
    write(contract_path, contract)
    return contract_path, path


def tree_bytes(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_notes_only_cli_draft_retains_approval_and_self_contained_history(tmp_path):
    contract, path = production_case(tmp_path)
    load_page_spec(path, require_images=True)
    root = workspace(path)
    orphan = store(root, b"Unused production snapshot", ".json")
    (root / "work.jsonl").write_text("Unrelated work log", encoding="utf-8")
    before = tree_bytes(contract.parent)
    output = tmp_path / "notes-draft"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/update_data_bindings.py"), str(contract),
                             "--set", '{"count": 130}', "--output-dir", str(output)],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert tree_bytes(contract.parent) == before
    draft = output / "nested/page-spec.json"
    draft_root = workspace(draft)
    assert (draft_root / "state.json").is_file()
    assert not (draft_root / orphan).exists()
    assert not (draft_root / "status.md").exists()
    assert not (draft_root / "work.jsonl").exists()
    assert not (draft_root / "transaction.lock").exists()
    state = json.loads((draft_root / "state.json").read_bytes())
    reference = Path(state["pages"]["s02"]["request_reference"])
    assert reference.is_relative_to(draft_root) and reference.is_file()
    shutil.rmtree(contract.parent)
    spec, _ = load_page_spec(draft, require_images=True)
    assert spec["slides"][1]["speaker_notes"] == "Notes count 130"
    assert all("image_origin" not in slide for slide in spec["slides"])
    assert execute(draft, "prepare")["pages"]["s01"]["status"] == "approved"
    old = next(p for p in state["pages"]["s01"]["history"] if p.get("status") == "approved")
    for field in ("source_snapshot", "request_snapshot", "generation_snapshot", "review_snapshot"):
        assert (draft_root / old[field]).is_file()


def test_selected_style_draft_restores_archived_refined_page_without_source_project(tmp_path):
    from test_page_production import fixture_review
    contract, path = production_case(tmp_path, style_reference=True)
    spec = json.loads(path.read_bytes())
    original_root = workspace(path)
    final = path.parent / spec["slides"][1]["image_file"]
    correction = path.parent / "style-correction.png"
    with Image.open(final) as image:
        image.paste("navy", (10, 10, 80, 40))
        image.save(correction)
    execute(path, "refine", slide_id="s02", source=correction, base_image=final,
            operation="Synthetic local correction retaining the selected style")
    fixture_review(path, "s02", path.parent / "style-correction-review.json")
    execute(path, "accept", slide_id="s02", record=path.parent / "style-correction-review.json")
    before = execute(path, "status")["pages"]["s02"]
    request_bytes = (original_root / before["generation_request_snapshot"]).read_bytes()
    reference_bytes = (original_root / before["style_reference"]["reference_snapshot"]).read_bytes()
    source_bytes = (original_root / before["style_reference"]["source_snapshot"]).read_bytes()
    spec = json.loads(path.read_bytes())
    removed = spec["slides"].pop()
    write(path, spec)
    execute(path, "prepare")
    binding = json.loads(contract.read_bytes())
    binding["bindings"][0]["pointer"] = "/slides/0/speaker_notes"
    write(contract, binding)
    plan, paths = plan_update(contract, {"count": 130})
    output = tmp_path / "style-draft"
    export_draft(contract, output, plan, paths)
    draft = output / "nested/page-spec.json"
    draft_root = workspace(draft)
    state = json.loads((draft_root / "state.json").read_bytes())
    archived = state["archived_pages"]["s02"]
    assert (draft_root / archived["generation_request_snapshot"]).read_bytes() == request_bytes
    assert (draft_root / archived["style_reference"]["reference_snapshot"]).read_bytes() == reference_bytes
    assert (draft_root / archived["style_reference"]["source_snapshot"]).read_bytes() == source_bytes
    assert Path(archived["request_reference"]).is_relative_to(draft_root)
    assert str(contract.parent) not in json.dumps(state)
    shutil.rmtree(contract.parent)
    load_page_spec(draft, require_images=True)
    restored = json.loads(draft.read_bytes())
    restored["slides"].append(removed)
    write(draft, restored)
    assert execute(draft, "prepare")["pages"]["s02"]["status"] == "approved"
    load_page_spec(draft, require_images=True)
    final = draft.parent / removed["image_file"]
    correction = draft.parent / "next-style-correction.png"
    with Image.open(final) as image:
        image.paste("navy", (90, 10, 120, 40))
        image.save(correction)
    execute(draft, "refine", slide_id="s02", source=correction, base_image=final,
            operation="Synthetic second local correction after source project removal")
    record = draft.parent / "next-style-review.json"
    fixture_review(draft, "s02", record)
    assert json.loads(record.read_bytes())["style_reference"] == archived["style_reference"]
    execute(draft, "accept", slide_id="s02", record=record)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build_image_ppt.py"), str(draft), str(output / "restored.pptx")],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    restored = json.loads(draft.read_bytes())
    restored["slides"][1]["visual_brief"] += " Synthetic authorized revision."
    write(draft, restored)
    requested = execute(draft, "request", slide_id="s02", route="host")["pages"]["s02"]
    assert Path(requested["request_reference"]).read_bytes() == reference_bytes
    assert Path(requested["request_reference"]).is_relative_to(draft_root)


@pytest.mark.parametrize("damage", ["current-reference", "retained-reference"])
def test_style_draft_rejects_changed_reference_and_keeps_output_unpublished(tmp_path, damage):
    contract, path = production_case(tmp_path, style_reference=True)
    plan, paths = plan_update(contract, {"count": 130})
    if damage == "current-reference":
        declaration = json.loads(path.read_bytes())["style"]["generation_reference"]
        target = path.parent / declaration["image"]
    else:
        state = execute(path, "status")
        target = workspace(path) / state["pages"]["s01"]["style_reference"]["reference_snapshot"]
    target.write_bytes(b"Synthetic corrupt style reference")
    output = tmp_path / "invalid-style-draft"
    with pytest.raises(ValueError):
        export_draft(contract, output, plan, paths)
    assert not output.exists()
    assert not list(tmp_path.glob(".data-draft-*"))


@pytest.mark.parametrize("approved", [False, True])
def test_visible_draft_is_pending_and_can_recover_retained_originals(tmp_path, approved):
    contract, _ = production_case(tmp_path, approved=approved, visible=True)
    before = tree_bytes(contract.parent)
    plan, paths = plan_update(contract, {"count": 130})
    output = tmp_path / "visible-draft"
    export_draft(contract, output, plan, paths)
    assert tree_bytes(contract.parent) == before
    draft = output / "nested/page-spec.json"
    spec = json.loads(draft.read_bytes())
    state = json.loads((workspace(draft) / "state.json").read_bytes())
    assert spec["content_approved"] is False
    assert spec["slides"][0]["image_status"] == "pending"
    assert state["pages"]["s01"]["status"] == "pending"
    assert state["pages"]["s02"]["status"] == ("approved" if approved else "generated")
    previous = next(p for p in reversed(state["pages"]["s01"]["history"]) if p.get("status") == "approved")
    assert previous["contract_sha256"] != state["pages"]["s01"]["contract_sha256"]
    shutil.rmtree(contract.parent)
    spec.update(content_approved=True, content_version="synthetic-revision-v2")
    spec["workflow"]["approved_content_version"] = spec["content_version"]
    write(draft, spec)
    assert execute(draft, "prepare")["pages"]["s01"]["status"] == "pending"
    with pytest.raises(ValueError, match="not approved"):
        load_page_spec(draft, require_images=True)
    # Restored pixels retain their original call evidence and still need a NEW review.
    restored = execute(draft, "compose", slide_id="s01", source=workspace(draft) / previous["source_snapshot"])
    page = restored["pages"]["s01"]
    assert page["status"] == "generated" and "review_snapshot" not in page
    assert page["generation_request_snapshot"] == previous["generation_request_snapshot"]


def test_draft_retains_removed_page_and_local_correction_after_source_deletion(tmp_path):
    contract, path = production_case(tmp_path)
    evidence = path.parent / "archived-only-evidence.png"
    Image.new("RGB", (160, 90), "blue").save(evidence)
    evidence_bytes = evidence.read_bytes()
    spec = json.loads(path.read_bytes())
    spec["slides"][1]["elements"].append({"id": "unique-evidence", "kind": "image", "role": "evidence",
        "native_intent": "raster", "source_ref": "Synthetic supplied evidence", "confirmation_status": "confirmed",
        "visual_brief": "Synthetic blue evidence", "separate_asset": True, "bbox_hint": [1000, 150, 480, 270],
        "preserve_asset": {"file": evidence.name, "sha256": digest(evidence_bytes), "region": [1000, 150, 480, 270]}})
    write(path, spec)
    produce(path, path.parent / "original.png", "s02")
    base_image = path.parent / "slides/02.png"
    corrected = path.parent / "synthetic-corrected.png"
    with Image.open(base_image) as image:
        image.paste("blue", (10, 10, 80, 40))
        image.save(corrected)
    refined = execute(path, "refine", slide_id="s02", source=corrected, base_image=base_image,
                      operation="Synthetic local correction, no real model call")["pages"]["s02"]
    record = path.parent / "refined-review.json"
    execute(path, "review-init", slide_id="s02", record=record)
    review = json.loads(record.read_bytes())
    spec = json.loads(path.read_bytes())
    review.update(reviewer="Synthetic protocol fixture", viewed_pixels=[1600, 900],
                  observed_text="\n".join(visible_text(spec["slides"][1], policy="1.1")),
                  checks={name: {"status": "pass", "notes": "Synthetic fixture", "targets": ["page"]} for name in CHECKS})
    write(record, review)
    execute(path, "accept", slide_id="s02", record=record)
    spec = json.loads(path.read_bytes())
    removed_slide = spec["slides"].pop()
    write(path, spec)
    execute(path, "prepare")
    bindings = json.loads(contract.read_bytes())
    bindings["bindings"][0]["pointer"] = "/slides/0/speaker_notes"
    write(contract, bindings)
    plan, paths = plan_update(contract, {"count": 130})
    output = tmp_path / "archive-draft"
    export_draft(contract, output, plan, paths)
    draft = output / "nested/page-spec.json"
    draft_root = workspace(draft)
    state = json.loads((draft_root / "state.json").read_bytes())
    assert state["archived_pages"]["s02"]["status"] == "approved"
    assert (draft.parent / evidence.name).read_bytes() == evidence_bytes
    for key in ("source_snapshot", "image_snapshot", "derived_input_snapshot", "correction_snapshot", "derivation_snapshot"):
        assert (draft_root / refined[key]).is_file()
    derivation = json.loads((draft_root / refined["derivation_snapshot"]).read_bytes())
    for field in ("input", "correction"):
        assert digest((draft_root / derivation[field + "_snapshot"]).read_bytes()) == derivation[field + "_sha256"]
    shutil.rmtree(contract.parent)
    restored_spec = json.loads(draft.read_bytes())
    restored_spec["slides"].append(removed_slide)
    write(draft, restored_spec)
    restored = execute(draft, "prepare")
    assert restored["pages"]["s02"]["status"] == "approved"
    assert restored["archived_page_ids"] == []
    load_page_spec(draft, require_images=True)
    assert digest((draft.parent / removed_slide["image_file"]).read_bytes()) == refined["image_sha256"]
    # A second refinement remains self-contained after the original project is gone.
    base_image = draft.parent / removed_slide["image_file"]
    corrected = draft.parent / "second-synthetic-correction.png"
    with Image.open(base_image) as image:
        image.paste("red", (90, 10, 140, 40))
        image.save(corrected)
    second = execute(draft, "refine", slide_id="s02", source=corrected, base_image=base_image,
                     operation="Second synthetic local correction")["pages"]["s02"]
    assert second["derived_input_sha256"] == refined["image_sha256"]
    assert second["source_sha256"] == refined["source_sha256"]
    assert second["generation_request_snapshot"] == refined["generation_request_snapshot"]
    record = draft.parent / "second-correction-review.json"
    execute(draft, "review-init", slide_id="s02", record=record)
    review = json.loads(record.read_bytes())
    review.update(reviewer="Synthetic protocol fixture", viewed_pixels=[1600, 900],
                  observed_text="\n".join(visible_text(removed_slide, policy="1.1")),
                  checks={name: {"status": "pass", "notes": "Synthetic fixture", "targets": ["page"]} for name in CHECKS})
    write(record, review)
    execute(draft, "accept", slide_id="s02", record=record)
    built = subprocess.run([sys.executable, str(ROOT / "scripts/build_image_ppt.py"), str(draft), str(output / "draft.pptx")],
                           text=True, capture_output=True, check=False)
    assert built.returncode == 0, built.stderr
    from pptx import Presentation
    assert digest(Presentation(output / "draft.pptx").slides[1].shapes[0].image.blob) == second["image_sha256"]


def test_draft_rejects_replaced_historical_evidence_without_overwriting_current_assets(tmp_path):
    contract, path = production_case(tmp_path)
    evidence = path.parent / "historical-evidence.png"
    Image.new("RGB", (160, 90), "blue").save(evidence)
    spec = json.loads(path.read_bytes())
    spec["slides"][1]["elements"].append({"id": "history-evidence", "kind": "image", "role": "evidence",
        "native_intent": "raster", "source_ref": "Synthetic supplied evidence", "confirmation_status": "confirmed",
        "visual_brief": "Synthetic evidence", "separate_asset": True, "bbox_hint": [1000, 150, 480, 270],
        "preserve_asset": {"file": evidence.name, "sha256": digest(evidence.read_bytes()), "region": [1000, 150, 480, 270]}})
    write(path, spec)
    produce(path, path.parent / "original.png", "s02")
    Image.new("RGB", (160, 90), "red").save(evidence)
    spec = json.loads(path.read_bytes())
    spec["slides"][1]["elements"][-1]["preserve_asset"]["sha256"] = digest(evidence.read_bytes())
    write(path, spec)
    produce(path, path.parent / "original.png", "s02")
    before = tree_bytes(contract.parent)
    plan, paths = plan_update(contract, {"count": 130})
    output = tmp_path / "missing-historical-evidence-draft"
    with pytest.raises(ValueError, match="Historical preserved asset hash changed"):
        export_draft(contract, output, plan, paths)
    assert not output.exists()
    assert tree_bytes(contract.parent) == before


@pytest.mark.parametrize("damage", ["state", "historical-artifact", "path-escape"])
def test_invalid_production_history_fails_without_publishing_or_modifying_source(tmp_path, damage):
    contract, path = production_case(tmp_path)
    plan, paths = plan_update(contract, {"count": 130})
    root = workspace(path)
    state = json.loads((root / "state.json").read_bytes())
    if damage == "state":
        state["pages"]["s01"]["status"] = "generated"
        write(root / "state.json", state)
    elif damage == "historical-artifact":
        old = next(p for p in state["pages"]["s01"]["history"] if p.get("status") == "approved")
        (root / old["source_snapshot"]).write_bytes(b"Changed archived original")
    else:
        state["pages"]["s02"]["request_reference"] = str(path.parent / "original.png")
        state["state_sha256"] = seal({k: v for k, v in state.items() if k != "state_sha256"})
        write(root / "state.json", state)
    before = tree_bytes(contract.parent)
    output = tmp_path / "broken-draft"
    with pytest.raises(ValueError, match="[Pp]roduction|snapshot|artifact"):
        export_draft(contract, output, plan, paths)
    assert tree_bytes(contract.parent) == before
    assert not output.exists()
    assert not list(tmp_path.glob(".data-draft-*"))
