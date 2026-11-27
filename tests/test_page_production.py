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



def compose_fixture(path, **kwargs):
    """Explicit synthetic call evidence for protocol tests; no real model invocation."""
    from page_production import digest
    slide_id = kwargs["slide_id"]
    page = execute(path, "status")["pages"][slide_id]
    source_hash = digest(Path(kwargs["source"]).read_bytes())
    previous = [page, *page.get("history", [])]
    if any(p.get("source_sha256") == source_hash and p.get("generation_snapshot") for p in previous):
        return execute(path, "compose", **kwargs)
    if not page.get("request_snapshot"):
        page = execute(path, "request", slide_id=slide_id, route="host")["pages"][slide_id]
    record = path.parent / f"synthetic-call-{slide_id}.json"
    write(record, {"version": "1.0", "slide_id": slide_id, "request_sha256": page["request_sha256"],
                   "source_sha256": source_hash, "backend": "synthetic-test-fixture", "model": None,
                   "result_ref": "Synthetic protocol result; not an actual image generation call"})
    return execute(path, "compose", **kwargs, generation_record=record)


def fixture_review(path, slide_id, record):
    execute(path, "review-init", slide_id=slide_id, record=record)
    value = json.loads(record.read_text(encoding="utf-8"))
    spec = json.loads(path.read_text(encoding="utf-8"))
    slide = next(s for s in spec["slides"] if s["id"] == slide_id)
    value.update(reviewer="Synthetic test fixture", observed_text="\n".join(visible_text(slide, policy=spec.get("content_policy"))),
                 viewed_pixels=[1600, 900])
    value["checks"] = {name: {"status": "pass", "notes": "Synthetic protocol fixture", "targets": ["page"]} for name in CHECKS}
    write(record, value)


def test_prepare_is_idempotent_and_does_not_reset_approved_pages(production, tmp_path):
    path, source = production
    execute(path, "prepare")
    compose_fixture(path, slide_id="s01", source=source)
    fixture_review(path, "s01", tmp_path / "review.json")
    execute(path, "accept", slide_id="s01", record=tmp_path / "review.json")
    before = (workspace(path) / "state.json").read_bytes()
    execute(path, "prepare")
    compose_fixture(path, slide_id="s01", source=source)
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
    compose_fixture(path, slide_id="s01", source=source)
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
            compose_fixture(path, slide_id="s01", source=source)
        else:
            execute(path, "accept", slide_id="s01", record=record)
    assert target.read_bytes() == before
    assert (workspace(path) / "state.json").read_bytes() == state_before


def test_upscale_disclosed_and_region_change_invalidates_only_affected_page(production, tmp_path):
    path, source = production
    Image.new("RGB", (800, 450), "white").save(source)
    for slide in ("s01", "s02"):
        compose_fixture(path, slide_id=slide, source=source, allow_upscale=True)
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
    compose_fixture(path, slide_id="s01", source=workspace(path) / previous, allow_upscale=True)
    with pytest.raises(ValueError, match="Stale"):
        execute(path, "accept", slide_id="s01", record=tmp_path / "s01.json")


def test_prepare_restores_interrupted_projection_from_committed_snapshot(production, tmp_path):
    path, source = production
    compose_fixture(path, slide_id="s01", source=source)
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
        compose_fixture(path, slide_id="s01", source=source)
    assert not target.exists()
    assert execute(path, "status")["pages"]["s01"]["status"] == "generated"
    monkeypatch.setattr(page_production, "atomic", original_atomic)
    execute(path, "prepare")
    assert target.exists()


def test_invalid_region_retains_specification_and_current_approval(production):
    path, source = production
    compose_fixture(path, slide_id="s01", source=source)
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


