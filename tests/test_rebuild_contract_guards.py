"""Real offline CLI regressions for independent reconstruction input contracts."""
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
from test_editable_backend import ROOT, RUNTIME, invoke


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def success(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def approved_job(directory, text="Revenue: 10 million", *, extra_elements=()):
    source = directory / "approved.png"
    image = Image.new("RGB", (640, 360), "white")
    ImageDraw.Draw(image).text((30, 30), text, fill="black")
    image.save(source)
    spec = json.loads((ROOT / "examples/page-spec.example.json").read_text(encoding="utf-8"))
    spec.update(content_policy="1.1", canvas={"width": 640, "height": 360},
                workflow={"content_mode": "reused", "approved_content_version": spec["content_version"],
                          "outline_ref": "Synthetic approved reconstruction fixture"})
    spec["style"].update(decision="locked-reference", authorization="Reuse the supplied test image")
    spec["slides"][0].update(id="s01", page_number=1, title=text, core_message=text,
        image_file=source.name, image_status="approved",
        image_origin={"kind": "provided", "source_ref": "Synthetic approved fixture",
                      "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        elements=[{"id": "title", "kind": "text", "role": "Title", "native_intent": "native",
                   "source_ref": "Synthetic fixture", "confirmation_status": "confirmed", "text": text},
                  *copy.deepcopy(extra_elements)])
    path = directory / "approved.json"
    write_json(path, spec)
    job = directory / "run"
    success(invoke("--offline", "prepare", "--page-spec", path, "--job-dir", job, "--no-text-hints"))
    return job


def manifest_for(job, text="Revenue: 10 million"):
    request = json.loads((job / "pages/page_001/page_request.json").read_text(encoding="utf-8"))
    return {"source": {"width_px": 640, "height_px": 360}, "slide": request["slide"],
            "content_box": request["content_box"],
            "text_boxes": [{"text": text, "box_px": [30, 30, 570, 60], "font_size": 20, "fit_text": False}],
            "required_text": [text], "shapes": [], "tables": [], "images": [], "visual_inventory": [],
            "background_strategy": {"mode": "native-or-script", "comparison_note": "Synthetic white canvas"},
            "quality_checks": dict.fromkeys(["font_size_calibrated", "visual_inventory_matched",
                "background_strategy_checked", "shape_corner_geometry_checked"], True)}


def record_page(job, manifest):
    page = job / "pages/page_001"
    write_json(page / "manifest.json", manifest)
    success(invoke("--offline", "page", "build", page))
    success(invoke("--offline", "page", "validate", page, "--report", "validation.json"))
    success(invoke("page-prompt", job, "--page", "1", "--out", "worker-prompt.md"))
    shutil.copyfile(page / "preview.png", page / "split_assets_contact.png")
    write_json(page / "page_result.json", {"synthetic_fixture": True})
    success(invoke("--offline", "run", "dispatch", job, "--page", "1", "--agent-id", "synthetic-local",
                   "--prompt-file", page / "worker-prompt.md", "--local"))
    success(invoke("--offline", "run", "record", job, "--page", "1", "--agent-id", "synthetic-local"))


def test_changed_native_body_cannot_finalize_against_approved_spec(tmp_path):
    job = approved_job(tmp_path)
    record_page(job, manifest_for(job, "Revenue: 90 million"))
    deck = json.loads((job / "deck_manifest.json").read_text(encoding="utf-8"))
    output = job / deck["output"]
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = b"synthetic prior delivery must survive failed finalization"
    output.write_bytes(previous)
    result = invoke("--offline", "run", "finalize", job)
    assert result.returncode != 0
    assert "approved native text is missing or changed" in result.stdout
    assert output.read_bytes() == previous
    assert json.loads((job / "page_jobs.json").read_text())["pages"][0]["status"] == "recorded"


