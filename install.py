from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import venv
from pathlib import Path

BRAND_NAME = "SlideMuse"
LEGACY_SKILL_NAME = "image-ppt"

CLIENT_DIRS = {
    "codex": Path(".agents") / "skills",
    "claude": Path(".claude") / "skills",
    "opencode": Path(".config") / "opencode" / "skills",
    "workbuddy": Path(".workbuddy") / "skills",
    "trae": Path(".trae") / "skills",
    "trae-cn": Path(".trae-cn") / "skills",
    "qoder": Path(".qoder") / "skills",
    "qoder-cn": Path(".qoder-cn") / "skills",
}

CLIENT_COMMANDS = {
    "codex": ("codex",),
    "claude": ("claude",),
    "opencode": ("opencode",),
    "workbuddy": ("workbuddy",),
    "trae": ("trae",),
    "qoder": ("qoder", "qodercli"),
}

RUNTIME_PATHS = (
    "slidemuse.py",
    "SKILL.md",
    "manifest.yaml",
    "requirements.txt",
    "scripts",
    "references",
    "agents",
    "examples",
)

OPTIONAL_RUNTIME_PATHS = ("docs", "vendor")
OPTIONAL_RUNTIME_FILES = ("README.md", "README.en.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE",
                          "requirements-editable.txt", "requirements-generate.txt")


def read_skill_name(root: Path) -> str:
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(
        r"^---\s*$.*?^name:\s*([A-Za-z0-9._-]+)\s*$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not read skill name from SKILL.md frontmatter.")
    return match.group(1)


def detect_client(home: Path) -> str:
    markers = {client: (directory.parent,) for client, directory in CLIENT_DIRS.items()}
    markers["codex"] += (Path(".codex"),)
    candidates = [client for client, paths in markers.items()
                  if any((home / path).is_dir() for path in paths)]
    for client, commands in CLIENT_COMMANDS.items():
        # Regional IDEs can expose the same executable as the international IDE.
        # A discovered CN profile must not invent a second international profile.
        if client in candidates or f"{client}-cn" in candidates:
            continue
        if any(shutil.which(command) for command in commands):
            candidates.append(client)

    if not candidates:
        return "codex"
    if len(candidates) == 1:
        return candidates[0]
    detected = ", ".join(candidates)
    options = ", ".join(f"--client {client}" for client in CLIENT_DIRS)
    raise RuntimeError(
        f"Multiple supported clients detected: {detected}. "
        f"Re-run with one of: {options}."
    )


def skill_invocation(client: str, skill_name: str) -> str:
    if client == "codex":
        return f"${skill_name}"
    if client in ("claude", "qoder", "qoder-cn"):
        return f"/{skill_name}"
    return f"Use the {skill_name} skill"


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def check_target(target: Path, force: bool) -> None:
    marker = target / ".skill-install.json"
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise RuntimeError(f"{target} is not a regular skill directory.")
    if target.exists() and not marker.exists() and any(target.iterdir()) and not force:
        raise RuntimeError(
            f"{target} already exists and was not created by this installer. "
            "Use --force only if you intend to replace it."
        )


def copy_runtime(root: Path, target: Path) -> None:
    missing = [str(root / name) for name in RUNTIME_PATHS if not (root / name).exists()]
    if missing:
        raise RuntimeError(f"Missing runtime paths: {', '.join(missing)}")
    paths = (*RUNTIME_PATHS, *(name for name in OPTIONAL_RUNTIME_PATHS if (root / name).is_dir()),
             *(name for name in OPTIONAL_RUNTIME_FILES if (root / name).is_file()))
    for name in paths:
        source = root / name
        destination = target / name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def install_dependencies(target: Path, final_target: Path) -> Path:
    env_dir = target / ".venv"
    python = venv_python(env_dir)
    if not python.exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(env_dir)
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(target / "requirements.txt"),
        ],
        check=True,
    )
    (target / ".skill-python").write_text(
        str(venv_python(final_target / ".venv")) + "\n",
        encoding="utf-8",
    )
    return python


def validate_install(target: Path, python: Path) -> None:
    subprocess.run(
        [
            str(python),
            str(target / "scripts" / "validate_page_spec.py"),
            str(target / "examples" / "page-spec.example.json"),
            "--strict",
        ],
        check=True,
    )


def retryable_replace_error(exc: OSError) -> bool:
    return os.name == "nt" and getattr(exc, "winerror", None) in (5, 32, 33)


def replace_directory(source: Path, destination: Path) -> None:
    """Allow Windows a moment to release a newly used virtual environment."""
    delays = (0, 0.25, 0.5, 1, 2, 4)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            source.replace(destination)
            return
        except OSError as exc:
            if attempt == len(delays) - 1 or not retryable_replace_error(exc):
                raise


def legacy_installs(home: Path, client: str, skill_name: str) -> list[Path]:
    if skill_name == LEGACY_SKILL_NAME:
        return []
    parents = [home / CLIENT_DIRS[client]]
    if client == "codex":
        parents.append(home / ".codex" / "skills")
    return [parent / LEGACY_SKILL_NAME for parent in parents if (parent / LEGACY_SKILL_NAME).exists()]


