import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_document_links_do_not_require_excluded_showcase_files():
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
    names = set(manifest["files"])
    for name in sorted(names):
        if not name.endswith(".md"):
            continue
        document = ROOT / name
        text = document.read_text(encoding="utf-8")
        links = re.findall(r"\]\(<?([^)>]+)>?\)", text)
        links += re.findall(r'(?:href|src)="([^"]+)"', text)
        for link in links:
            if re.match(r"^[A-Za-z]+:", link) or link.startswith("#") or "<" in link:
                continue
            raw = unquote(link.split("#")[0].split("?")[0])
            target = (document.parent / raw).resolve()
            if raw and target.is_relative_to(ROOT) and target.is_file():
                assert target.relative_to(ROOT).as_posix() in names, (name, link)


def test_manifest_packaged_zip_is_installable(tmp_path):
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
    archive = tmp_path / "release.zip"
    # Exercise the same file selection and archive layout as the release workflow.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name in manifest["files"]:
            output.write(ROOT / name, "slidemuse/" + name)
    bundle = tmp_path / "bundle"
    with zipfile.ZipFile(archive) as released:
        released.extractall(bundle)
    completed = subprocess.run(
        [sys.executable, str(bundle / "slidemuse" / "install.py"), "--client", "codex",
         "--home", str(tmp_path / "home"), "--skip-deps", "--json"],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    installed = Path(result["target"])
    installed_manifest = yaml.safe_load((installed / "manifest.yaml").read_text(encoding="utf-8"))
    assert installed_manifest["version"] == manifest["version"]
    production = subprocess.run(
        [sys.executable, str(installed / "slidemuse.py"), "produce", "status",
         str(installed / "examples/page-spec.example.json")],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(production.stdout)["pages"]["s01"]["status"] == "pending"
    assert not (installed / "examples/.page-spec-production").exists()
    assert (installed / "docs/cli.md").is_file()
    assert (installed / "docs/cli.en.md").is_file()
    assert (installed / "README.md").is_file()
    assert (installed / "docs/guide.md").is_file()
    assert (installed / "LICENSE").is_file()
    diagnosed = subprocess.run(
        [sys.executable, str(installed / "slidemuse.py"), "doctor", "--json"],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(diagnosed.stdout)["status"] in ("pass", "warning")
    subprocess.run(
        [sys.executable, str(installed / "slidemuse.py"), "validate",
         str(installed / "examples" / "page-spec.example.json"), "--strict"],
        check=True, capture_output=True, text=True,
    )
    assert not (installed / "showcase").exists()
    assert not any(name.startswith("showcase/") for name in manifest["files"])
    optional = subprocess.run(
        [sys.executable, str(installed / "slidemuse.py"), "sample"],
        capture_output=True, text=True, check=False,
    )
    assert optional.returncode == 2
    assert "sample.zip" in optional.stderr
    assert "Reinstall" not in optional.stderr
    # Exercise the new table helper from the actual manifest-built installation.
    merged = tmp_path / "merged-table.pptx"
    subprocess.run(
        [sys.executable, str(installed / "scripts/build_editable_ppt.py"),
         str(installed / "examples/merged-table.scene.json"), str(merged)],
        check=True, capture_output=True, text=True,
    )
    checked = subprocess.run(
        [sys.executable, str(installed / "scripts/audit_editability.py"), str(merged),
         "--scene", str(installed / "examples/merged-table.scene.json")],
        check=True, capture_output=True, text=True,
    )
    assert not json.loads(checked.stdout)["errors"]
    assert "Copyright (c) 2026 ningzimu" in (installed / "references/upstream-editable.md").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 ningzimu" in (installed / "vendor/codex-ppt/LICENSE").read_text(encoding="utf-8")
    backend = subprocess.run(
        [sys.executable, str(installed / "slidemuse.py"), "rebuild", "capabilities", "--verify-source"],
        check=True, capture_output=True, encoding="utf-8",
    )
    capabilities = json.loads(backend.stdout)
    assert capabilities["dependencies_ready"]
    assert not capabilities["source_integrity"]["mismatches"]
    generation = subprocess.run(
        [sys.executable, str(installed / "slidemuse.py"), "generate", "capabilities", "--verify-source"],
        check=True, capture_output=True, encoding="utf-8",
    )
    generate_capabilities = json.loads(generation.stdout)
    assert not generate_capabilities["source_integrity"]["mismatches"]
    assert (installed / "vendor/codex-ppt/skills/codex-ppt/references/清爽专业风.md").is_file()
    assert (installed / "references/generate-backend.md").is_file()
    assert (installed / "references/style-library.md").is_file()
    assert (installed / "requirements-generate.txt").is_file()


def test_separate_sample_rebuilds_with_core_runtime(tmp_path):
    # Exercise the actual optional release asset, including its original sealed inputs.
    unpacked = tmp_path / "sample"
    with zipfile.ZipFile(ROOT / "showcase/editable-irena/sample.zip") as archive:
        archive.extractall(unpacked)
    sample = unpacked / "editable-irena"
    output = tmp_path / "sample-output"
    subprocess.run(
        [sys.executable, str(sample / "reproduce.py"), "--verify",
         "--runtime", str(ROOT), "--output", str(output)],
        check=True, capture_output=True, text=True,
    )
    report = json.loads((output / "reproduction.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert len(report["decks"]) == 6