def test_approved_text_can_be_split_into_runs_and_lines(tmp_path):
    job = approved_job(tmp_path)
    manifest = manifest_for(job)
    manifest["text_boxes"][0].pop("text")
    manifest["text_boxes"][0]["paragraphs"] = [
        {"runs": [{"text": "Revenue: "}, {"text": "10 "}]}, {"text": "million"}]
    record_page(job, manifest)
    success(invoke("--offline", "run", "finalize", job))
    report = json.loads((job / "final/validation.json").read_text())
    assert report["passed"] and not report["approved_content_errors"]
    assert report["approved_content_checks"][0]["native_text_checked"] == 1


@pytest.mark.parametrize("changed", [False, True])
def test_native_table_checks_independent_approved_cells(tmp_path, changed):
    table = {"id": "figures", "kind": "table", "role": "Evidence", "native_intent": "native",
             "confirmation_status": "confirmed", "source_ref": "Synthetic data",
             "data": {"rows": [["Quarter", "Revenue"], ["Q1", 10]]}}
    job = approved_job(tmp_path, extra_elements=[table])
    manifest = manifest_for(job)
    manifest["tables"] = [{"box_px": [30, 130, 570, 160], "style": {"font_size": 18, "fit_text": False},
                           "cells": [["Quarter", "Revenue"], ["Q1", "90" if changed else "10.0"]]}]
    record_page(job, manifest)
    result = invoke("--offline", "run", "finalize", job)
    assert (result.returncode != 0) is changed, result.stdout + result.stderr
    if changed:
        assert "approved native table is missing or its rows/cells differ" in result.stdout


def load_content_checker():
    spec = importlib.util.spec_from_file_location("contract_guard_test_content", RUNTIME / "approved_content.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("actual", ["132%", "-32%", "+32%", "32.5%", "3.2%"])
def test_numeric_matching_does_not_accept_substrings_or_changed_signs(actual):
    assert not load_content_checker().text_present("32%", [actual])


def test_native_number_cannot_be_assembled_from_unrelated_text_objects():
    module = load_content_checker()
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    for index, text in enumerate(["3", "2%"]):
        page.shapes.add_textbox(Inches(index * 4), 0, Inches(2), Inches(1)).text = text
    slide = {"id": "s1", "elements": [{"id": "number", "kind": "text", "text": "32%",
        "native_intent": "native", "confirmation_status": "confirmed"}]}
    result = module.check_approved_slide(slide, ET.fromstring(page._element.xml))
    assert result["errors"] == [{"element_id": "number", "expected": "32%",
                                  "reason": "approved native text is missing or changed"}]


def test_raster_content_and_semantic_claims_are_not_native_ocr_requirements():
    check = load_content_checker().check_approved_slide
    root = ET.fromstring('<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
    slide = {"id": "s1", "title": "Raster title", "core_message": "Semantic claim",
             "required_visible_values": ["32%"], "elements": [
        {"id": "title", "kind": "text", "text": "Raster title", "native_intent": "raster", "confirmation_status": "confirmed"},
        {"id": "chart", "kind": "chart", "native_intent": "raster", "data": {"series": [32]}, "confirmation_status": "confirmed"}]}
    result = check(slide, root)
    assert result["errors"] == [] and result["native_text_checked"] == 0
    assert len(result["visual_review_required"]) == 3


def test_native_chart_cache_matches_approved_categories_and_values():
    module = load_content_checker()
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    data = CategoryChartData()
    data.categories = ["A", "B"]
    data.add_series("Revenue", [10, 20])
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, 0, 0, Inches(6), Inches(4), data).chart
    approved = {"id": "s1", "elements": [{"id": "chart", "kind": "chart", "native_intent": "native",
        "confirmation_status": "confirmed", "data": {"categories": ["A", "B"],
        "series": [{"name": "Revenue", "values": [10, 20]}]}}]}
    root = ET.fromstring(slide._element.xml)
    chart_root = ET.fromstring(chart._chartSpace.xml)
    assert not module.check_approved_slide(approved, root, [chart_root])["errors"]
    approved["elements"][0]["data"]["series"][0]["values"][0] = 90
    assert module.check_approved_slide(approved, root, [chart_root])["errors"]


def test_registered_original_foreground_passes_real_validation_and_finalization(tmp_path):
    job = approved_job(tmp_path)
    original = tmp_path / "official-logo.png"
    image = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 20, 80, 60), fill="blue")
    image.save(original)
    registered = success(invoke("--offline", "preserve-asset", job, "--page", "1", "--source", original,
                                "--asset-id", "official-logo", "--note", "Original user-supplied logo"))
    fragment = json.loads(registered.stdout)
    manifest = manifest_for(job)
    manifest["images"] = [{"path": fragment["asset_provenance"]["path"], "box_px": [30, 130, 100, 80]}]
    manifest["visual_inventory"] = [fragment["visual_inventory"]]
    manifest["asset_provenance"] = [fragment["asset_provenance"]]
    record_page(job, manifest)
    success(invoke("--offline", "run", "finalize", job))
    assert json.loads((job / "final/validation.json").read_text())["passed"]
    assert original.read_bytes() == (job / "pages/page_001" / manifest["images"][0]["path"]).read_bytes()


