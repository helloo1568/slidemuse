from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import install as installer

ROOT = Path(__file__).resolve().parents[1]


def test_success_output_supports_windows_gbk(monkeypatch) -> None:
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="gbk")
    monkeypatch.setattr(sys, "stdout", stdout)
    installer.emit({"client": "codex", "skill": "slidemuse",
                    "target": "C:/用户/.agents/skills/slidemuse"}, as_json=False)
    stdout.flush()
    output = buffer.getvalue().decode("gbk")
    assert "SlideMuse installed successfully" in output
    assert "C:/用户/.agents/skills/slidemuse" in output


def test_json_output_preserves_unicode_in_utf8_and_gbk_pipes(monkeypatch) -> None:
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="gbk")
    monkeypatch.setattr(sys, "stdout", stdout)
    result = {"client": "workbuddy", "skill": "slidemuse",
              "target": "D:/用户/作品🎨/.workbuddy/skills/slidemuse"}
    installer.emit(result, as_json=True)
    stdout.flush()
    assert json.loads(buffer.getvalue().decode("utf-8")) == result


def test_skill_frontmatter_uses_slidemuse() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "name: slidemuse" in text


def test_installer_dry_run_targets_slidemuse(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "install.py"),
            "--client",
            "codex",
            "--home",
            str(tmp_path),
            "--dry-run",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["skill"] == "slidemuse"
    assert Path(result["target"]) == tmp_path / ".agents" / "skills" / "slidemuse"


def test_installer_auto_rejects_multiple_detected_clients(tmp_path: Path) -> None:
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".claude").mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "install.py"),
            "--home",
            str(tmp_path),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Multiple supported clients detected" in completed.stderr
    assert "--client codex" in completed.stderr
    assert "--client claude" in completed.stderr


NEW_CLIENTS = [
    ("workbuddy", ".workbuddy"),
    ("trae", ".trae"),
    ("trae-cn", ".trae-cn"),
    ("qoder", ".qoder"),
    ("qoder-cn", ".qoder-cn"),
]


@pytest.mark.parametrize(("client", "profile"), NEW_CLIENTS)
def test_new_client_install_and_upgrade_are_usable_outside_repository(
    tmp_path: Path, client: str, profile: str,
) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    sibling = home / profile / "skills" / "unrelated-skill"
    sibling.mkdir(parents=True)
    sentinel = sibling / "SKILL.md"
    sentinel.write_text("keep this skill", encoding="utf-8")
    command = [sys.executable, str(ROOT / "install.py"), "--client", client,
               "--home", str(home), "--skip-deps", "--json"]
    for _ in range(2):
        completed = subprocess.run(command, cwd=cwd, check=True, capture_output=True,
                                   text=True, encoding="utf-8")
        result = json.loads(completed.stdout)
        target = Path(result["target"])
        assert target == home / profile / "skills" / "slidemuse"
        assert (target / "SKILL.md").is_file()
        assert (target / "docs" / "clients.md").is_file()
        marker = json.loads((target / ".skill-install.json").read_text(encoding="utf-8"))
        assert marker["client"] == client
        assert result["invocation"] == installer.skill_invocation(client, "slidemuse")
        assert sentinel.read_text(encoding="utf-8") == "keep this skill"
    subprocess.run([sys.executable, str(target / "slidemuse.py"), "validate",
                    str(target / "examples" / "page-spec.example.json"), "--strict"],
                   cwd=cwd, check=True, capture_output=True, text=True)
    assert not list(target.parent.glob(".slidemuse-stage-*"))
    assert not list(target.parent.glob(".slidemuse-backup-*"))


@pytest.mark.parametrize(("client", "profile"), NEW_CLIENTS)
def test_auto_detects_native_client_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str, profile: str,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda command: None)
    (tmp_path / profile).mkdir()
    assert installer.detect_client(tmp_path) == client


@pytest.mark.parametrize(("client", "profile", "command"), [
    ("trae-cn", ".trae-cn", "trae"),
    ("qoder-cn", ".qoder-cn", "qodercli"),
])
def test_shared_cli_does_not_misidentify_cn_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str, profile: str, command: str,
) -> None:
    (tmp_path / profile).mkdir()
    monkeypatch.setattr(installer.shutil, "which",
                        lambda name: "/bin/" + command if name == command else None)
    assert installer.detect_client(tmp_path) == client


def test_multiple_new_clients_require_explicit_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda command: None)
    for profile in (".workbuddy", ".trae-cn", ".qoder-cn"):
        (tmp_path / profile).mkdir()
    with pytest.raises(RuntimeError, match="Multiple supported clients detected") as error:
        installer.detect_client(tmp_path)
    for client in ("workbuddy", "trae-cn", "qoder-cn"):
        assert f"--client {client}" in str(error.value)
    assert not any(tmp_path.glob("*/skills/slidemuse"))


