#!/usr/bin/env python3
"""Run the complete pinned editable-reconstruction backend inside SlideMuse."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import runpy
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path("vendor/image-to-editable")
SKILL = Path("skills/image-to-editable-ppt")
MODULES = {"PyMuPDF": "fitz", "Pillow": "PIL", "openai": "openai",
           "PyYAML": "yaml", "numpy": "numpy", "requests": "requests"}
FEATURES = ["image-pdf-pptx-normalization", "speaker-notes", "offline-text-geometry",
            "optional-paddle-ocr", "native-table-cell-styles-and-merges",
            "native-custom-paths-dashes-arrows", "background-strategy-and-clean-base-provenance",
            "transparent-and-chroma-asset-sheets", "whole-object-region-splitting",
            "latex-formula-assets", "image-import-and-provenance",
            "optional-oauth-or-api-images", "page-dispatch-leases-and-recovery",
            "manifest-rebuild-and-finalize", "package-content-and-notes-validation"]


def command_prefix(root=ROOT):
    parts = [sys.executable, str(root / "slidemuse.py"), "rebuild"]
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
    result = {"backend": "image-to-editable", "upstream": provenance["repository"],
              "commit": provenance["commit"], "license": provenance["license"],
              "features": FEATURES, "dependencies": dependencies,
              "dependencies_ready": all(dependencies.values()),
              "scope": "Availability only; network providers and external TeX tools are not exercised."}
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


def page_prompt(argv, root=ROOT):
    parser = argparse.ArgumentParser(description="Write a page prompt using SlideMuse's packaged backend.")
    parser.add_argument("run", type=Path)
    parser.add_argument("--page", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    skill = root / VENDOR / SKILL
    helpers = runpy.run_path(str(skill / "scripts/build-page-worker-prompt.py"))
    run = helpers["run_dir_from_target"](str(args.run))
    page = helpers["find_page"](helpers["load_jobs"](run), args.page)
    directory = helpers["page_dir_for"](run, page)
    output = helpers["resolve_prompt_out"](run, directory, args.out)
    prompt = helpers["build_prompt"](run, page, directory)
    prefix = command_prefix(root)
    prompt = re.sub(r"(?<![\w/])editppt(?=\s+(?:prepare|run|page|image|formula|doctor|config|setup)\b)",
                    lambda match: prefix, prompt)
    policy = (
        "SlideMuse integration: the parent skill's user intent, Page Spec text/data, protected evidence "
        "and actual host-tool rules remain authoritative. Read references/editable-backend.md in the "
        f"SlideMuse root ({root}) before using the upstream field references below. "
        "Use the host image tool for image edits when it is available; an API backend needs the user's "
        "chosen provider. Do not recreate protected source evidence through image generation. "
        "The backend preview is diagnostic: render the PPTX in Office before claiming visual acceptance.\n\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(policy + prompt.strip() + "\n", encoding="utf-8")
    print(json.dumps({"prompt_file": str(output), "page_id": page["page_id"],
                      "dispatch_command_template": f"{prefix} run dispatch <run> --page {page['page_id']} --agent-id <actual-worker-id> --prompt-file <prompt-file>"},
                     ensure_ascii=True, indent=2))
    return 0


def main(argv=None):
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
    if argv[:1] == ["page-prompt"]:
        return page_prompt(argv[1:])
    entry = ROOT / VENDOR / SKILL / "cli/editppt/cli.py"
    if not entry.is_file():
        print("SlideMuse: packaged editable backend is missing; reinstall the skill.", file=sys.stderr)
        return 2
    if argv[:1] == ["prepare"] and not any(a.split("=", 1)[0] == "--image-backend" for a in argv):
        argv.extend(["--image-backend", "builtin-imagegen"])
    # Optional local-only execution isolates all config and credential discovery,
    # including subprocesses launched by the backend.
    with tempfile.TemporaryDirectory(prefix="slidemuse-editable-") as isolated:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["IMAGE_TO_EDITABLE_PPT_CLI_PROG"] = command_prefix()
        if offline:
            if argv[:2] in (["image", "generate"], ["image", "edit"]) and "--dry-run" not in argv:
                print("SlideMuse: --offline supports image requests only with --dry-run.", file=sys.stderr)
                return 2
            env.update(EDITPPT_CONFIG_HOME=isolated, CODEX_AUTH_FILE=str(Path(isolated) / "no-auth.json"),
                       CODEX_PPT_HOME=isolated)
            for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "PADDLE_OCR_TOKEN"):
                env.pop(name, None)
        try:
            return subprocess.run([sys.executable, str(entry), *argv], env=env, check=False).returncode
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
