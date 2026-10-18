#!/usr/bin/env python3
"""Run the complete pinned codex-ppt image-generation backend inside SlideMuse."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path("vendor/codex-ppt")
SKILL = Path("skills/codex-ppt")
MODULES = {"python-pptx": "pptx", "Pillow": "PIL", "openai": "openai", "filelock": "filelock"}
FEATURES = ["outline-driven-slide-jobs", "per-slide-prompt-preparation",
            "slide-dispatch-and-result-state", "slide-blocker-recording",
            "image-deck-assembly", "speech-md-to-slide-notes", "slide-status-summary",
            "shared-runtime-venv-and-env-configuration", "optional-api-image-generation",
            "optional-chroma-key-matte-removal"]
SCRIPTS = {
    "status": "scripts/slide_job_status.py",
    "prepare": "scripts/prepare_slide_prompts.py",
    "dispatch": "scripts/record_slide_dispatch.py",
    "result": "scripts/record_slide_result.py",
    "blocker": "scripts/record_slide_blocker.py",
    "assemble": "scripts/assemble_ppt.py",
    "chroma": "scripts/remove_chroma_key.py",
    "runtime": "scripts/codex_ppt_runtime.py",
}


def prepare(argv, script, env):
    from generation_delivery import from_page_spec, prepare_spec, save_contract
    from json_io import read_json
    if "--help" in argv or "-h" in argv:
        print("SlideMuse additions: --page-spec <approved Page Spec> instead of --spec; current content rules are checked before writing jobs.")
        return subprocess.run([sys.executable, str(script), *argv], env=env, check=False).returncode
    parser = argparse.ArgumentParser(description="Prepare generation jobs from approved, role-aware content.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path)
    source.add_argument("--page-spec", type=Path)
    source.add_argument("--write-template", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args, extra = parser.parse_known_args(argv)
    if args.write_template:
        if args.write_template.exists():
            raise ValueError("Template already exists")
        from generation_delivery import write
        write(args.write_template, read_json(ROOT / "examples/generation-content.example.json"))
        return 0
    if args.out_dir is None:
        raise ValueError("--out-dir is required")
    spec = from_page_spec(args.page_spec.resolve()) if args.page_spec else read_json(args.spec)
    spec = prepare_spec(spec)
    source_path = (args.page_spec or args.spec).resolve()
    def resolve_images(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "path" and isinstance(item, str):
                    value[key] = str((source_path.parent / item).resolve())
                else:
                    resolve_images(item)
        elif isinstance(value, list):
            for item in value:
                resolve_images(item)
    for slide in spec["slides"]:
        resolve_images(slide.get("required_images", []))
    resolve_images(spec.get("approved_style_reference", {}))
    # Original relative paths in Markdown image references must keep their base.
    # Stage beside the source, so the vendored helper resolves every path as before.
    fd, temporary = tempfile.mkstemp(prefix=".slidemuse-generation-", suffix=".json", dir=source_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(spec, stream, ensure_ascii=False)
        result = subprocess.run([sys.executable, str(script), "--spec", temporary,
                                 "--out-dir", str(args.out_dir), *extra], env=env, check=False).returncode
    finally:
        Path(temporary).unlink(missing_ok=True)
    if result == 0:
        save_contract(args.out_dir.resolve(), spec)
        if any("speaker_notes" in s for s in spec["slides"]):
            notes = "\n\n".join(f"## Slide {s['number']}: {s['title']}\n{s.get('speaker_notes', '')}"
                                 for s in spec["slides"])
            (args.out_dir / "speech.md").write_text(notes + "\n", encoding="utf-8")
    return result


def command_prefix(root=ROOT):
    parts = [sys.executable, str(root / "slidemuse.py"), "generate"]
    if os.name == "nt":
        return "& " + " ".join("'" + part.replace("'", "''") + "'" for part in parts)
    return shlex.join(parts)


def content_sha256(path):
    """Hash text as stored in Git, so verification does not depend on checkout line endings."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def capabilities(root=ROOT, verify=False):
    vendor = root / VENDOR
    provenance = json.loads((vendor / "upstream.json").read_text(encoding="utf-8"))
    dependencies = {name: importlib.util.find_spec(module) is not None
                    for name, module in MODULES.items()}
    result = {"backend": "codex-ppt", "upstream": provenance["repository"],
              "commit": provenance["commit"], "license": provenance["license"],
              "commands": sorted(SCRIPTS), "features": FEATURES, "dependencies": dependencies,
              "dependencies_ready": all(dependencies.values()),
              "scope": "Availability only; the host agent generates slide images and no network provider is exercised."}
    if verify:
        mismatches = []
        for name, expected in provenance["files"].items():
            expected = provenance.get("patches", {}).get(name, {}).get("sha256", expected)
            path = (vendor / name).resolve()
            if (not path.is_relative_to(vendor.resolve()) or not path.is_file()
                    or content_sha256(path) != expected):
                mismatches.append(name)
        result["source_integrity"] = {"checked": len(provenance["files"]), "mismatches": mismatches}
    return result