def test_workflow_uses_visible_copy_and_reuses_unaffected_approved_pages(production, tmp_path):
    path, source = production
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["content_policy"] = "1.1"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "User-facing outline v1 in conversation"}
    spec["style"].update(decision="skipped", authorization="Skip style previews")
    first = spec["slides"][0]
    first.update(required_visible_values=["32%"], source_refs=["Internal page provenance"],
                 explanation="Internal explanation", speaker_notes="Private speaker note")
    first["elements"][0]["source_ref"] = "Internal element provenance"
    write(path, spec)

    state = execute(path, "prepare")
    prompt = json.loads((workspace(path) / state["pages"]["s01"]["prompt_snapshot"]).read_text(encoding="utf-8"))
    assert prompt["required_visible_text"] == [first["title"], "32%", first["elements"][1]["text"]]
    assert prompt["slide"]["explanation"] == "Internal explanation"
    prompt_text = json.dumps(prompt)
    assert all(text not in prompt_text for text in
               ("Internal page provenance", "Internal element provenance", "Private speaker note"))

    for slide_id in ("s01", "s02"):
        compose_fixture(path, slide_id=slide_id, source=source)
        record = tmp_path / f"{slide_id}.json"
        fixture_review(path, slide_id, record)
        if slide_id == "s01":
            correct = json.loads(record.read_text(encoding="utf-8"))
            write(record, {**correct, "observed_text": correct["observed_text"].replace("32%", "23%")})
            with pytest.raises(ValueError, match="required visible text"):
                execute(path, "accept", slide_id=slide_id, record=record)
            write(record, correct)
        execute(path, "accept", slide_id=slide_id, record=record)

    revised = json.loads(path.read_text(encoding="utf-8"))
    revised.update(content_version="outline-v2", content_authorization="Only change the cover")
    revised["slides"][0]["visual_brief"] += " with updated cover typography"
    write(path, revised)
    with pytest.raises(ValueError, match="current content_version"):
        execute(path, "prepare")
    revised["workflow"].update(content_mode="authorized-revision", approved_content_version="outline-v2")
    write(path, revised)
    state = execute(path, "prepare")
    assert state["pages"]["s01"]["status"] == "pending"
    assert state["pages"]["s02"]["status"] == "approved"


def test_legacy_source_coverage_remains_readable_without_requiring_source_text():
    slide = {
        "title": "Overview",
        "role": "cover",
        "core_message": "Explain the comparison",
        "source_refs": ["Local report page 3"],
        "elements": [{"id": "title", "kind": "text", "text": "Overview", "confirmation_status": "confirmed"}],
        "display": {"coverage": [
            {"claim": "core_message", "element_ids": ["title"]},
            {"claim": "source_refs/0", "element_ids": ["title"]},
        ]},
    }
    validate_content(slide, required=True)
    assert visible_text(slide) == ["Overview"]
    assert visible_text(slide, policy="1.1") == ["Overview"]
    slide["display"]["coverage"][1]["claim"] = "source_refs/1"
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        validate_content(slide, required=True)


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

def test_single_page_requests_isolate_preview_and_anchor_after_review(production, tmp_path):
    path, source = production
    spec = json.loads(path.read_text(encoding="utf-8"))
    preview = tmp_path / "overview.png"
    Image.new("RGB", (1600, 900)).save(preview)
    spec["style"]["tokens"] = {"palette": {"background": "#FFFFFF", "text": "#222222", "primary": "#334455", "accent": "#667788"},
                               "typography": {"heading_font": "Arial", "body_font": "Arial", "heading_size": 36, "body_size": 20},
                               "layout": {"grid": "single page", "margin_px": 40, "spacing_px": 12},
                               "image_treatment": "ink", "reference_images": [preview.name]}
    spec["slides"][1]["generation_prompt"] = "OLD PREVIEW INSTRUCTION"
    write(path, spec)
    state = execute(path, "request", slide_id="s01", route="host")
    page = state["pages"]["s01"]
    packet = json.loads((workspace(path) / page["request_snapshot"]).read_text(encoding="utf-8"))
    assert "reference_images" not in packet["style"]["tokens"]
    assert "request_reference" not in page
    assert "current page role" in packet["instructions"]
    assert "not as a repeated composition" in packet["instructions"]
    assert packet["slide"]["id"] == "s01" and "slides" not in packet
    compose_fixture(path, slide_id="s01", source=source)
    record = tmp_path / "anchor-review.json"
    fixture_review(path, "s01", record)
    template = json.loads(record.read_text(encoding="utf-8"))
    assert set(template["design_review_guidance"]) == {"density", "visual_relationships"}
    execute(path, "accept", slide_id="s01", record=record)
    state = execute(path, "request", slide_id="s02", route="isolated-worker")
    page = state["pages"]["s02"]
    packet = json.loads((workspace(path) / page["request_snapshot"]).read_text(encoding="utf-8"))
    assert packet["style_anchor"]["slide_id"] == "s01"
    assert Path(page["request_reference"]).is_file()
    assert "OLD PREVIEW INSTRUCTION" not in json.dumps(packet)
    assert preview.name not in json.dumps(packet)


