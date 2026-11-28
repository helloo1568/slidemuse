#!/usr/bin/env python3
"""Manage previews and gate publication for one WorkBuddy project."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from json_io import read_json

PREVIEW = Path("styles/compare-4-styles.png")
EVENTS = {"pre": "PreToolUse", "post": "PostToolUse"}
MATCHER = r"(^|.*__)present_files$"
FALLBACK_MESSAGE = "预览面板未确认打开。请点开四套风格对比 PNG 附件，一张图即可查看四套。"


def local_path(value: str, project: Path) -> Path | None:
    value = value.strip()
    if value.lower().startswith("file://"):
        uri = urlsplit(value)
        path = url2pathname(uri.path)
        value = f"//{uri.netloc}{path}" if uri.netloc not in ("", "localhost") else path
    elif "://" in value:
        return None
    path = Path(value)
    return (project / path).resolve()


def receipts(value):
    """Unwrap the JSON result inside WorkBuddy's MCP text content."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return
    if isinstance(value, list):
        for item in value:
            yield from receipts(item)
    elif isinstance(value, dict):
        if value.get("type") == "present_files_result":
            yield value
        else:
            for key in ("content", "text", "result", "output"):
                if key in value:
                    yield from receipts(value[key])


def files(value, project):
    items = value if isinstance(value, list) else []
    return {path for item in items if isinstance(item, str) and item.strip()
            if (path := local_path(item, project)) is not None}


def opened_preview(value: str, preview: Path, project: Path) -> bool:
    target = urlsplit(value)
    if target.scheme == "file":
        return local_path(value, project) == preview
    if target.scheme in ("http", "https") and target.hostname in ("localhost", "127.0.0.1", "::1"):
        parts = unquote(target.path).split("/")
        return len(parts) == 4 and parts[1] == "static-html" and bool(parts[2]) and parts[3] == preview.name
    return False


def preview_status(project: Path, result) -> dict:
    backup = (project / PREVIEW).resolve()
    preview = backup.with_suffix(".html")
    matches = list(receipts(result))
    receipt = matches[0] if len(matches) == 1 else {}
    attached = files(receipt.get("files"), project)
    opened = receipt.get("previewed")
    visible = (attached == {preview, backup} and isinstance(opened, list) and len(opened) == 1
               and isinstance(opened[0], str) and opened_preview(opened[0], preview, project))
    return {
        "status": "opened" if visible else "fallback",
        "fallback": str(backup) if backup.is_file() else None,
        "fallback_attached": backup in attached,
        "message": "WorkBuddy 已打开四套风格的对比预览。" if visible else FALLBACK_MESSAGE,
    }


def preview_contains_backup(preview: Path, backup: Path) -> bool:
    if not preview.is_file() or not backup.is_file():
        return False
    images = re.findall(rb'data:image/png;base64,([A-Za-z0-9+/=]+)"', preview.read_bytes())
    return len(images) == 1 and base64.b64decode(images[0], validate=True) == backup.read_bytes()


def config_paths(project: Path, job: Path, work: Path) -> tuple[Path, Path]:
    job, work = (project / job).resolve(), (project / work).resolve()
    if any(path == project or not path.is_relative_to(project) for path in (job, work)):
        raise ValueError("Job and review workspace must be inside the managed project")
    return job, work


def ready_deck(job: Path, work: Path) -> tuple[Path, str]:
    """Recheck current evidence before a finished artifact can be presented."""
    from audit_chart_geometry import charts as geometry_charts
    from evaluate_delivery import evaluate
    from render_deck import sha256
    from run_deck import build_key, cached_state, load_inputs, valid_artifact

    summary = read_json(work / "summary.json")
    recorded = read_json(work / "scorecard.json")
    if summary.get("status") != "complete" or recorded.get("status") != "pass":
        raise ValueError("当前交付流水线尚未验收通过")
    if Path(read_json(work / "owner.json")["config"]).resolve() != job:
        raise ValueError("当前审阅目录属于另一份任务")
    inputs = load_inputs(job, work)
    state = cached_state(work)
    build = state.get("build")
    if not valid_artifact(build, build_key(inputs), work):
        raise ValueError("当前材料与已审的 PPTX 不匹配")
    deck = Path(build["path"]).resolve()
    optional = inputs["optional"]
    visual = optional.get("visual_review", work / "visual-review.json")
    observations = inputs["observations"] or [work / "content-observations.json"]
    chart_checks = optional.get("chart_observations")
    if (chart_checks is None and inputs["config"]["mode"] == "image"
            and inputs["spec"].get("content_policy") == "1.1" and geometry_charts(inputs["spec"])):
        chart_checks = work / "chart-observations.json"
    if inputs["scene_path"] and any(not item.get("notes", "").strip() for item in read_json(visual)["slides"]):
        raise ValueError("可编辑版每页都需要记录实际看图结论")
    current = evaluate(inputs["spec_path"], work / "render-report.json", visual, observations,
                       inputs["scene_path"], chart_checks, optional.get("data_bindings"))
    if (current["status"] != "pass" or current != recorded or Path(current["deck"]).resolve() != deck
            or Path(summary["deck"]).resolve() != deck or sha256(deck) != current["deck_sha256"]):
        raise ValueError("正式交付与当前验收记录不一致，请重跑流水线")
    return deck, current["deck_sha256"]