def run_backend(argv, root=ROOT, offline=False):
    name = argv[0] if argv else ""
    if name in ("", "--help", "-h"):
        print("SlideMuse generate: " + ", ".join([*sorted(SCRIPTS), "review", "capabilities"]))
        print("prepare --spec <deck.json> OR --page-spec <approved.json> --out-dir <deck>; review <deck> [--init]")
        return 0
    if name == "review":
        from generation_delivery import REVIEW, review
        parser = argparse.ArgumentParser(description="Create or verify observations of actual generated pages; never auto-approve.")
        parser.add_argument("deck", type=Path)
        parser.add_argument("--record", type=Path)
        parser.add_argument("--init", action="store_true")
        args = parser.parse_args(argv[1:])
        record = args.record or args.deck / REVIEW
        result = review(args.deck.resolve(), record.resolve(), args.init)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result["status"] in ("pass", "awaiting_review") else 1
    if name not in SCRIPTS:
        print(f"SlideMuse: choose one of: {', '.join(sorted(SCRIPTS))}", file=sys.stderr)
        return 2
    if offline and name == "runtime":
        # The shared runtime creates a venv, writes user-level credentials and can probe an API.
        print("SlideMuse: --offline does not support the networked runtime commands.", file=sys.stderr)
        return 2
    script = root / VENDOR / SKILL / SCRIPTS[name]
    if not script.is_file():
        print("SlideMuse: packaged image-generation backend is missing; reinstall the skill.", file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if offline:
        # Isolate every config and credential path the backend could discover.
        env["CODEX_PPT_HOME"] = os.path.join(tempfile.gettempdir(), "slidemuse-offline-codex-ppt")
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_PPT_IMAGE_MODEL"):
            env.pop(key, None)
    try:
        if name == "prepare":
            return prepare(argv[1:], script, env)
        if name == "assemble":
            from generation_delivery import assemble
            return assemble(argv[1:], script)
        return subprocess.run([sys.executable, str(script), *argv[1:]], env=env, check=False).returncode
    except KeyboardInterrupt:
        return 130


def main(argv=None):
    # Keep wrapper diagnostics consistent with its UTF-8 backend, including
    # rejected commands containing Chinese paths on legacy Windows locales.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    offline = bool(argv and argv[0] == "--offline")
    if offline:
        argv.pop(0)
    if argv[:1] == ["capabilities"]:
        parser = argparse.ArgumentParser(description="Inspect backend capabilities without reading credentials.")
        parser.add_argument("--verify-source", action="store_true")
        args = parser.parse_args(argv[1:])
        result = capabilities(verify=args.verify_source)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1 if result.get("source_integrity", {}).get("mismatches") else 0
    try:
        return run_backend(argv, offline=offline)
    except (ValueError, TypeError, OSError, KeyError) as error:
        print(f"SlideMuse generation: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
