import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/release_needed.py"


@pytest.fixture
def release_repo(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "release@example.test")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("version: 2.26.0\nfiles: []\n", encoding="utf-8")
    git("add", "manifest.yaml")
    git("commit", "-m", "Initial release")
    return tmp_path, manifest, git("rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("event", "version", "expected"),
    [
        ("push", "2.26.0", "false"),
        ("push", "2.26.1", "true"),
        ("workflow_dispatch", "2.26.0", "true"),
    ],
)
def test_release_gate(release_repo, event, version, expected):
    repo, manifest, before = release_repo
    manifest.write_text(f"version: {version}\nfiles: [SKILL.md]\n", encoding="utf-8")
    output = repo / "github-output.txt"
    env = dict(
        os.environ,
        GITHUB_EVENT_NAME=event,
        BEFORE_SHA=before if event == "push" else "",
        GITHUB_OUTPUT=str(output),
    )
    subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, env=env, check=True)
    assert output.read_text(encoding="utf-8").strip() == f"publish={expected}"


def test_release_workflow_only_publishes_when_gate_allows():
    workflow = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["on"]["push"]["paths"] == ["manifest.yaml"]
    validate = workflow["jobs"]["validate"]
    assert validate["outputs"]["publish"] == "${{ steps.release-needed.outputs.publish }}"
    assert workflow["jobs"]["publish"]["if"] == "needs.validate.outputs.publish == 'true'"
    assert any("bump manifest version" in step.get("run", "")
               for step in workflow["jobs"]["publish"]["steps"])


def test_release_version_references_are_consistent():
    version = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))["version"]
    assert f"# SlideMuse · {version}" in (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for name in ("README.md", "README.en.md"):
        assert f"/badge/version-{version}-" in (ROOT / name).read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    latest = next(line for line in changelog.splitlines() if line.startswith("## ["))
    assert latest.startswith(f"## [{version}]")
