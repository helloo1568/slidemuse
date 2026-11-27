"""Synthetic v2.27 persisted-state fixtures; no model call or visual approval is implied."""
import copy
import json
from pathlib import Path

import pytest
from content_density import visible_text
from page_production import (
    CHECKS,
    commit,
    digest,
    encoded,
    execute,
    fingerprint,
    generation_input,
    store,
    workspace,
)
from PIL import Image
from validate_page_spec import load_page_spec

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_bytes(encoded(value))


def legacy_fixture(tmp_path, *, request=True, route="host"):
    spec = json.loads((ROOT / "examples/page-spec.example.json").read_text(encoding="utf-8"))
    spec["content_policy"] = "1.1"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "Synthetic approved legacy outline"}
    spec["style"].pop("tokens", None)
    spec["style"].update(decision="skipped", authorization="Synthetic legacy authorization")
    slide = spec["slides"][0]
    slide["image_status"] = "approved"
    path = tmp_path / "legacy.json"
    write(path, spec)
    original = tmp_path / "original.png"
    Image.new("RGB", (1600, 900), "navy").save(original)
    raw = original.read_bytes()
    root = workspace(path)
    prompt = encoded(generation_input(spec, slide))
    page = {"contract_sha256": fingerprint(spec, slide, tmp_path), "status": "approved", "history": [],
            "source_snapshot": store(root, raw, ".source"), "source_sha256": digest(raw),
            "source_pixels": [1600, 900], "final_pixels": [1600, 900], "upscaled": False,
            "image_snapshot": store(root, raw, ".png"), "image_sha256": digest(raw),
            "protected_regions": [], "prompt_snapshot": store(root, prompt, ".prompt.json")}
    review = {"version": "1.0", "id": slide["id"], "contract_sha256": page["contract_sha256"],
              "image_sha256": page["image_sha256"], "reviewer": "Synthetic legacy reviewer",
              "observed_text": "\n".join(visible_text(slide, policy="1.1")), "viewed_pixels": [1600, 900],
              "checks": {name: {"status": "pass", "notes": "Synthetic fixture", "targets": ["page"]}
                         for name in CHECKS}, "protected_regions": []}
    page["review_snapshot"] = store(root, encoded(review), ".review.json")
    if request:
        # Exact old shape: the packet has no request_id, route or contract_sha256.
        page["request_snapshot"] = store(root, prompt, ".request.json")
        if route is not None:
            page["request_route"] = route
    commit(path, spec, root, {"version": "1.0", "pages": {slide["id"]: page}})
    return path, original, copy.deepcopy(page)


def historical_record(path, original, page):
    record = path.parent / "historical-call.json"
    request = workspace(path) / page["request_snapshot"]
    write(record, {"version": "1.0", "slide_id": "s01", "request_sha256": digest(request.read_bytes()),
                   "source_sha256": digest(original.read_bytes()), "backend": "synthetic-legacy-tool",
                   "model": None, "result_ref": "Synthetic historical call evidence"})
    return record


def accept_current(path, record):
    execute(path, "review-init", slide_id="s01", record=record)
    value = json.loads(record.read_bytes())
    slide = json.loads(path.read_bytes())["slides"][0]
    value.update(reviewer="Synthetic migration reviewer", observed_text="\n".join(visible_text(slide, policy="1.1")),
                 viewed_pixels=[1600, 900])
    value["checks"] = {name: {"status": "pass", "notes": "Synthetic migration review", "targets": ["page"]}
                       for name in CHECKS}
    write(record, value)
    execute(path, "accept", slide_id="s01", record=record)