def publish(job: Path, work: Path) -> dict:
    from render_deck import sha256
    from run_deck import locked_workspace

    with locked_workspace(job, work, managed=True):
        deck, expected_hash = ready_deck(job, work)
        output = work / "final" / "slidemuse.pptx"
        if output.parent.resolve() != output.parent:
            raise ValueError("正式输出目录不能重定向到其他位置")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(deck, temporary)
            if sha256(temporary) != expected_hash:
                raise ValueError("PPTX 在交付期间发生变化")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return {"status": "approved", "file": str(output), "sha256": expected_hash}


def review(job: Path, work: Path, record: Path | None = None) -> dict:
    from run_deck import locked_workspace, run

    if record is not None:
        from review_panel import import_record

        with locked_workspace(job, work, managed=True):
            return import_record(job, work, record.resolve())
    result = run(job, work, managed=True)
    result.pop("deck", None)
    return result


def deny(message: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                    "permissionDecisionReason": message}}


def hook(event, phase, project, job, work) -> dict:
    if event.get("hook_event_name") != EVENTS[phase]:
        raise ValueError("Unexpected WorkBuddy hook event")
    items = files(event["tool_input"]["files"], project)
    backup = (project / PREVIEW).resolve()
    preview = backup.with_suffix(".html")
    if phase == "post":
        if not items.intersection({backup, preview}):
            return {}
        status = preview_status(project, event.get("tool_response"))
        message = status["message"]
        if status["status"] == "fallback" and not status["fallback_attached"] and status["fallback"]:
            message += " 本次回执未挂上备用图，请只用以下路径调用 present_files：" + status["fallback"]
        return {"systemMessage": message, "hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                                     "additionalContext": message}}

    if preview in items and (items != {preview, backup} or not preview_contains_backup(preview, backup)):
        return deny("请同时提供同一次 style-overview 生成的对比 HTML 和备用 PNG。HTML 无法使用时可只发 PNG。")
    decks = {path for path in items if path.suffix.lower() == ".pptx"}
    if not decks:
        if backup in items:
            message = "如对比预览没有打开，请点开同一条消息里的 PNG 附件。" if preview in items else FALLBACK_MESSAGE
            return {"systemMessage": message}
        return {}
    final = work / "final" / "slidemuse.pptx"
    if decks != {final} or not final.is_file():
        return deny("SlideMuse：未验收的 PPTX 无法作为成品交付。请完成流水线审阅，再发布正式文件。")
    from render_deck import sha256
    from run_deck import locked_workspace

    with locked_workspace(job, work, managed=True):
        _, expected_hash = ready_deck(job, work)
    if sha256(final) != expected_hash:
        return deny("SlideMuse：正式文件已替换或损坏，请重新发布已验收的 PPTX。")
    return {}


def setup(project: Path, job: Path, work: Path) -> dict:
    """Register project-only hooks while preserving unrelated settings."""
    from run_deck import locked_workspace, write

    settings_path = project / ".workbuddy" / "settings.local.json"
    if not settings_path.resolve().is_relative_to(project):
        raise ValueError("WorkBuddy project settings must stay inside the project")
    settings = read_json(settings_path) if settings_path.is_file() else {}
    for phase, event_name in EVENTS.items():
        args = [Path(sys.executable).as_posix(), Path(__file__).resolve().as_posix(), "hook", phase,
                project.as_posix(), "--job", job.as_posix(), "--work", work.as_posix()]
        command = shlex.join(args)
        entries = settings.setdefault("hooks", {}).setdefault(event_name, [])
        entry = {"matcher": MATCHER, "hooks": [{"type": "command", "command": command, "timeout": 45}]}
        entries[:] = [item for item in entries if not (
            isinstance(item, dict) and item.get("matcher") == MATCHER and len(item.get("hooks", [])) == 1
            and "workbuddy_delivery.py" in item["hooks"][0].get("command", "")
        )]
        entries.append(entry)
    with locked_workspace(job, work, managed=True, initialize=True):
        write(settings_path, settings)
    return {"status": "configured", "settings": str(settings_path), "job": str(job), "review_workspace": str(work)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "review", "publish", "preview", "hook"):
        command = commands.add_parser(name)
        if name == "hook":
            command.add_argument("phase", choices=EVENTS)
        if name == "review":
            command.add_argument("--import-record", type=Path)
        command.add_argument("project", type=Path)
        command.add_argument("--job", type=Path, default=Path("job.json"))
        command.add_argument("--work", type=Path, default=Path(".slidemuse-review"))
    args = parser.parse_args()
    project = args.project.resolve()
    try:
        job, work = config_paths(project, args.job, args.work)
        if args.command == "setup":
            result = setup(project, job, work)
        elif args.command == "review":
            result = review(job, work, args.import_record)
        elif args.command == "publish":
            result = publish(job, work)
        elif args.command == "preview":
            result = preview_status(project, json.load(sys.stdin.buffer))
        else:
            result = hook(json.load(sys.stdin.buffer), args.phase, project, job, work)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError) as error:
        if args.command != "hook":
            parser.exit(1, f"SlideMuse WorkBuddy: {error}\n")
        detail = f"SlideMuse：交付检查未通过。{error}"
        result = deny(detail) if args.phase == "pre" else {"systemMessage": detail}
    print(json.dumps(result, ensure_ascii=True))
    if args.command == "review" and result["status"] != "complete":
        raise SystemExit(3 if result["status"] == "awaiting_review" else 1)


if __name__ == "__main__":
    main()
