import os
import shutil
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
    quality = workflow["jobs"]["quality"]
    assert quality["needs"] == "validate"
    assert quality["if"] == "needs.validate.outputs.publish == 'true'"
    assert quality["uses"] == "./.github/workflows/ci.yml"
    publish = workflow["jobs"]["publish"]
    assert set(publish["needs"]) == {"validate", "quality"}
    assert publish["if"] == "needs.validate.outputs.publish == 'true' && needs.quality.result == 'success'"
    assert any("bump manifest version" in step.get("run", "")
               for step in publish["steps"])
    # Gate checks and packaging must inspect exactly the commit being released.
    for job in (validate, publish):
        checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["ref"] == "${{ github.sha }}"


def test_release_reuses_all_platform_backend_and_render_checks():
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert "workflow_call" in workflow["on"]
    jobs = workflow["jobs"]
    assert {"test", "real-render"} <= jobs.keys()
    matrix = jobs["test"]["strategy"]["matrix"]
    assert set(matrix["os"]) == {"ubuntu-latest", "windows-latest"}
    assert set(matrix["python-version"]) == {"3.10", "3.12", "3.13"}
    commands = "\n".join(s.get("run", "") for s in jobs["test"]["steps"])
    for required in ("pytest tests/", "pytest vendor/image-to-editable/tests/",
                     "pytest vendor/codex-ppt/tests/", "--with-editable --with-generate"):
        assert required in commands
    assert any("verify_render_backend.py" in s.get("run", "")
               for s in jobs["real-render"]["steps"])
    for job in jobs.values():
        checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["ref"] == "${{ github.sha }}"


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"),
                    reason="The showcase workflow runs in Ubuntu bash")
def test_showcase_workflow_commits_new_untracked_previews(tmp_path):
    workflow = yaml.load(
        (ROOT / ".github/workflows/optimize-showcase.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    command = next(s["run"] for s in workflow["jobs"]["optimize"]["steps"]
                   if s.get("name") == "Commit optimized previews")
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-b", "main")
    git("config", "user.name", "Preview Test")
    git("config", "user.email", "preview@example.test")
    for name in ("README.md", "README.en.md"):
        (repo / name).write_text("Unchanged documentation", encoding="utf-8")
    previews = repo / "showcase/preview"
    previews.mkdir(parents=True)
    (repo / "showcase/new.png").write_bytes(b"source from triggering commit")
    git("add", ".")
    git("commit", "-m", "Add showcase source")
    git("remote", "add", "origin", str(remote))
    git("push", "-u", "origin", "main")
    previous = git("rev-parse", "HEAD")
    (previews / "new.webp").write_bytes(b"new generated preview")

    subprocess.run(["bash", "-e", "-o", "pipefail", "-c", command],
                   cwd=repo, check=True, capture_output=True, text=True)
    assert git("ls-files", "--error-unmatch", "showcase/preview/new.webp")
    published = git("rev-parse", "HEAD")
    assert published != previous
    assert git("rev-parse", "origin/main") == published
    repeated = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", command],
                              cwd=repo, check=True, capture_output=True, text=True)
    assert "No showcase preview changes." in repeated.stdout
    assert git("rev-parse", "HEAD") == published


def test_release_version_references_are_consistent():
    version = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))["version"]
    assert f"# SlideMuse · {version}" in (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for name in ("README.md", "README.en.md"):
        assert f"/badge/version-{version}-" in (ROOT / name).read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    latest = next(line for line in changelog.splitlines() if line.startswith("## ["))
    assert latest.startswith(f"## [{version}]")
