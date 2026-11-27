"""Synthetic protocol fixtures; these do not measure model output or human review quality."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from content_density import semantic_claims, validate_content, visible_text
from page_production import STYLE_CHECK, execute, workspace
from PIL import Image, ImageChops, PngImagePlugin
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
    value["checks"] = {name: {"status": "pass", "notes": "Synthetic protocol fixture", "targets": ["page"]}
                       for name in value["checks"]}
    write(record, value)


def selected_style_fixture(path, *, decision="selected", register=True, legacy=False):
    """Synthetic visual baseline and selection; never a model result or visual quality claim."""
    from style_reference import create_reference, resolve_reference
    spec = json.loads(path.read_bytes())
    if not legacy:
        spec["content_policy"] = "1.1"
        spec["workflow"] = {"content_mode": "confirmed", "approved_content_version": spec["content_version"],
                            "outline_ref": "Synthetic authorized content fixture"}
    preview = path.parent / "selected-overview.png"
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("slidemuse_style_option", "2")
    metadata.add_text("slidemuse_style_name", "Synthetic crimson")
    image = Image.new("RGB", (1800, 1100), "#882244")
    image.paste("#442288", (20, 70, 980, 610))
    image.save(preview, pnginfo=metadata)
    spec["style"].update(decision=decision, option=2, choice="Synthetic crimson",
                         authorization="Synthetic style authorization", visual_spec="Synthetic crimson and purple style")
    spec["style"]["tokens"] = {
        "palette": {"background": "#882244", "text": "#FFFFFF", "primary": "#442288", "accent": "#DDCC66"},
        "typography": {"heading_font": "Arial", "body_font": "Arial", "heading_size": 36, "body_size": 20},
        "layout": {"grid": "single page", "margin_px": 40, "spacing_px": 12},
        "image_treatment": "Synthetic flat fixture", "reference_images": [preview.name]}
    if decision == "locked-reference":
        Image.new("RGB", (1600, 900), "#442288").save(preview)
    write(path, spec)
    if register and decision != "locked-reference":
        return create_reference(path, "styles/selected-single.png", box=[20, 70, 960, 540])
    return resolve_reference(spec, path.parent)


def test_refine_cli_preserves_real_original_binding_and_requires_new_review(production, tmp_path):
    from page_production import digest
    from validate_page_spec import load_page_spec
    path, source = production
    page = compose_fixture(path, slide_id="s01", source=source)["pages"]["s01"]
    old_review = tmp_path / "before-refine.json"
    fixture_review(path, "s01", old_review)
    execute(path, "accept", slide_id="s01", record=old_review)
    final = path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]
    before = final.read_bytes()
    corrected = tmp_path / "synthetic-correction.png"
    with Image.open(final) as image:
        image.paste("white", (10, 10, 80, 40))
        image.save(corrected)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "slidemuse.py"),
                             "produce", "refine", str(path), "--slide", "s01", "--base-image", str(final),
                             "--source", str(corrected), "--operation", "Synthetic local text correction; no model invocation"],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    refined = json.loads(result.stdout)["pages"]["s01"]
    assert refined["status"] == "generated" and "review_snapshot" not in refined
    for key in ("source_snapshot", "source_sha256", "generation_snapshot", "generation_request_snapshot"):
        assert refined[key] == page[key]
    assert refined["derived_input_sha256"] == digest(before)
    assert refined["correction_sha256"] == digest(corrected.read_bytes())
    assert digest(final.read_bytes()) == refined["image_sha256"] != digest(before)
    with pytest.raises(ValueError, match="not approved"):
        load_page_spec(path, require_images=True)
    with pytest.raises(ValueError, match="Stale or mismatched"):
        execute(path, "accept", slide_id="s01", record=old_review)
    current_bytes = final.read_bytes()
    review = tmp_path / "after-refine.json"
    fixture_review(path, "s01", review)
    assert final.read_bytes() == current_bytes
    execute(path, "accept", slide_id="s01", record=review)
    # The second page must also be approved before testing the actual export gate.
    compose_fixture(path, slide_id="s02", source=source)
    fixture_review(path, "s02", tmp_path / "second-page.json")
    execute(path, "accept", slide_id="s02", record=tmp_path / "second-page.json")
    load_page_spec(path, require_images=True)
    output = tmp_path / "refined.pptx"
    built = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/build_image_ppt.py"),
                            str(path), str(output)], text=True, capture_output=True, check=False)
    assert built.returncode == 0, built.stderr
    from pptx import Presentation
    assert Presentation(output).slides[0].shapes[0].image.blob == current_bytes


@pytest.mark.parametrize("damage", ["unknown-base", "protected-pixels", "wrong-size", "transparent", "blank-operation"])
def test_refine_rejects_unbound_or_invalid_corrections_without_committing(production, tmp_path, damage):
    path, source = production
    compose_fixture(path, slide_id="s01", source=source)
    base = path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]
    corrected = tmp_path / "synthetic-correction.png"
    image = Image.open(base).convert("RGB")
    operation = "Synthetic local correction"
    if damage == "unknown-base":
        base = tmp_path / "unrelated.png"
        Image.new("RGB", (1600, 900), "blue").save(base)
    elif damage == "protected-pixels":
        image.putpixel((1000, 150), (255, 0, 0))
    elif damage == "wrong-size":
        image = image.resize((800, 450))
    elif damage == "transparent":
        image = image.convert("RGBA")
        image.putpixel((0, 0), (0, 0, 0, 0))
    else:
        operation = " "
    image.save(corrected)
    state_before = (workspace(path) / "state.json").read_bytes()
    final_before = (path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]).read_bytes()
    with pytest.raises(ValueError):
        execute(path, "refine", slide_id="s01", source=corrected, base_image=base, operation=operation)
    assert (workspace(path) / "state.json").read_bytes() == state_before
    assert (path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]).read_bytes() == final_before


def test_review_init_preserves_unregistered_correction_and_explains_recovery(production, tmp_path):
    path, source = production
    compose_fixture(path, slide_id="s01", source=source)
    final = path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]
    with Image.open(final) as image:
        image.paste("white", (10, 10, 80, 40))
        image.save(final)
    corrected = final.read_bytes()
    state_before = (workspace(path) / "state.json").read_bytes()
    record = tmp_path / "unregistered-review.json"
    with pytest.raises(ValueError, match="refine"):
        execute(path, "review-init", slide_id="s01", record=record)
    assert final.read_bytes() == corrected and not record.exists()
    assert (workspace(path) / "state.json").read_bytes() == state_before


@pytest.mark.parametrize("action", ["prepare", "request", "compose", "review-init"])
def test_unrelated_page_actions_preserve_external_edits_before_any_commit(production, tmp_path, action):
    path, source = production
    compose_fixture(path, slide_id="s01", source=source)
    compose_fixture(path, slide_id="s02", source=source)
    final = path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]
    with Image.open(final) as image:
        image.paste("white", (10, 10, 80, 40))
        image.save(final)
    corrected = final.read_bytes()
    before = {p: p.read_bytes() for p in workspace(path).rglob("*") if p.is_file()}
    spec_before = path.read_bytes()
    record = tmp_path / "other-page-review.json"
    with pytest.raises(ValueError, match="s01.*|refine"):
        execute(path, action, slide_id="s02", route="host", source=source, record=record)
    assert final.read_bytes() == corrected and not record.exists()
    assert path.read_bytes() == spec_before
    assert {p: p.read_bytes() for p in workspace(path).rglob("*") if p.is_file()} == before
    # Moving the correction aside allows explicit recovery and registration.
    correction = tmp_path / "independent-correction.png"
    final.rename(correction)
    execute(path, "prepare")
    execute(path, "refine", slide_id="s01", source=correction, base_image=final,
            operation="Synthetic local correction retained after conflict")
    assert correction.read_bytes() == corrected


@pytest.mark.parametrize("external_edit", [False, True])
def test_prepare_recovers_interrupted_replacement_only_from_retained_pixels(production, tmp_path, monkeypatch, external_edit):
    import page_production
    path, source = production
    old = compose_fixture(path, slide_id="s01", source=source)["pages"]["s01"]
    target = path.parent / json.loads(path.read_bytes())["slides"][0]["image_file"]
    Image.new("RGB", (1600, 900), "purple").save(source)
    atomic = page_production.atomic

    def interrupted(destination, data):
        if destination == target:
            raise OSError("Synthetic interruption replacing an existing projection")
        atomic(destination, data)

    monkeypatch.setattr(page_production, "atomic", interrupted)
    with pytest.raises(OSError, match="interruption"):
        compose_fixture(path, slide_id="s01", source=source)
    monkeypatch.setattr(page_production, "atomic", atomic)
    assert page_production.digest(target.read_bytes()) == old["image_sha256"]
    if external_edit:
        Image.new("RGB", (1600, 900), "orange").save(target)
        edited = target.read_bytes()
        before = (workspace(path) / "state.json").read_bytes()
        with pytest.raises(ValueError, match="retain|Keep"):
            execute(path, "prepare")
        assert target.read_bytes() == edited
        assert (workspace(path) / "state.json").read_bytes() == before
    else:
        page = execute(path, "prepare")["pages"]["s01"]
        assert page_production.digest(target.read_bytes()) == page["image_sha256"] != old["image_sha256"]


def test_refine_can_use_historical_image_after_authorized_content_revision(production, tmp_path):
    path, source = production
    previous = compose_fixture(path, slide_id="s01", source=source)["pages"]["s01"]
    spec = json.loads(path.read_bytes())
    spec["slides"][0]["visual_brief"] += " with a corrected local label"
    write(path, spec)
    assert execute(path, "prepare")["pages"]["s01"]["status"] == "pending"
    base = workspace(path) / previous["image_snapshot"]
    corrected = tmp_path / "revised.png"
    with Image.open(base) as image:
        image.paste("white", (10, 10, 80, 40))
        image.save(corrected)
    revised = execute(path, "refine", slide_id="s01", source=corrected, base_image=base,
                      operation="Synthetic authorized local label revision")["pages"]["s01"]
    assert revised["status"] == "generated"
    assert revised["source_sha256"] == previous["source_sha256"]
    assert revised["generation_request_snapshot"] == previous["generation_request_snapshot"]
    assert revised["contract_sha256"] != previous["contract_sha256"]
    fixture_review(path, "s01", tmp_path / "revised-review.json")
    execute(path, "accept", slide_id="s01", record=tmp_path / "revised-review.json")


def test_refine_requires_explicit_new_upscale_and_reuses_existing_allowance(production, tmp_path):
    path, source = production
    compose_fixture(path, slide_id="s02", source=source)
    spec = json.loads(path.read_bytes())
    spec["canvas"] = {"width": 3200, "height": 1800}
    write(path, spec)
    execute(path, "prepare")
    base = path.parent / "slides/02.png"
    corrected = tmp_path / "enlarged-correction.png"
    with Image.open(base) as image:
        image.resize((3200, 1800)).save(corrected)
    old_state = (workspace(path) / "state.json").read_bytes()
    with pytest.raises(ValueError, match="--allow-upscale"):
        execute(path, "refine", slide_id="s02", source=corrected, base_image=base, operation="Synthetic local correction")
    assert (workspace(path) / "state.json").read_bytes() == old_state
    first = execute(path, "refine", slide_id="s02", source=corrected, base_image=base,
                    operation="Synthetic explicitly enlarged correction", allow_upscale=True)["pages"]["s02"]
    assert first["upscaled"] is True
    assert first["source_pixels"] == first["derived_input_pixels"] == [1600, 900]
    assert first["final_pixels"] == [3200, 1800]
    with Image.open(base) as image:
        image.paste("red", (10, 10, 80, 40))
        image.save(corrected)
    second = execute(path, "refine", slide_id="s02", source=corrected, base_image=base,
                     operation="Synthetic subsequent correction at the same authorized size")["pages"]["s02"]
    assert second["upscaled"] is True
    assert second["derived_input_pixels"] == second["final_pixels"] == [3200, 1800]
    assert second["source_pixels"] == [1600, 900]


@pytest.mark.parametrize("changed", [False, True])
def test_removed_page_undo_restores_approval_or_retains_history(production, tmp_path, changed):
    path, source = production
    compose_fixture(path, slide_id="s02", source=source)
    fixture_review(path, "s02", tmp_path / "review-removed.json")
    old = execute(path, "accept", slide_id="s02", record=tmp_path / "review-removed.json")["pages"]["s02"]
    original_spec = json.loads(path.read_bytes())
    removed = copy.deepcopy(original_spec)
    removed["slides"].pop()
    write(path, removed)
    result = execute(path, "prepare")
    assert result["archived_page_ids"] == ["s02"]
    archived = execute(path, "status")["archived_pages"]["s02"]
    assert archived["review_snapshot"] == old["review_snapshot"]
    source.unlink()
    if changed:
        original_spec["slides"][1]["visual_brief"] += " with revised typography"
    write(path, original_spec)
    restored = execute(path, "prepare")
    assert restored["archived_page_ids"] == []
    page = execute(path, "status")["pages"]["s02"]
    assert page["status"] == ("pending" if changed else "approved")
    previous = page["history"][-1] if changed else page
    assert previous["generation_snapshot"] == old["generation_snapshot"]
    assert previous["review_snapshot"] == old["review_snapshot"]
    recovered = execute(path, "compose", slide_id="s02", source=workspace(path) / old["source_snapshot"])
    assert recovered["pages"]["s02"]["status"] == ("generated" if changed else "approved")


def test_restoring_removed_page_checks_retained_snapshot_integrity(production):
    path, source = production
    old = compose_fixture(path, slide_id="s02", source=source)["pages"]["s02"]
    original_spec = json.loads(path.read_bytes())
    removed = copy.deepcopy(original_spec)
    removed["slides"].pop()
    write(path, removed)
    execute(path, "prepare")
    before = (workspace(path) / "state.json").read_bytes()
    (workspace(path) / old["source_snapshot"]).write_bytes(b"Damaged retained original")
    write(path, original_spec)
    with pytest.raises(ValueError, match="snapshot changed"):
        execute(path, "prepare")
    assert (workspace(path) / "state.json").read_bytes() == before


@pytest.mark.parametrize("changed_target", [False, True])
def test_restore_provided_archive_recovers_missing_pixels_but_rejects_replacement(production, changed_target):
    from page_production import digest
    path, source = production
    original = source.read_bytes()
    spec = json.loads(path.read_bytes())
    spec["slides"][1].update(image_file=source.name, image_status="approved",
                             image_origin={"kind": "provided", "source_ref": "Synthetic input", "sha256": digest(original)})
    write(path, spec)
    execute(path, "prepare")
    removed = copy.deepcopy(spec)
    removed["slides"].pop()
    write(path, removed)
    execute(path, "prepare")
    source.unlink()
    if changed_target:
        Image.new("RGB", (1600, 900), "blue").save(source)
        replacement = source.read_bytes()
    write(path, spec)
    if changed_target:
        with pytest.raises(ValueError, match="Provided image changed"):
            execute(path, "prepare")
        assert source.read_bytes() == replacement
    else:
        assert execute(path, "prepare")["pages"]["s02"]["status"] == "approved"
        assert source.read_bytes() == original


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
    reference = selected_style_fixture(path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["slides"][1]["generation_prompt"] = "OLD PREVIEW INSTRUCTION"
    write(path, spec)
    state = execute(path, "request", slide_id="s01", route="host")
    page = state["pages"]["s01"]
    packet = json.loads((workspace(path) / page["request_snapshot"]).read_text(encoding="utf-8"))
    assert "reference_images" not in packet["style"]["tokens"]
    assert "without treating its exact composition as a fixed template" in packet["instructions"]
    baseline = packet["style_reference"]
    assert baseline == page["style_reference"]
    assert baseline["sha256"] == reference["sha256"]
    assert baseline["source_sha256"] == reference["source_sha256"]
    assert Path(page["request_reference"]).read_bytes() == Path(reference["path"]).read_bytes()
    assert (workspace(path) / baseline["source_snapshot"]).read_bytes() == Path(reference["source_path"]).read_bytes()
    assert "style_anchor" not in packet
    assert packet["slide"]["id"] == "s01" and "slides" not in packet
    compose_fixture(path, slide_id="s01", source=source)
    record = tmp_path / "anchor-review.json"
    fixture_review(path, "s01", record)
    review = json.loads(record.read_text(encoding="utf-8"))
    assert review["style_reference"] == baseline
    assert "density" in review["design_review_guidance"]
    assert "visual_relationships" in review["design_review_guidance"]
    assert review["checks"]["style_consistency"]["status"] == "pass"
    execute(path, "accept", slide_id="s01", record=record)
    state = execute(path, "request", slide_id="s02", route="isolated-worker")
    page = state["pages"]["s02"]
    packet = json.loads((workspace(path) / page["request_snapshot"]).read_text(encoding="utf-8"))
    assert packet["style_reference"] == baseline
    assert Path(page["request_reference"]).read_bytes() == Path(reference["path"]).read_bytes()
    assert "style_anchor" not in packet
    assert "OLD PREVIEW INSTRUCTION" not in json.dumps(packet)
    assert Path(reference["source_path"]).name not in json.dumps(packet)
    assert "generation_reference" not in packet["style"]


@pytest.mark.parametrize("decision", ["selected", "delegated"])
@pytest.mark.parametrize("legacy", [False, True])
def test_selected_visual_requests_require_registered_single_page_baseline(production, decision, legacy):
    path, _ = production
    selected_style_fixture(path, decision=decision, register=False, legacy=legacy)
    # Reading and preparing a historical contract does not invent calibration.
    execute(path, "prepare")
    before = (workspace(path) / "state.json").read_bytes()
    with pytest.raises(ValueError, match="style-reference"):
        execute(path, "request", slide_id="s01", route="host")
    assert (workspace(path) / "state.json").read_bytes() == before


def test_locked_single_page_is_the_first_and_later_request_reference(production, tmp_path):
    path, source = production
    reference = selected_style_fixture(path, decision="locked-reference")
    first = execute(path, "request", slide_id="s01", route="host")["pages"]["s01"]
    assert Path(first["request_reference"]).read_bytes() == Path(reference["path"]).read_bytes()
    assert first["style_reference"]["kind"] == "single-page"
    compose_fixture(path, slide_id="s01", source=source)
    fixture_review(path, "s01", tmp_path / "locked-review.json")
    execute(path, "accept", slide_id="s01", record=tmp_path / "locked-review.json")
    second = execute(path, "request", slide_id="s02", route="host")["pages"]["s02"]
    assert second["style_reference"] == first["style_reference"]
    assert second["request_reference"] == first["request_reference"]


@pytest.mark.parametrize("damage", ["missing-reference", "wrong-reference", "wrong-source", "missing-check",
                                     "failed-check", "blank-observations", "wrong-target"])
def test_style_review_rejects_missing_or_mismatched_comparisons(production, tmp_path, damage):
    path, source = production
    selected_style_fixture(path)
    compose_fixture(path, slide_id="s01", source=source)
    record = tmp_path / "style-review.json"
    fixture_review(path, "s01", record)
    review = json.loads(record.read_bytes())
    if damage == "missing-reference":
        review.pop("style_reference")
    elif damage == "wrong-reference":
        review["style_reference"]["sha256"] = "0" * 64
    elif damage == "wrong-source":
        review["style_reference"]["source_sha256"] = "0" * 64
    elif damage == "missing-check":
        review["checks"].pop(STYLE_CHECK)
    elif damage == "failed-check":
        review["checks"][STYLE_CHECK]["status"] = "fail"
    elif damage == "blank-observations":
        review["checks"][STYLE_CHECK]["notes"] = " "
    else:
        review["checks"][STYLE_CHECK]["targets"] = ["title"]
    write(record, review)
    before = (workspace(path) / "state.json").read_bytes()
    with pytest.raises(ValueError, match="style reference|style_consistency"):
        execute(path, "accept", slide_id="s01", record=record)
    assert (workspace(path) / "state.json").read_bytes() == before
    assert execute(path, "status")["pages"]["s01"]["status"] == "generated"


def test_style_refine_requires_new_comparison_and_exports_current_pixels(production, tmp_path):
    from validate_page_spec import load_page_spec
    path, source = production
    selected_style_fixture(path)
    for slide_id in ("s01", "s02"):
        compose_fixture(path, slide_id=slide_id, source=source)
        fixture_review(path, slide_id, tmp_path / f"original-{slide_id}.json")
        execute(path, "accept", slide_id=slide_id, record=tmp_path / f"original-{slide_id}.json")
    before = execute(path, "status")["pages"]["s01"]
    spec = json.loads(path.read_bytes())
    final = path.parent / spec["slides"][0]["image_file"]
    corrected = tmp_path / "style-local-correction.png"
    with Image.open(final) as image:
        image.paste("white", (10, 10, 80, 40))
        image.save(corrected)
    refined = execute(path, "refine", slide_id="s01", source=corrected, base_image=final,
                      operation="Synthetic local text correction; no model call")["pages"]["s01"]
    assert refined["style_reference"] == before["style_reference"]
    assert refined["status"] == "generated" and "review_snapshot" not in refined
    with pytest.raises(ValueError, match="not approved"):
        load_page_spec(path, require_images=True)
    with pytest.raises(ValueError, match="Stale or mismatched"):
        execute(path, "accept", slide_id="s01", record=tmp_path / "original-s01.json")
    record = tmp_path / "refined-style-review.json"
    fixture_review(path, "s01", record)
    assert json.loads(record.read_bytes())["style_reference"] == before["style_reference"]
    execute(path, "accept", slide_id="s01", record=record)
    output = tmp_path / "style-refined.pptx"
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/build_image_ppt.py"),
                             str(path), str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    from pptx import Presentation
    assert Presentation(output).slides[0].shapes[0].image.blob == final.read_bytes()


@pytest.mark.parametrize("damage", ["reference_snapshot", "source_snapshot", "current-reference", "current-source",
                                     "review-reference", "review-failed", "missing-binding"])
def test_style_export_rechecks_reference_files_and_comparison_record(production, tmp_path, damage):
    from page_production import commit, encoded, store
    from validate_page_spec import load_page_spec
    path, source = production
    reference = selected_style_fixture(path)
    for slide_id in ("s01", "s02"):
        compose_fixture(path, slide_id=slide_id, source=source)
        record = tmp_path / f"accepted-{slide_id}.json"
        fixture_review(path, slide_id, record)
        execute(path, "accept", slide_id=slide_id, record=record)
    load_page_spec(path, require_images=True)
    root = workspace(path)
    state = json.loads((root / "state.json").read_bytes())
    page = state["pages"]["s01"]
    spec = json.loads(path.read_bytes())
    if damage in {"reference_snapshot", "source_snapshot"}:
        (root / page["style_reference"][damage]).write_bytes(b"Synthetic corrupt reference snapshot")
    elif damage.startswith("current-"):
        target = Path(reference["path" if damage == "current-reference" else "source_path"])
        with Image.open(target) as image:
            changed = image.convert("RGBA")
            changed.putpixel((1, 1), (255, 255, 255, 255))
            changed.save(target)
    else:
        # A deliberately malformed but content-addressed synthetic approval exercises
        # export's independent style gate instead of merely the outer state checksum.
        review = json.loads((root / page["review_snapshot"]).read_bytes())
        if damage == "review-reference":
            review["style_reference"]["sha256"] = "0" * 64
        elif damage == "missing-binding":
            page.pop("style_reference")
            review.pop("style_reference")
            review["checks"].pop(STYLE_CHECK)
        else:
            review["checks"][STYLE_CHECK]["status"] = "fail"
        page["review_snapshot"] = store(root, encoded(review), ".review.json")
        commit(path, spec, root, state)
    with pytest.raises(ValueError):
        load_page_spec(path, require_images=True)


def test_changed_selection_invalidates_prior_style_review_and_request(production, tmp_path):
    from style_reference import create_reference
    path, source = production
    selected_style_fixture(path)
    compose_fixture(path, slide_id="s01", source=source)
    old_review = tmp_path / "old-style-review.json"
    fixture_review(path, "s01", old_review)
    execute(path, "accept", slide_id="s01", record=old_review)
    before = execute(path, "status")["pages"]["s01"]
    spec = json.loads(path.read_bytes())
    changed = tmp_path / "new-selected-overview.png"
    Image.new("RGB", (1800, 1100), "#224488").save(changed)
    spec["style"]["tokens"]["reference_images"] = [changed.name]
    spec["style"].pop("generation_reference")
    spec["style"].update(option=3, choice="Synthetic blue", authorization="Synthetic changed selection")
    write(path, spec)
    create_reference(path, "styles/new-selected-single.png", box=[20, 70, 960, 540])
    current = execute(path, "request", slide_id="s01", route="host")["pages"]["s01"]
    assert current["status"] == "pending"
    assert current["contract_sha256"] != before["contract_sha256"]
    assert current["style_reference"]["sha256"] != before["style_reference"]["sha256"]
    # Reusing a retained original does not invent a new model call or old-style approval.
    compose_fixture(path, slide_id="s01", source=source)
    with pytest.raises(ValueError, match="Stale or mismatched"):
        execute(path, "accept", slide_id="s01", record=old_review)
    record = tmp_path / "new-style-review.json"
    fixture_review(path, "s01", record)
    assert json.loads(record.read_bytes())["style_reference"] == current["style_reference"]
    execute(path, "accept", slide_id="s01", record=record)


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
    with pytest.raises(ValueError, match="Final image changed"):
        execute(path, "request", slide_id="s01", route="host")
    retained = tmp_path / "unregistered-existing.png"
    target.rename(retained)
    compose_fixture(path, slide_id="s01", source=source)
    assert retained.read_bytes() == source.read_bytes()
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
