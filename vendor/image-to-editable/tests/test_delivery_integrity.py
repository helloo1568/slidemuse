"""Offline regression fixtures for recorded inputs and actual delivered content."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/image-to-editable-ppt/cli"
RUNTIME = CLI / "editppt/runtime"
sys.path.insert(0, str(RUNTIME))

from build_pptx_from_manifest import write_deck, write_pptx
from finalize_deck_run import recorded_deck
from validate_pptx import NS


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def command(*args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CLI) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, *map(str, args)], env=env, capture_output=True, text=True, encoding="utf-8")


def cli(*args):
    return command("-m", "editppt.cli", *args)


def success(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def manifest(text):
    return {
        "source": {"width_px": 1600, "height_px": 900},
        "slide": {"width": 13.333, "height": 7.5},
        "text_boxes": [{"text": text, "box_px": [100, 100, 1200, 100], "font_size": 24}],
        "required_text": [text],
        "shapes": [{"type": "ellipse", "box_px": [100, 300, 80, 80], "fill": "#112233"}],
        "images": [], "visual_inventory": [],
        "background_strategy": {"mode": "native-or-script", "comparison_note": "Synthetic white canvas"},
        "quality_checks": dict.fromkeys(["font_size_calibrated", "visual_inventory_matched",
                                         "background_strategy_checked", "shape_corner_geometry_checked"], True),
    }


def rewrite_pptx(path, change):
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    change(parts)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


def edit_xml(parts, name, change):
    tree = ET.fromstring(parts[name])
    change(tree)
    parts[name] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def validation_fixture(directory):
    entries, pages, notes = [], [], []
    for index, color in enumerate(("red", "blue"), 1):
        page = directory / f"pages/page_{index:03d}"
        page.mkdir(parents=True)
        Image.new("RGB", (40, 40), color).save(page / "asset.png")
        data = manifest(f"APPROVED PAGE {index}")
        data["images"] = [{"path": "asset.png", "box_px": [400, 300, 80, 80]}]
        data["asset_provenance"] = [{"path": "asset.png", "source_type": "user-provided",
                                     "source": "asset.png", "provenance_note": "Synthetic test asset"}]
        path = page / "manifest.json"
        write_json(path, data)
        write_json(page / "validation.json", {"passed": True})
        entries.append({"manifest": data, "manifest_path": path})
        pages.append({"page_id": f"page_{index:03d}", "manifest": str(path.relative_to(directory)),
                      "validation": str((page / "validation.json").relative_to(directory))})
        notes.append({"page_index": index, "text": f"AUTHORIZED NOTES {index}"})
    deck = {"job_dir": str(directory), "page_count": 2, "pages": pages,
            "notes_manifest": "notes_manifest.json", "slide": entries[0]["manifest"]["slide"]}
    write_json(directory / "deck_manifest.json", deck)
    write_json(directory / "notes_manifest.json", {"notes": notes})
    pptx = directory / "final.pptx"
    write_deck(deck, entries, pptx, notes)
    return pptx, directory / "deck_manifest.json"


def validate(pptx, deck):
    result = command(RUNTIME / "validate_pptx.py", pptx, "--deck-manifest", deck)
    return result, json.loads(result.stdout)


@pytest.mark.parametrize("change", ["blank", "text", "shape", "hidden_image", "missing_image", "image_bytes", "image_relation"])
def test_final_validation_checks_actual_objects_and_media(tmp_path, change):
    pptx, deck = validation_fixture(tmp_path)
    success(validate(pptx, deck)[0])

    def damage(parts):
        if change == "image_bytes":
            parts["ppt/media/image1.png"] = parts["ppt/media/image2.png"]
        elif change == "image_relation":
            edit_xml(parts, "ppt/slides/_rels/slide1.xml.rels", lambda root: next(
                rel for rel in root if rel.get("Type", "").endswith("/image")
            ).set("Target", "../media/image2.png"))
        else:
            def damage_slide(root):
                tree = root.find("p:cSld/p:spTree", NS)
                if change == "blank":
                    for child in list(tree):
                        if child.tag.rsplit("}", 1)[-1] in {"sp", "pic", "graphicFrame"}:
                            tree.remove(child)
                elif change == "text":
                    root.find(".//a:t", NS).text = "UNAPPROVED BODY"
                elif change == "shape":
                    root.find(".//p:sp/p:spPr/a:xfrm/a:off", NS).set("x", "1")
                elif change == "hidden_image":
                    root.find(".//p:pic/p:nvPicPr/p:cNvPr", NS).set("hidden", "1")
                else:
                    tree.remove(root.find(".//p:pic", NS))
            edit_xml(parts, "ppt/slides/slide1.xml", damage_slide)

    rewrite_pptx(pptx, damage)
    result, report = validate(pptx, deck)
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["page_contract_violations"]
    assert not report["passed"]


@pytest.mark.parametrize("change", ["detached", "swapped", "slide_order"])
def test_final_validation_follows_real_slide_and_notes_relationships(tmp_path, change):
    pptx, deck = validation_fixture(tmp_path)

    def damage(parts):
        if change == "slide_order":
            def reverse_slides(root):
                slides = root.find("p:sldIdLst", NS)
                slides[:] = list(reversed(slides))
            edit_xml(parts, "ppt/presentation.xml", reverse_slides)
        else:
            def change_notes(root):
                relation = next(rel for rel in root if rel.get("Type", "").endswith("/notesSlide"))
                if change == "detached":
                    root.remove(relation)
                else:
                    relation.set("Target", "../notesSlides/notesSlide2.xml")
            edit_xml(parts, "ppt/slides/_rels/slide1.xml.rels", change_notes)

    rewrite_pptx(pptx, damage)
    result, report = validate(pptx, deck)
    assert result.returncode == 1
    assert report["notes_hash_mismatches"]
    if change == "slide_order":
        assert report["page_contract_violations"]
    if change == "detached":
        assert not Presentation(pptx).slides[0].has_notes_slide
        assert report["notes_found"] == 1  # Only page 2 still has actual notes.


def test_final_validation_accepts_renamed_parts_and_relationship_ids(tmp_path):
    pptx, deck = validation_fixture(tmp_path)

    def rename(parts):
        parts["ppt/notesSlides/notesSlide99.xml"] = parts.pop("ppt/notesSlides/notesSlide1.xml")
        parts["ppt/notesSlides/_rels/notesSlide99.xml.rels"] = parts.pop("ppt/notesSlides/_rels/notesSlide1.xml.rels")
        parts["ppt/media/renamed.png"] = parts.pop("ppt/media/image1.png")
        def change_relationships(root):
            for relation in root:
                if relation.get("Type", "").endswith("/notesSlide"):
                    relation.set("Target", "../notesSlides/notesSlide99.xml")
                if relation.get("Type", "").endswith("/image"):
                    relation.set("Target", "/ppt/media/renamed.png")
                    relation.set("Id", "rId99")
        edit_xml(parts, "ppt/slides/_rels/slide1.xml.rels", change_relationships)
        edit_xml(parts, "ppt/slides/slide1.xml", lambda root: root.find(".//a:blip", NS).set(f"{{{NS['r']}}}embed", "rId99"))
        parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(b"notesSlide1.xml", b"notesSlide99.xml")

    rewrite_pptx(pptx, rename)
    result, report = validate(pptx, deck)
    success(result)
    assert report["notes_found"] == 2
    assert report["passed"]


def test_final_validation_requires_explicit_page_pass(tmp_path):
    pptx, deck = validation_fixture(tmp_path)
    write_json(tmp_path / "pages/page_001/validation.json", {"warnings": []})
    result, report = validate(pptx, deck)
    assert result.returncode == 1 and report["failed_page_validations"]


def test_finalize_uses_the_custom_recorded_manifest_and_validation(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (1600, 900), "white").save(source)
    job = tmp_path / "job"
    success(cli("prepare", source, "--job-dir", job, "--no-text-hints"))
    page = job / "pages/page_001"
    # The valid old outputs remain, making accidental use of defaults observable.
    for stem, text in (("manifest", "OLD PRICE 10"), ("revised", "APPROVED NEW PRICE 20")):
        data = manifest(text)
        path = page / f"{stem}.json"
        write_json(path, data)
        write_pptx(data, page / f"{stem}.pptx", path)
        success(command(RUNTIME / "validate_pptx.py", page / f"{stem}.pptx", "--manifest", path,
                        "--report", page / ("validation.json" if stem == "manifest" else "revised-validation.json")))
    for name in ("preview.png", "split_assets_contact.png"):
        Image.new("RGB", (64, 36), "white").save(page / name)
    write_json(page / "page_result.json", {"page_manifest": "revised.json", "page_pptx": "revised.pptx",
                                           "validation": "revised-validation.json"})
    (page / "worker-prompt.md").write_text("Synthetic fixture: use the approved price 20.", encoding="utf-8")
    success(cli("run", "dispatch", job, "--page", "1", "--agent-id", "synthetic-worker",
                "--prompt-file", page / "worker-prompt.md", "--local"))
    success(cli("run", "record", job, "--page", "1", "--agent-id", "synthetic-worker"))
    record = read_json(job / "page_jobs.json")["pages"][0]["result"]
    success(cli("run", "finalize", job))
    final = next((job / "final").glob("*.pptx"))
    text = "\n".join(shape.text for shape in Presentation(final).slides[0].shapes if shape.has_text_frame)
    assert "APPROVED NEW PRICE 20" in text and "OLD PRICE 10" not in text
    assembled = read_json(final.with_name(final.stem + "-assembly.json"))
    canonical = read_json(job / "deck_manifest.json")
    assert assembled["pages"][0]["manifest"] == canonical["pages"][0]["manifest"] == record["outputs"]["page_manifest"]
    assert assembled["pages"][0]["validation"] == record["outputs"]["validation"]
    assert assembled["pages"][0]["manifest_sha256"] == record["hashes"]["page_manifest"]
    assert read_json(job / "run_state.json")["status"] == "complete"
    success(validate(final, job / "deck_manifest.json")[0])


@pytest.mark.parametrize("change", ["reorder", "duplicate", "missing", "index"])
def test_finalize_rejects_inconsistent_page_identity(tmp_path, change):
    pages = [{"page_id": f"page_{i:03d}", "page_index": i} for i in (1, 2)]
    deck = {"run_id": "test", "pages": pages}
    jobs = {"run_id": "test", "pages": copy.deepcopy(pages)}
    if change == "reorder":
        jobs["pages"].reverse()
    elif change == "duplicate":
        jobs["pages"][1]["page_id"] = "page_001"
    elif change == "missing":
        jobs["pages"].pop()
    else:
        jobs["pages"][0]["page_index"] = 2
    with pytest.raises(SystemExit, match="identities/order|indices"):
        recorded_deck(tmp_path, deck, jobs)


def snapshots(path):
    return {str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
            for item in path.rglob("*") if item.is_file()}


def test_repeated_prepare_preserves_active_run_and_every_existing_file(tmp_path):
    source, replacement = tmp_path / "red.png", tmp_path / "blue.png"
    Image.new("RGB", (1600, 900), "red").save(source)
    Image.new("RGB", (1600, 900), "blue").save(replacement)
    job = tmp_path / "job"
    success(cli("prepare", source, "--job-dir", job, "--no-text-hints"))
    page = job / "pages/page_001"
    (page / "worker-prompt.md").write_text("Synthetic red page task", encoding="utf-8")
    write_json(page / "manifest.json", manifest("Existing work"))
    success(cli("run", "dispatch", job, "--page", "1", "--agent-id", "running-worker",
                "--prompt-file", page / "worker-prompt.md", "--local"))
    before = snapshots(job)
    result = cli("prepare", replacement, "--job-dir", job, "--no-text-hints")
    assert result.returncode != 0 and "Task directory is not empty" in result.stderr
    assert before == snapshots(job)
    assert read_json(job / "page_jobs.json")["pages"][0]["dispatch"]["agent_id"] == "running-worker"


@pytest.mark.parametrize("hidden", ["1", "true"])
@pytest.mark.parametrize("existing_empty", [False, True])
def test_hidden_picture_is_rejected_without_leaving_a_partial_run(tmp_path, hidden, existing_empty):
    image = tmp_path / "source.png"
    Image.new("RGB", (800, 450), "red").save(image)
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(8), Inches(4.5)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    picture = slide.shapes.add_picture(str(image), 0, 0, presentation.slide_width, presentation.slide_height)
    picture._element.nvPicPr.cNvPr.set("hidden", hidden)
    source = tmp_path / "source.pptx"
    presentation.save(source)
    job = tmp_path / "job"
    if existing_empty:
        job.mkdir()
    result = cli("prepare", source, "--job-dir", job, "--no-text-hints")
    assert result.returncode != 0 and "hidden picture" in result.stderr
    assert not job.exists() or not any(job.iterdir())
    assert not list(tmp_path.glob(".job-prepare-*"))


def test_prepare_accepts_empty_directory_and_commits_final_paths(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (800, 450), "white").save(source)
    job = tmp_path / "job"
    job.mkdir()
    success(cli("prepare", source, "--job-dir", job, "--no-text-hints"))
    assert read_json(job / "deck_manifest.json")["job_dir"] == str(job.resolve())
    for path in job.rglob("*.json"):
        assert ".job-prepare-" not in path.read_text(encoding="utf-8")