@pytest.mark.parametrize("archived", [False, True])
def test_legacy_request_uses_sealed_route_and_preserves_original_packet(tmp_path, archived):
    path, original, old = legacy_fixture(tmp_path)
    old_request = (workspace(path) / old["request_snapshot"]).read_bytes()
    record = historical_record(path, original, old)
    if archived:
        spec = json.loads(path.read_bytes())
        spec["slides"][0]["elements"][0]["bbox_hint"] = [10, 10, 600, 100]
        write(path, spec)
        execute(path, "prepare")
    result = execute(path, "compose", slide_id="s01", source=original, generation_record=record)
    page = result["pages"]["s01"]
    assert page["status"] == "generated"
    assert "review_snapshot" not in page
    assert page["generation_request_snapshot"] == old["request_snapshot"]
    assert page["generation_request_route"] == "host"
    assert (workspace(path) / old["request_snapshot"]).read_bytes() == old_request
    assert "route" not in json.loads(old_request)
    assert json.loads(path.read_bytes())["slides"][0]["image_status"] == "generated"
    with pytest.raises(ValueError, match="not approved"):
        load_page_spec(path, require_images=True)
    accept_current(path, tmp_path / "new-review.json")
    assert load_page_spec(path, require_images=True)[1]["slides"] == 1
    before = (workspace(path) / "state.json").read_bytes()
    execute(path, "compose", slide_id="s01", source=original)
    assert (workspace(path) / "state.json").read_bytes() == before


@pytest.mark.parametrize("mutation", ["request-hash", "source-hash", "missing-route", "partial-modern-packet"])
def test_legacy_migration_rejects_unbound_evidence_without_changes(tmp_path, mutation):
    path, original, page = legacy_fixture(tmp_path, route=None if mutation == "missing-route" else "host")
    if mutation == "partial-modern-packet":
        packet = json.loads((workspace(path) / page["request_snapshot"]).read_bytes())
        packet["request_id"] = "modern-request-must-have-its-own-route"
        page["request_snapshot"] = store(workspace(path), encoded(packet), ".request.json")
        spec = json.loads(path.read_bytes())
        commit(path, spec, workspace(path), {"version": "1.0", "pages": {"s01": page}})
    record = historical_record(path, original, page)
    value = json.loads(record.read_bytes())
    if mutation == "request-hash":
        value["request_sha256"] = "0" * 64
    if mutation == "source-hash":
        value["source_sha256"] = "0" * 64
    write(record, value)
    before_state, before_spec = (workspace(path) / "state.json").read_bytes(), path.read_bytes()
    with pytest.raises(ValueError):
        execute(path, "compose", slide_id="s01", source=original, generation_record=record)
    assert (workspace(path) / "state.json").read_bytes() == before_state
    assert path.read_bytes() == before_spec


def test_no_historical_request_explains_and_allows_separate_regeneration(tmp_path):
    path, original, old = legacy_fixture(tmp_path, request=False)
    before_state, before_spec = (workspace(path) / "state.json").read_bytes(), path.read_bytes()
    for supplied in (False, True):
        kwargs = {}
        if supplied:
            # A saved generic production prompt is not proof of the actual old request.
            record = tmp_path / "unbound-prompt-record.json"
            write(record, {"version": "1.0", "slide_id": "s01", "request_sha256": old["prompt_snapshot"].split("/")[-1][:64],
                           "source_sha256": digest(original.read_bytes()), "backend": "synthetic-tool",
                           "model": None, "result_ref": "Synthetic unbound prompt"})
            kwargs["generation_record"] = record
        with pytest.raises(ValueError, match="separate new project directory.*NEW original"):
            execute(path, "compose", slide_id="s01", source=original, **kwargs)
    assert (workspace(path) / "state.json").read_bytes() == before_state
    assert path.read_bytes() == before_spec

    fresh = tmp_path / "separate-project"
    fresh.mkdir()
    new_spec = fresh / "page-spec.json"
    new_spec.write_bytes(before_spec)
    new_source = fresh / "new-original.png"
    Image.new("RGB", (1600, 900), "teal").save(new_source)
    page = execute(new_spec, "request", slide_id="s01", route="host")["pages"]["s01"]
    record = fresh / "new-call.json"
    write(record, {"version": "1.0", "slide_id": "s01", "request_sha256": page["request_sha256"],
                   "source_sha256": digest(new_source.read_bytes()), "backend": "synthetic-new-tool",
                   "model": None, "result_ref": "Synthetic NEW call result"})
    execute(new_spec, "compose", slide_id="s01", source=new_source, generation_record=record)
    accept_current(new_spec, fresh / "review.json")
    assert load_page_spec(new_spec, require_images=True)[1]["slides"] == 1
    assert (workspace(path) / "state.json").read_bytes() == before_state
    assert path.read_bytes() == before_spec