def test_preserve_original_emits_utf8_under_ascii_io_encoding(tmp_path, monkeypatch):
    job = approved_job(tmp_path)
    original = tmp_path / "原始透明标志.png"
    note = "用户提供的原始标志，保留中文来源说明"
    Image.new("RGBA", (50, 50), "blue").save(original)
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    result = success(invoke("--offline", "preserve-asset", job, "--page", "1", "--source", original,
                            "--asset-id", "official-logo", "--note", note))
    fragment = json.loads(result.stdout)
    assert fragment["asset_provenance"]["provenance_note"] == note
    receipt = json.loads((job / "input/preserved-originals/official-logo/registration.json").read_text(encoding="utf-8"))
    assert receipt["source_name"] == original.name and receipt["note"] == note
    assert (job / "pages/page_001" / fragment["asset_provenance"]["path"]).read_bytes() == original.read_bytes()


@pytest.mark.parametrize("mutation", ["unregistered", "asset_changed", "source_changed", "fake_id", "source_redirected"])
def test_foreground_original_requires_independent_registration_and_exact_bytes(tmp_path, mutation):
    job = approved_job(tmp_path)
    source = tmp_path / "logo.png"
    Image.new("RGBA", (50, 50), "blue").save(source)
    fragment = json.loads(success(invoke("preserve-asset", job, "--page", "1", "--source", source,
                                        "--asset-id", "logo", "--note", "Synthetic original input")).stdout)
    page = job / "pages/page_001"
    entry = fragment["asset_provenance"]
    if mutation == "unregistered":
        entry.pop("original_asset_id")
    elif mutation == "asset_changed":
        Image.new("RGBA", (50, 50), "red").save(page / entry["path"])
    elif mutation == "source_changed":
        Image.new("RGBA", (50, 50), "red").save(page / entry["source"])
    elif mutation == "fake_id":
        entry["original_asset_id"] = "fake-receipt"
    else:
        entry["source"] = entry["path"]
    manifest = manifest_for(job)
    manifest.update(images=[{"path": entry["path"], "box_px": [30, 130, 50, 50]}],
                    visual_inventory=[fragment["visual_inventory"]], asset_provenance=[entry])
    write_json(page / "manifest.json", manifest)
    success(invoke("--offline", "page", "build", page))
    result = invoke("--offline", "page", "validate", page)
    assert result.returncode != 0
    assert json.loads(result.stdout)["page_contract_violations"]


def test_cannot_register_a_run_page_crop_as_a_user_original(tmp_path):
    job = approved_job(tmp_path)
    result = invoke("preserve-asset", job, "--page", "1", "--source", job / "pages/page_001/source.png",
                    "--asset-id", "pretend-original", "--note", "Self-asserted source")
    assert result.returncode != 0 and "independent supplied original" in result.stderr