def test_duplicate_failure_fuses_route_and_requires_new_route(production):
    path, _ = production
    for evidence in ("call-1", "call-2"):
        execute(path, "request", slide_id="s01", route="host")
        execute(path, "failure", slide_id="s01", route="host", failure_kind="multi-page", evidence=evidence)
    with pytest.raises(ValueError, match="Two repeated failures"):
        execute(path, "request", slide_id="s01", route="host")
    result = execute(path, "request", slide_id="s01", route="isolated-api")
    assert result["pages"]["s01"]["request_route"] == "isolated-api"
    assert len(result["pages"]["s01"]["generation_failures"]) == 2


def current_one_page(path):
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["content_policy"] = "1.1"
    spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                        "outline_ref": "Synthetic current-policy test outline"}
    spec["style"].update(decision="skipped", authorization="Synthetic test authorization")
    spec["slides"] = spec["slides"][:1]
    for element in spec["slides"][0]["elements"]:
        element.pop("preserve_asset", None)
    write(path, spec)
    return spec


def test_new_original_requires_prepared_request_and_bound_call_evidence(production, tmp_path):
    from page_production import digest
    path, source = production
    current_one_page(path)
    with pytest.raises(ValueError, match="generation-record"):
        execute(path, "compose", slide_id="s01", source=source)
    page = execute(path, "request", slide_id="s01", route="host")["pages"]["s01"]
    with pytest.raises(ValueError, match="generation-record"):
        execute(path, "compose", slide_id="s01", source=source)
    record = tmp_path / "call.json"
    valid = {"version": "1.0", "slide_id": "s01", "request_sha256": page["request_sha256"],
             "source_sha256": digest(source.read_bytes()), "backend": "synthetic-fixture", "model": None,
             "result_ref": "Synthetic actual-output locator for protocol testing"}
    for key, value in (("request_sha256", "0" * 64), ("source_sha256", "0" * 64),
                       ("backend", ""), ("result_ref", ""), ("model", "")):
        write(record, {**valid, key: value})
        with pytest.raises(ValueError):
            execute(path, "compose", slide_id="s01", source=source, generation_record=record)
        assert execute(path, "status")["pages"]["s01"]["status"] == "pending"
    write(record, valid)
    assert execute(path, "compose", slide_id="s01", source=source, generation_record=record)["pages"]["s01"]["status"] == "generated"


def test_export_rejects_shadow_approval_and_changed_approved_image(production, tmp_path):
    import argparse

    from build_image_ppt import build_deck
    from validate_page_spec import load_page_spec
    path, source = production
    spec = current_one_page(path)
    target = tmp_path / spec["slides"][0]["image_file"]
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(source.read_bytes())
    spec["slides"][0]["image_status"] = "approved"
    write(path, spec)
    with pytest.raises(ValueError, match="production approval"):
        load_page_spec(path, require_images=True)
    compose_fixture(path, slide_id="s01", source=source)
    review = tmp_path / "approved-review.json"
    fixture_review(path, "s01", review)
    execute(path, "accept", slide_id="s01", record=review)
    args = argparse.Namespace(input_dir=path, output=tmp_path / "approved.pptx", width=None, height=None,
                              fit="cover", background="FFFFFF", title="", max_width=0, jpeg_quality=0)
    assert build_deck(args)["slides"] == 1
    before = args.output.read_bytes()
    Image.new("RGB", (1600, 900), "red").save(target)
    with pytest.raises(ValueError, match="Approved image or review changed"):
        build_deck(args)
    assert args.output.read_bytes() == before


def test_explicit_existing_images_need_no_generation_but_keep_hash_binding(production, tmp_path):
    from page_production import digest
    from validate_page_spec import load_page_spec
    path, source = production
    spec = current_one_page(path)
    slide = spec["slides"][0]
    target = tmp_path / slide["image_file"]
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(source.read_bytes())
    slide.update(image_status="approved", image_origin={"kind": "provided", "source_ref": "User-provided synthetic fixture",
                                                       "sha256": digest(target.read_bytes())})
    write(path, spec)
    assert load_page_spec(path, require_images=True)[1]["slides"] == 1
    assert not workspace(path).exists()
    Image.new("RGB", (1600, 900), "red").save(target)
    with pytest.raises(ValueError, match="Provided image changed"):
        load_page_spec(path, require_images=True)