def test_dry_run_finds_legacy_codex_install_in_both_locations(tmp_path: Path) -> None:
    for parent in (tmp_path / ".agents" / "skills", tmp_path / ".codex" / "skills"):
        (parent / installer.LEGACY_SKILL_NAME).mkdir(parents=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "install.py"),
            "--client",
            "codex",
            "--home",
            str(tmp_path),
            "--dry-run",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert {Path(path) for path in result["legacy_targets"]} == {
        tmp_path / ".agents" / "skills" / installer.LEGACY_SKILL_NAME,
        tmp_path / ".codex" / "skills" / installer.LEGACY_SKILL_NAME,
    }


def existing_install(target: Path) -> None:
    target.mkdir(parents=True)
    (target / ".skill-install.json").write_text('{"installer":"slidemuse"}')
    (target / "SKILL.md").write_text("working old skill")
    (target / ".skill-python").write_text("old python")


def test_replace_directory_retries_transient_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, destination = tmp_path / "stage", tmp_path / "installed"
    source.mkdir()
    original_replace = Path.replace
    attempts = 0
    delays: list[float] = []

    def locked_once(path: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("virtual environment temporarily locked")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", locked_once)
    monkeypatch.setattr(installer, "retryable_replace_error", lambda exc: True)
    monkeypatch.setattr(installer.time, "sleep", delays.append)

    installer.replace_directory(source, destination)

    assert attempts == 2
    assert delays == [0.25]
    assert not source.exists() and destination.is_dir()


def test_replace_directory_preserves_permanent_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "stage"
    source.mkdir()
    attempts = 0

    def denied(path: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        raise PermissionError("permanent denial")

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr(installer, "retryable_replace_error", lambda exc: False)
    with pytest.raises(PermissionError, match="permanent denial"):
        installer.replace_directory(source, tmp_path / "installed")

    assert attempts == 1
    assert source.is_dir()


def test_dependency_failure_keeps_existing_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".agents" / "skills" / "slidemuse"
    existing_install(target)

    def fail_install(staging: Path, final_target: Path) -> Path:
        raise subprocess.CalledProcessError(1, "pip")

    monkeypatch.setattr(installer, "install_dependencies", fail_install)
    with pytest.raises(subprocess.CalledProcessError):
        installer.install_skill(ROOT, target, "codex", "slidemuse", False, False)

    assert (target / "SKILL.md").read_text() == "working old skill"
    assert (target / ".skill-python").read_text() == "old python"
    assert list(target.parent.glob(".slidemuse-stage-*")) == []


def test_failed_final_validation_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".agents" / "skills" / "slidemuse"
    existing_install(target)

    def fake_install(staging: Path, final_target: Path) -> Path:
        (staging / ".venv").mkdir()
        (staging / ".skill-python").write_text(
            str(installer.venv_python(final_target / ".venv"))
        )
        return installer.venv_python(staging / ".venv")

    def fake_validate(location: Path, python: Path) -> None:
        if location == target:
            raise RuntimeError("relocated runtime failed validation")

    monkeypatch.setattr(installer, "install_dependencies", fake_install)
    monkeypatch.setattr(installer, "validate_install", fake_validate)
    with pytest.raises(RuntimeError, match="relocated runtime failed validation"):
        installer.install_skill(ROOT, target, "codex", "slidemuse", False, False)

    assert (target / "SKILL.md").read_text() == "working old skill"
    assert (target / ".skill-python").read_text() == "old python"
    assert list(target.parent.glob(".slidemuse-backup-*")) == []
    assert list(target.parent.glob(".slidemuse-failed-*")) == []


def test_skip_deps_upgrade_drops_stale_python_pointer(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "slidemuse"
    existing_install(target)

    installer.install_skill(ROOT, target, "codex", "slidemuse", False, True)

    assert (target / "SKILL.md").read_text(encoding="utf-8").startswith("---")
    assert not (target / ".skill-python").exists()
    assert not (target / "showcase").exists()
    assert "sample_included" not in json.loads(
        (target / ".skill-install.json").read_text(encoding="utf-8"))


def test_core_upgrade_removes_legacy_showcase(tmp_path: Path) -> None:
    # Older installs could carry the sample; a core install must not keep it.
    target = tmp_path / "installed"
    existing_install(target)
    old_sample = target / "showcase/editable-irena"
    old_sample.mkdir(parents=True)
    (old_sample / "old-demo.pptx").write_bytes(b"old demo")
    installer.install_skill(ROOT, target, "codex", "slidemuse", False, True)
    assert not (target / "showcase").exists()
    assert (target / "slidemuse.py").is_file()
