#!/usr/bin/env python3
"""Run the complete pinned editable-reconstruction backend inside SlideMuse."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
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
FEATURES = ["image-pdf-pptx-normalization", "speaker-notes", "offline-text-geometry", "targeted-offline-text-measurements",
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
    semantic = run / "slidemuse-page-content.json"
    if semantic.is_file():
        content = json.loads(semantic.read_text(encoding="utf-8"))
        index = int(page["page_index"]) - 1
        from content_density import WORKFLOW_POLICY, prompt_elements, visible_text
        slide = content["slides"][index]
        slide_content = {key: value for key, value in slide.items() if key != "source_refs"}
        slide_content["elements"] = prompt_elements(slide["elements"])
        prompt += ("\n\nApproved SlideMuse page content (reuse exact text, data and stable IDs; keep recorded sources in the Page Spec; "
                   "OCR is only a geometry hint, not authority to rewrite):\n"
                   + json.dumps(slide_content, ensure_ascii=False, indent=2))
        policy = content.get("content_policy")
        if "display" in slide_content or policy == WORKFLOW_POLICY:
            prompt += ("\nExpress semantic claims through the approved elements. Exact visible text:\n"
                       + json.dumps(visible_text(slide, policy=policy), ensure_ascii=False, indent=2))
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


def save_content_contract(job_dir: Path, semantic: dict) -> None:
    """Carry approved notes into the backend's actual assembly input and verifier."""
    from speaker_notes import canonical_notes

    snapshot = job_dir / "slidemuse-page-content.json"
    snapshot.write_text(json.dumps(semantic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notes = [{"page_index": index, "source_slide_id": slide["id"],
              "text": canonical_notes(slide.get("speaker_notes", ""))}
             for index, slide in enumerate(semantic["slides"], 1)]
    for entry in notes:
        entry["text_sha256"] = hashlib.sha256(entry["text"].encode("utf-8")).hexdigest()
    (job_dir / "notes_manifest.json").write_text(
        json.dumps({"source": snapshot.name, "notes": notes}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    deck_path = job_dir / "deck_manifest.json"
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    deck["slidemuse_content"] = snapshot.name
    deck["slidemuse_content_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    deck_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def measure_text(argv):
    """Use the pinned upstream ink metrics on human-identified text regions."""
    parser = argparse.ArgumentParser(description="Measure known text regions offline; no text recognition or editing.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--region", action="append", nargs=5, required=True, metavar=("ID", "X", "Y", "W", "H"))
    parser.add_argument("--slide-width-inches", type=float, default=13.333333)
    args = parser.parse_args(argv)
    if not math.isfinite(args.slide_width_inches) or args.slide_width_inches <= 0:
        parser.error("--slide-width-inches must be finite and positive")
    if importlib.util.find_spec("numpy") is None:
        parser.error("Install the optional reconstruction dependencies with --with-editable.")
    metrics = runpy.run_path(str(ROOT / VENDOR / SKILL / "cli/editppt/runtime/page_text_metrics.py"))
    try:
        gray = metrics["load_gray"](args.image)
    except OSError as error:
        parser.error(f"Cannot read source image: {error}")
    height, width = gray.shape
    results = []
    seen = set()
    pt_per_px = 72 * args.slide_width_inches / width
    for name, *bounds in args.region:
        if not name.strip() or name in seen:
            parser.error("Region IDs must be nonempty and unique.")
        seen.add(name)
        try:
            x, y, w, h = map(int, bounds)
        except ValueError:
            parser.error(f"{name}: region bounds must be integers.")
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
            parser.error(f"{name}: region must lie within the source image.")
        m = metrics["measure_crop"](gray[y:y+h, x:x+w])
        row = {"id": name, "region_px": [x, y, w, h], "status": "needs_review"}
        if not m["ok"]:
            row["reason"] = m["reason"]
        else:
            rx, ry, rw, rh = m["bbox"]
            glyph = m["glyph_height_px"]
            row.update(ink_box_px=[x+rx, y+ry, rw, rh], glyph_height_px=glyph,
                       line_count=m["line_count"], polarity=m["polarity"],
                       font_pt_if_cjk=round(glyph * pt_per_px / metrics["glyph_em_ratio"]("中"), 1),
                       font_pt_if_latin=round(glyph * pt_per_px / metrics["glyph_em_ratio"]("ABC"), 1))
        results.append(row)
    print(json.dumps({"source_pixels": [width, height], "slide_width_inches": args.slide_width_inches,
                      "scope": "Advisory geometry. Compare with the source; not OCR, exact font size, or visual approval.",
                      "regions": results}, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    offline = bool(argv and argv[0] == "--offline")
    if offline:
        argv.pop(0)
    if argv[:1] == ["measure-text"]:
        return measure_text(argv[1:])
    if argv[:1] == ["capabilities"]:
        parser = argparse.ArgumentParser(description="Inspect backend capabilities without reading credentials.")
        parser.add_argument("--verify-source", action="store_true")
        args = parser.parse_args(argv[1:])
        result = capabilities(verify=args.verify_source)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1 if result.get("source_integrity", {}).get("mismatches") else 0
    if argv[:1] == ["page-prompt"]:
        return page_prompt(argv[1:])
    semantic = None
    job_dir = None
    if argv[:1] == ["prepare"] and any(a.split("=", 1)[0] == "--page-spec" for a in argv):
        from validate_page_spec import load_page_spec
        parser = argparse.ArgumentParser(description="Prepare rebuilding with an approved Page Spec semantic contract")
        parser.add_argument("--page-spec", type=Path, required=True)
        parser.add_argument("--job-dir", type=Path, required=True)
        args, extra = parser.parse_known_args(argv[1:])
        source = args.page_spec.resolve()
        semantic, _ = load_page_spec(source, require_images=True, strict=True, content=True)
        argv = ["prepare", *extra, "--job-dir", str(args.job_dir),
                *[str((source.parent / s["image_file"]).resolve()) for s in semantic["slides"]]]
        job_dir = args.job_dir.resolve()
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
            result = subprocess.run([sys.executable, str(entry), *argv], env=env, check=False).returncode
            if result == 0 and semantic is not None:
                save_content_contract(job_dir, semantic)
            return result
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