def test_generated_history_cannot_be_reclassified_as_provided(production, tmp_path):
    from page_production import digest
    from validate_page_spec import load_page_spec
    path, source = production
    current_one_page(path)
    compose_fixture(path, slide_id="s01", source=source)
    spec = json.loads(path.read_text(encoding="utf-8"))
    slide = spec["slides"][0]
    slide.update(image_status="approved", image_origin={"kind": "provided", "source_ref": "False reclassification",
        "sha256": digest((tmp_path / slide["image_file"]).read_bytes())})
    write(path, spec)
    for action in (lambda: load_page_spec(path, require_images=True), lambda: execute(path, "prepare")):
        with pytest.raises(ValueError, match="cannot bypass production review"):
            action()


def test_provided_jpeg_and_generated_page_can_share_production(production, tmp_path):
    from page_production import digest
    from validate_page_spec import load_page_spec
    path, source = production
    spec = current_one_page(path)
    provided = copy.deepcopy(spec["slides"][0])
    provided.update(id="s02", page_number=2, image_file="provided.jpg", image_status="approved")
    image = tmp_path / provided["image_file"]
    Image.new("RGB", (1600, 900), "navy").save(image)
    raw = image.read_bytes()
    provided["image_origin"] = {"kind": "provided", "source_ref": "User-provided synthetic fixture",
                                "sha256": digest(raw)}
    spec["slides"].append(provided)
    write(path, spec)
    state = execute(path, "prepare")
    assert state["pages"]["s02"]["status"] == "approved"
    page = execute(path, "request", slide_id="s01", route="host")["pages"]["s01"]
    assert Path(page["request_reference"]).read_bytes() == raw
    compose_fixture(path, slide_id="s01", source=source)
    review = tmp_path / "mixed-review.json"
    fixture_review(path, "s01", review)
    execute(path, "accept", slide_id="s01", record=review)
    assert load_page_spec(path, require_images=True)[1]["slides"] == 2
    assert image.read_bytes() == raw
    with pytest.raises(ValueError, match="Provided images"):
        execute(path, "request", slide_id="s02", route="host")


def test_export_checks_for_input_changes_after_embedding(production, tmp_path, monkeypatch):
    import argparse

    import build_image_ppt
    path, source = production
    spec = current_one_page(path)
    compose_fixture(path, slide_id="s01", source=source)
    review = tmp_path / "review.json"
    fixture_review(path, "s01", review)
    execute(path, "accept", slide_id="s01", record=review)
    original = build_image_ppt.add_fitted_picture

    def substitute(*args, **kwargs):
        picture = original(*args, **kwargs)
        Image.new("RGB", (1600, 900), "red").save(tmp_path / spec["slides"][0]["image_file"])
        return picture

    monkeypatch.setattr(build_image_ppt, "add_fitted_picture", substitute)
    args = argparse.Namespace(input_dir=path, output=tmp_path / "late-change.pptx", width=None, height=None,
                              fit="cover", background="FFFFFF", title="", max_width=0, jpeg_quality=0)
    with pytest.raises(ValueError, match="Approved image or review changed"):
        build_image_ppt.build_deck(args)
    assert not args.output.exists()


def test_editable_revision_uses_only_approved_historical_image(production, tmp_path):
    from page_production import approved_image_hashes

    path, source = production
    for slide_id in ("s01", "s02"):
        compose_fixture(path, slide_id=slide_id, source=source)
        record = tmp_path / f"{slide_id}-review.json"
        fixture_review(path, slide_id, record)
        execute(path, "accept", slide_id=slide_id, record=record)
    spec = json.loads(path.read_text(encoding="utf-8"))
    approved_image_hashes(path, spec)
    slide = spec["slides"][0]
    slide.update(title="Revised for editable only", image_status="revision")
    approved_image_hashes(path, spec, allow_revision=True)
    with pytest.raises(ValueError, match="Missing current production approval for s01"):
        approved_image_hashes(path, spec)
    path_image = tmp_path / slide["image_file"]
    with Image.open(path_image) as image:
        edited = image.copy()
    edited.putpixel((0, 0), (12, 34, 56))
    edited.save(path_image)
    with pytest.raises(ValueError, match="approved historical image"):
        approved_image_hashes(path, spec, allow_revision=True)