def install_skill(
    root: Path, target: Path, client: str, skill_name: str, force: bool, skip_deps: bool,
    with_editable: bool = False, with_generate: bool = False,
) -> Path:
    check_target(target, force)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-stage-", dir=target.parent))
    backup: Path | None = None
    activated = False
    try:
        copy_runtime(root, staging)
        python = Path(sys.executable)
        if not skip_deps:
            python = install_dependencies(staging, target)
            for enabled, requirements in ((with_editable, "requirements-editable.txt"),
                                          (with_generate, "requirements-generate.txt")):
                if enabled:
                    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                                    "-r", str(staging / requirements)], check=True)

        marker = {
            "installer": "slidemuse",
            "brand": BRAND_NAME,
            "skill": skill_name,
            "client": client,
            "source": str(root),
            "editable_backend": with_editable,
            "generate_backend": with_generate,
        }
        (staging / ".skill-install.json").write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not skip_deps:
            validate_install(staging, python)

        if target.exists():
            backup = target.with_name(f".{target.name}-backup-{uuid.uuid4().hex}")
            replace_directory(target, backup)
        replace_directory(staging, target)
        activated = True

        final_python = venv_python(target / ".venv") if not skip_deps else python
        if not skip_deps:
            validate_install(target, final_python)
            if with_editable:
                subprocess.run([str(final_python), "-c",
                                "import fitz, PIL, openai, yaml, numpy, requests"], check=True)
                subprocess.run([str(final_python), str(target / "slidemuse.py"),
                                "rebuild", "capabilities", "--verify-source"], check=True)
            if with_generate:
                subprocess.run([str(final_python), "-c",
                                "import pptx, PIL, openai, filelock"], check=True)
                subprocess.run([str(final_python), str(target / "slidemuse.py"),
                                "generate", "capabilities", "--verify-source"], check=True)
    except BaseException:
        failed: Path | None = None
        if activated:
            failed = target.with_name(f".{target.name}-failed-{uuid.uuid4().hex}")
            replace_directory(target, failed)
        if backup is not None and backup.exists():
            replace_directory(backup, target)
        if failed is not None:
            shutil.rmtree(failed)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    if backup is not None:
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            print(f"install: warning: could not remove old backup {backup}: {exc}", file=sys.stderr)
    return final_python


IMAGE_BACKEND_TIP = {
    "optional": True,
    "sponsor": "FengYun AI (风云AI)",
    "url": "https://fyai.uk",
    "docs": ["docs/fyai-quickstart.md", "docs/fyai-quickstart.en.md"],
    "zh": [
        "提示（可选）：想要发挥 SlideMuse 的最大效果，需要 Codex 的生图模型。没有 Codex 订阅或海外网络？",
        "赞助方风云AI fyai.uk 生图仅 0.04 元/张（1K/2K/4K 同价）、GPT 低至 0.12 倍率、支持 Claude。",
        "去注册→充值→创建 API Key，交给 AI 工具即可配好生图，详见 docs/fyai-quickstart.md",
        "（也可用其他 OpenAI 兼容服务）。",
    ],
}


def emit(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        # Machine output must survive both UTF-8 agent pipes and GBK terminals.
        print(json.dumps(result, ensure_ascii=True))
        return

    if result.get("dry_run"):
        print(f"{BRAND_NAME} installer dry run")
    else:
        print(f"[OK] {BRAND_NAME} installed successfully")
    print(f"  Client: {result['client']}")
    print(f"  Skill:  {result['skill']}")
    invocation = result.get("invocation") or skill_invocation(str(result["client"]), str(result["skill"]))
    print(f"  Invoke: {invocation}")
    print(f"  Path:   {result['target']}")
    if result.get("python"):
        print(f"  Python: {result['python']}")
    for legacy in result.get("legacy_targets", []):
        print(
            f"  Note: legacy install found at {legacy}. "
            "You can remove it after confirming $slidemuse works."
        )
    tip = result.get("image_backend_tip")
    if tip:
        for line in tip["zh"]:
            print(f"  {line}")


def main() -> None:
    # Keep agent-facing text (including the bilingual image-backend tip) UTF-8
    # on legacy Windows consoles, matching the generation backend wrapper.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Install SlideMuse and its isolated Python runtime."
    )
    parser.add_argument(
        "--client",
        choices=("auto", *CLIENT_DIRS),
        default="auto",
        help="Target agent client. Defaults to automatic detection.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Register the skill without creating its isolated Python environment.",
    )
    parser.add_argument(
        "--with-editable", action="store_true",
        help="Also install dependencies for the complete image-to-editable backend.",
    )
    parser.add_argument(
        "--with-generate", action="store_true",
        help="Also install dependencies for the complete image-generation backend.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing unrecognized skill directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the selected client and target path without changing files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    args = parser.parse_args()
    if args.skip_deps and (args.with_editable or args.with_generate):
        parser.error("--with-editable and --with-generate require dependency installation; omit --skip-deps")

    root = Path(__file__).resolve().parent
    skill_name = read_skill_name(root)
    try:
        client = detect_client(args.home) if args.client == "auto" else args.client
    except RuntimeError as exc:
        parser.exit(2, f"install: error: {exc}\n")
    target = args.home / CLIENT_DIRS[client] / skill_name
    legacy = legacy_installs(args.home, client, skill_name)

    result: dict[str, object] = {
        "ok": True,
        "client": client,
        "skill": skill_name,
        "target": str(target),
        "invocation": skill_invocation(client, skill_name),
    }
    if legacy:
        result["legacy_targets"] = [str(path) for path in legacy]
        result["legacy_target"] = str(legacy[0])

    if args.dry_run:
        result["dry_run"] = True
        emit(result, args.json)
        return

    try:
        python = install_skill(root, target, client, skill_name, args.force, args.skip_deps,
                               args.with_editable, args.with_generate)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"install: error: {exc}\n")

    result["python"] = str(python)
    result["verified"] = not args.skip_deps
    result["image_backend_tip"] = IMAGE_BACKEND_TIP
    emit(result, args.json)


if __name__ == "__main__":
    main()
