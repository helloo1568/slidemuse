#!/usr/bin/env python3
"""Validate, build, resume selected-page rendering, and collect real delivery review tasks."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from audit_editability import audit as audit_objects
from audit_page_content import template as content_template
from build_editable_ppt import build_deck as build_editable
from build_image_ppt import DEFAULT_EXTENSIONS
from build_image_ppt import build_deck as build_image
from evaluate_delivery import evaluate, review_template, verified_visual_review
from render_deck import build_review, reference_files, render_selected, sha256
from scene import load_scene, walk
from speaker_notes import check_scene_notes
from update_data_bindings import inspect as inspect_bindings
from validate_page_spec import _relative_path, load_page_spec

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"version", "page_spec", "mode", "scene", "backend", "width", "visual_review",
          "observations", "chart_observations", "data_bindings"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pipeline-", dir=path.parent)
    os.close(fd)
    try:
        Path(temporary).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def runtime_key():
    paths = [*sorted((ROOT / "scripts").glob("*.py")), *sorted((ROOT / "scripts").glob("*.ps1")),
             *sorted((ROOT / "references").glob("*.schema.json"))]
    return digest({str(p.relative_to(ROOT)): sha256(p) for p in paths})


def load_inputs(config_path, work):
    config = read(config_path)
    if (not isinstance(config, dict) or set(config) - FIELDS or config.get("version") != "1.0"
            or config.get("mode") not in ("image", "editable")):
        raise ValueError("Job needs version 1.0, mode image/editable and supported fields")
    if config.get("backend", "auto") not in ("auto", "powerpoint", "libreoffice"):
        raise ValueError("Unknown render backend")
    width = config.get("width", 1600)
    if isinstance(width, bool) or not isinstance(width, int) or not 320 <= width <= 16384:
        raise ValueError("Render width must be an integer between 320 and 16384")
    if "observations" in config and (not isinstance(config["observations"], list) or not config["observations"]):
        raise ValueError("Observations must be a nonempty path list")
    resolve = lambda value: _relative_path(config_path.parent, value)
    spec_path = resolve(config["page_spec"])
    scene_path = resolve(config["scene"]) if config.get("scene") else None
    if config["mode"] == "editable" and scene_path is None:
        raise ValueError("Editable mode needs a Scene")
    if config["mode"] == "image" and scene_path is not None:
        raise ValueError("Image mode must not declare an editable Scene")
    spec, _ = load_page_spec(spec_path, strict=True, require_images=config["mode"] == "image")
    references = reference_files(spec_path, len(spec["slides"]))
    scene = load_scene(scene_path)[0] if scene_path else None
    if scene and (errors := check_scene_notes(spec, scene)):
        raise ValueError("; ".join(errors))
    assets = set(references)
    assets.update(resolve_path for name in spec["style"].get("tokens", {}).get("reference_images", [])
                  for resolve_path in [_relative_path(spec_path.parent, name)])
    per_slide_assets = {}
    for slide in scene["slides"] if scene else []:
        names = [e["path"] for e in walk(slide["elements"]) if e["type"] == "image"]
        if slide.get("source_image"):
            names.append(slide["source_image"])
        paths = [_relative_path(scene_path.parent, name) for name in names]
        assets.update(paths)
        per_slide_assets[slide["id"]] = {str(p): sha256(p) for p in paths}
    inputs = {config_path, spec_path, *assets, *([scene_path] if scene_path else [])}
    if any(p.is_relative_to(work) for p in inputs):
        raise ValueError("Pipeline workspace must not contain job inputs or source assets")
    optional = {name: resolve(config[name]) for name in ("visual_review", "chart_observations", "data_bindings") if config.get(name)}
    observations = [resolve(name) for name in config.get("observations", [])]
    return {"config": config, "spec_path": spec_path, "scene_path": scene_path, "spec": spec, "scene": scene,
            "references": references, "assets": {str(p): sha256(p) for p in assets}, "slide_assets": per_slide_assets,
            "optional": optional, "observations": observations, "runtime": runtime_key()}


def visible(slide):
    return {k: v for k, v in slide.items() if k not in ("speaker_notes", "notes", "generation_prompt", "prompt_record")}


def keys(inputs, backend):
    spec, config = inputs["spec"], inputs["config"]
    result = {}
    for index, slide in enumerate(spec["slides"]):
        source = visible(inputs["scene"]["slides"][index]) if inputs["scene"] else sha256(inputs["references"][index])
        result[slide["id"]] = digest({"mode": config["mode"], "index": index, "canvas": spec["canvas"],
                                      "scene_canvas": inputs["scene"]["canvas"] if inputs["scene"] else None,
                                      "style": spec["style"], "spec": visible(slide), "source": source,
                                      "assets": inputs["slide_assets"].get(slide["id"], {}),
                                      "reference": sha256(inputs["references"][index]),
                                      "count": len(spec["slides"]) if slide.get("depends_on_slide_count") else None,
                                      "backend": backend, "requested_backend": config.get("backend", "auto"),
                                      "width": config.get("width", 1600), "runtime": inputs["runtime"],
                                      "data_bindings": sha256(inputs["optional"]["data_bindings"]) if "data_bindings" in inputs["optional"] else None})
    return result


def valid_artifact(record, key, work):
    if not isinstance(record, dict) or record.get("key") != key or not isinstance(record.get("path"), str):
        return False
    path = Path(record["path"]).resolve()
    return path.is_relative_to(work) and path.is_file() and record.get("sha256") == sha256(path)


def artifact(path, key):
    return {"key": key, "path": str(path), "sha256": sha256(path)}


def cached_state(work):
    path = work / "state.json"
    if not path.exists():
        return {}
    state = read(path)
    if not isinstance(state, dict) or state.get("version") != "1.0":
        raise ValueError("Invalid pipeline state; preserve it and use a new workspace")
    seal = state.pop("state_sha256", None)
    if seal != digest(state):
        raise ValueError("Pipeline state changed or is incomplete; preserve it and use a new workspace")
    return state


def save_state(work, state):
    state["version"] = "1.0"
    value = {k: v for k, v in state.items() if k != "state_sha256"}
    write(work / "state.json", {**value, "state_sha256": digest(value)})


@contextmanager
def locked_workspace(config_path, work):
    owner = work / "owner.json"
    if work.exists() and any(work.iterdir()) and not owner.is_file():
        raise ValueError("Use a new or previously owned pipeline workspace")
    work.mkdir(parents=True, exist_ok=True)
    with (work / ".run.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if owner.exists():
                if read(owner) != {"version": "1.0", "config": str(config_path)}:
                    raise ValueError("Workspace belongs to a different job")
            else:
                write(owner, {"version": "1.0", "config": str(config_path)})
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def archive_review(work, path):
    if path.is_file():
        target = work / "review-history" / (path.stem + "-" + sha256(path) + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(path, target)


def update_templates(inputs, work, report, page_keys, previous):
    spec = inputs["spec"]
    review_path = work / "visual-review.json"
    current = review_template(spec, report)
    if review_path.exists():
        try:
            # Keep current, genuinely recorded judgments. No automatic pending->pass.
            verified_visual_review(review_path, spec, report)
        except (ValueError, KeyError, TypeError):
            old = None
            if previous.get("spec") and previous.get("render"):
                try:
                    old = verified_visual_review(review_path, previous["spec"], previous["render"])
                except (ValueError, KeyError, TypeError):
                    pass
            if old:
                by_id = {s["id"]: s for s in old["slides"]}
                for slide in current["slides"]:
                    if previous.get("review_keys", {}).get(slide["id"]) == page_keys[slide["id"]]:
                        before = by_id.get(slide["id"])
                        if before and before["rendered_sha256"] == slide["rendered_sha256"] and before["reference_sha256"] == slide["reference_sha256"]:
                            for name in ("status", "notes", "data_reviews", "data_visual_inventory"):
                                slide[name] = copy.deepcopy(before[name])
            archive_review(work, review_path)
            write(review_path, current)
    else:
        write(review_path, current)
    observation_path = work / "content-observations.json"
    observation = content_template(inputs["spec_path"], spec["slides"])
    if observation_path.exists():
        old = read(observation_path)
        entries = old.get("slides", []) if isinstance(old, dict) and old.get("version") == "1.0" else []
        by_id = {s.get("id"): s for s in entries if isinstance(s, dict)}
        if len(by_id) != len(entries):
            by_id = {}  # Duplicate/malformed transcriptions cannot be silently accepted.
        for item in observation["slides"]:
            before = by_id.get(item["id"])
            if (before and previous.get("review_keys", {}).get(item["id"]) == page_keys[item["id"]]
                    and before.get("image_sha256") == item["image_sha256"]
                    and before.get("status") in ("complete", "partial") and isinstance(before.get("observed_text"), str)):
                item.update(status=before["status"], observed_text=before["observed_text"])
        if observation != old:
            archive_review(work, observation_path)
            write(observation_path, observation)
    else:
        write(observation_path, observation)


def summary(work, result):
    write(work / "summary.json", result)
    lines = ["# SlideMuse pipeline", "", "Status: " + result["status"], "", "| Stage | Result |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in result.get("stages", {}).items()]
    lines += ["", "## Next actions", ""]
    lines += [f"- {item['kind']}: {item['message']}" for item in result.get("actions", [])] or ["- Current declared checks passed."]
    lines += ["", "Review records establish recorded judgments, not reviewer identity or source truth.", ""]
    (work / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def run(config_path, work, stop_after=None, refresh_render=False):
    config_path, work = config_path.resolve(), work.resolve()
    inputs = load_inputs(config_path, work)
    with locked_workspace(config_path, work):
        state = cached_state(work)
        previous = copy.deepcopy(state)
        result = {"status": "running", "stages": {"validate": "pass"}, "actions": [], "rendered_slides": [], "reused_slides": []}
        current_stage = "validate"
        try:
            archive_review(work, work / "scorecard.json")
            (work / "scorecard.json").unlink(missing_ok=True)
            config = inputs["config"]
            if "data_bindings" in inputs["optional"]:
                check = inspect_bindings(inputs["optional"]["data_bindings"], inputs["spec_path"], inputs["scene_path"])
                if check["status"] != "pass":
                    raise ValueError("Declared data dependencies conflict: " + json.dumps(check["errors"], ensure_ascii=True))
            if stop_after == "validate":
                result["status"] = "stopped"
                save_state(work, state)
                return summary(work, result)
            build_key = digest({"spec": sha256(inputs["spec_path"]), "scene": sha256(inputs["scene_path"]) if inputs["scene_path"] else None,
                                "assets": inputs["assets"], "mode": config["mode"], "runtime": inputs["runtime"]})
            current_stage = "build"
            if valid_artifact(state.get("build"), build_key, work):
                deck = Path(state["build"]["path"])
                result["stages"]["build"] = "reused"
            else:
                deck = work / "cache" / ("deck-" + build_key + ".pptx")
                if config["mode"] == "editable":
                    build_editable(inputs["scene_path"], deck, inputs["spec_path"])
                else:
                    build_image(argparse.Namespace(input_dir=inputs["spec_path"], output=deck, width=None, height=None,
                                                    fit="cover", background="FFFFFF", title="", max_width=0, jpeg_quality=0,
                                                    extensions=DEFAULT_EXTENSIONS))
                state["build"] = artifact(deck, build_key)
                result["stages"]["build"] = "built"
                save_state(work, state)
            result["deck"] = str(deck)
            if inputs["scene_path"]:
                objects = audit_objects(deck, inputs["scene_path"])
                write(work / "object-audit.json", objects)
                if objects["errors"]:
                    raise ValueError("Native object checks failed: " + "; ".join(objects["errors"]))
            if stop_after == "build":
                result["status"] = "stopped"
                return summary(work, result)
            current_stage = "render"
            backend = state.get("backend", config.get("backend", "auto"))
            page_keys = keys(inputs, backend)
            pages = state.get("pages", {})
            ids = [s["id"] for s in inputs["spec"]["slides"]]
            wanted = [n for n, sid in enumerate(ids, 1) if refresh_render or not valid_artifact(pages.get(sid), page_keys[sid], work)]
            if wanted:
                with tempfile.TemporaryDirectory(prefix=".render-", dir=work) as temporary:
                    rendered = Path(temporary)
                    actual_backend = render_selected(deck, rendered, config.get("width", 1600), config.get("backend", "auto"), wanted)
                    if actual_backend != backend:
                        # A fallback backend cannot be mixed with old cached pages.
                        missing = [n for n in range(1, len(ids) + 1) if n not in wanted]
                        if missing:
                            with tempfile.TemporaryDirectory(prefix=".render-fallback-", dir=work) as extra:
                                render_selected(deck, Path(extra), config.get("width", 1600), actual_backend, missing)
                                for n in missing:
                                    shutil.copyfile(Path(extra) / f"{n:03d}.png", rendered / f"{n:03d}.png")
                            wanted += missing
                        backend = actual_backend
                        page_keys = keys(inputs, backend)
                    for n in wanted:
                        sid = ids[n - 1]
                        cached = work / "cache" / ("page-" + page_keys[sid] + ".png")
                        shutil.copyfile(rendered / f"{n:03d}.png", cached)
                        pages[sid] = artifact(cached, page_keys[sid])
                state.update(pages={sid: pages[sid] for sid in ids}, backend=backend)
                save_state(work, state)
            result["rendered_slides"] = [ids[n - 1] for n in sorted(wanted)]
            result["reused_slides"] = [sid for sid in ids if sid not in result["rendered_slides"]]
            result["stages"]["render"] = "rendered" if wanted else "reused"
            images = [Path(pages[sid]["path"]) for sid in ids]
            report = {"deck": str(deck), "deck_sha256": sha256(deck), "backend": backend,
                      "page_spec_sha256": sha256(inputs["spec_path"]),
                      "slides": build_review(images, work, inputs["references"]), "review_sheet": str(work / "review.png")}
            update_templates(inputs, work, report, page_keys, previous)
            write(work / "render-report.json", report)
            result["review_sheet"] = str(work / "review.png")
            state.update(spec=inputs["spec"], render=report, review_keys=page_keys)
            save_state(work, state)
            if stop_after == "render":
                result["status"] = "stopped"
                return summary(work, result)
            current_stage = "evaluate"
            review_path = inputs["optional"].get("visual_review", work / "visual-review.json")
            observations = inputs["observations"] or [work / "content-observations.json"]
            missing = [p for p in [review_path, *observations, *inputs["optional"].values()] if not p.is_file()]
            if missing:
                result["actions"] = [{"kind": "missing_evidence", "message": str(p)} for p in missing]
                result["status"] = "awaiting_review"
                return summary(work, result)
            scorecard = evaluate(inputs["spec_path"], work / "render-report.json", review_path, observations,
                                 inputs["scene_path"], inputs["optional"].get("chart_observations"), inputs["optional"].get("data_bindings"))
            write(work / "scorecard.json", scorecard)
            for sid in scorecard["visual"]["pending"] + scorecard["visual"]["failed"]:
                result["actions"].append({"kind": "visual_review", "message": sid + ": inspect current rendered page in " + str(review_path)})
            for review in scorecard["data"]["pending"] + scorecard["data"]["failed"]:
                result["actions"].append({"kind": "data_review", "message": review["slide_id"] + "/" + review["element_id"] + ": check values, labels and geometry/alignment"})
            for sid in scorecard["data_visual_inventory"]["pending"] + scorecard["data_visual_inventory"]["failed"]:
                result["actions"].append({"kind": "visual_inventory", "message": sid + ": record actual data visuals"})
            if scorecard["content"]["issues"] or scorecard["content"]["incomplete"]:
                result["actions"].append({"kind": "content_observations", "message": "Complete or repair actual visual transcriptions: " + ", ".join(str(p) for p in observations)})
            if scorecard["chart_geometry"].get("status") in ("fail", "incomplete"):
                result["actions"].append({"kind": "chart_geometry", "message": "Measure current chart endpoints and resolve geometry findings"})
            result["stages"]["evaluate"] = scorecard["status"]
            result["status"] = "complete" if scorecard["status"] == "pass" else "failed" if scorecard["status"] == "fail" else "awaiting_review"
            if result["status"] != "complete" and not result["actions"]:
                result["actions"].append({"kind": "delivery_checks", "message": "Resolve current scorecard.json findings before delivery"})
            result["deck"] = str(deck)
            return summary(work, result)
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
            result.update(status="failed", failed_stage=current_stage)
            result["stages"][current_stage] = "failed"
            result["actions"].append({"kind": "repair", "message": str(error)})
            summary(work, result)
            return result


def status(config_path, work):
    """Read-only input/cache diagnostics; does not compile or fabricate review."""
    inputs = load_inputs(config_path.resolve(), work.resolve())
    state = cached_state(work.resolve())
    backend = state.get("backend", inputs["config"].get("backend", "auto"))
    wanted_keys = keys(inputs, backend)
    return {"status": "ready", "slides": len(wanted_keys),
            "reusable_render_slides": [sid for sid, key in wanted_keys.items() if valid_artifact(state.get("pages", {}).get(sid), key, work.resolve())],
            "last_summary": read(work / "summary.json") if (work / "summary.json").is_file() else None,
            "note": "Last summary is historical; run always re-evaluates current review and dependencies."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--status", action="store_true", help="Read-only diagnostics")
    parser.add_argument("--stop-after", choices=("validate", "build", "render"))
    parser.add_argument("--refresh-render", action="store_true", help="Render all pages after font/renderer environment changes")
    args = parser.parse_args()
    try:
        if args.status and (args.stop_after or args.refresh_render):
            raise ValueError("--status cannot execute stages or refresh rendering")
        result = status(args.job, args.workspace) if args.status else run(args.job, args.workspace, args.stop_after, args.refresh_render)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        result = {"status": "blocked", "actions": [{"kind": "input_or_workspace", "message": str(error)}]}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if result["status"] in ("failed", "blocked"):
        raise SystemExit(1)
    if result["status"] == "awaiting_review":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
