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
                            for name in CHECKS}
        write(record, review)
        execute(path, "accept", slide_id=slide_id, record=record)


def production_case(tmp_path, *, approved=True, visible=False):
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