@pytest.mark.parametrize("failure", ["missing_asset", "preview_failure", "invalid_xml"])
def test_page_build_failure_keeps_existing_pptx_and_preview(tmp_path, failure):
    job = approved_job(tmp_path)
    page = job / "pages/page_001"
    manifest = manifest_for(job)
    write_json(page / "manifest.json", manifest)
    success(invoke("--offline", "page", "build", page))
    before = {name: (page / name).read_bytes() for name in ("page.pptx", "preview.png")}
    if failure == "missing_asset":
        manifest["images"] = [{"path": "not-copied-yet.png", "box_px": [30, 130, 100, 80]}]
    elif failure == "preview_failure":
        manifest["preview_scale"] = "not-an-integer"
    else:
        manifest["text_boxes"][0]["text"] = "invalid XML character \u0001"
    write_json(page / "manifest.json", manifest)
    result = invoke("--offline", "page", "build", page)
    assert result.returncode != 0
    assert all((page / name).read_bytes() == data for name, data in before.items())
    assert not list(page.glob(".page-build-*")) and not list(page.glob(".page-preview-*"))


def test_successful_page_build_replaces_previous_native_text(tmp_path):
    job = approved_job(tmp_path)
    page = job / "pages/page_001"
    for value in ("Old page", "New page"):
        write_json(page / "manifest.json", manifest_for(job, value))
        success(invoke("--offline", "page", "build", page))
    text = "".join(shape.text for shape in Presentation(page / "page.pptx").slides[0].shapes if shape.has_text_frame)
    assert text == "New page"


def load_page_builder(monkeypatch):
    monkeypatch.syspath_prepend(str(RUNTIME))
    spec = importlib.util.spec_from_file_location("contract_guard_test_builder", RUNTIME / "build_pptx_from_manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("has_previous", [False, True])
def test_page_publication_failure_restores_both_outputs(tmp_path, monkeypatch, has_previous):
    job = approved_job(tmp_path)
    page = job / "pages/page_001"
    manifest_path = page / "manifest.json"
    write_json(manifest_path, manifest_for(job, "Old revision"))
    if has_previous:
        success(invoke("--offline", "page", "build", page))
    outputs = [page / "page.pptx", page / "preview.png"]
    before = {path: path.read_bytes() for path in outputs if path.exists()}
    write_json(manifest_path, manifest_for(job, "New revision"))
    builder = load_page_builder(monkeypatch)
    replace = builder.os.replace
    failed = False

    def fail_preview_publication(source, destination):
        nonlocal failed
        if (not failed and Path(destination) == outputs[1]
                and Path(source).parent.name.startswith(".page-preview-")):
            failed = True
            raise OSError("Synthetic preview publication failure")
        return replace(source, destination)

    monkeypatch.setattr(builder.os, "replace", fail_preview_publication)
    monkeypatch.setattr(sys, "argv", ["build_pptx_from_manifest.py", str(manifest_path),
                                     "--out", str(outputs[0]), "--preview", str(outputs[1])])
    with pytest.raises(OSError, match="Synthetic preview publication failure"):
        builder.main()
    assert failed
    for path in outputs:
        if path in before:
            assert path.read_bytes() == before[path]
        else:
            assert not path.exists()
    assert not list(page.glob(".page-*"))


def test_preview_directory_is_rejected_before_replacing_pptx(tmp_path):
    job = approved_job(tmp_path)
    page = job / "pages/page_001"
    manifest = page / "manifest.json"
    write_json(manifest, manifest_for(job, "Old revision"))
    success(invoke("--offline", "page", "build", page))
    old_pptx = (page / "page.pptx").read_bytes()
    directory = page / "preview-directory"
    directory.mkdir()
    (directory / "existing.png").write_bytes(b"Existing directory contents")
    write_json(manifest, manifest_for(job, "New revision"))
    result = subprocess.run([sys.executable, str(RUNTIME / "build_pptx_from_manifest.py"), str(manifest),
                             "--out", str(page / "page.pptx"), "--preview", str(directory)],
                            check=False, text=True, capture_output=True)
    assert result.returncode != 0 and "output path is not a file" in result.stderr
    assert (page / "page.pptx").read_bytes() == old_pptx
    assert (directory / "existing.png").read_bytes() == b"Existing directory contents"
    assert not list(page.glob(".page-*"))
