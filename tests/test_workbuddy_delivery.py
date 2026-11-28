import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from workbuddy_delivery import PREVIEW, hook, preview_status, setup


def event(phase, inputs, output=None):
    return {"hook_event_name": phase, "tool_input": {"files": [str(item) for item in inputs]},
            "tool_response": output}


@pytest.mark.parametrize("opened, expected", [
    ([], "fallback"),
    (["http://127.0.0.1:5432/static-html/id/another.html"], "fallback"),
    (["https://example.net/static-html/id/compare-4-styles.html"], "fallback"),
    (["http://127.0.0.1:5432/static-html/id/compare-4-styles.html"], "opened"),
])
def test_preview_uses_only_its_actual_workbuddy_receipt(tmp_path, opened, expected):
    png = tmp_path / PREVIEW
    png.parent.mkdir()
    png.write_bytes(b"backup")
    html = png.with_suffix(".html")
    payload = {"type": "present_files_result", "files": [str(html), str(png)], "previewed": opened}
    response = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    status = preview_status(tmp_path, response)
    assert status["status"] == expected
    assert status["fallback"] == str(png)
    assert status["fallback_attached"]
    result = hook(event("PostToolUse", [html, png], response), "post", tmp_path, tmp_path / "job.json", tmp_path / "review")
    assert result["systemMessage"] == status["message"]


def test_pre_hook_enforces_backup_and_blocks_direct_drafts(tmp_path):
    png = tmp_path / PREVIEW
    png.parent.mkdir()
    png.write_bytes(b"backup")
    html = png.with_suffix(".html")
    html.write_text('<img src="data:image/png;base64,YmFja3Vw">', encoding="utf-8")
    args = ("pre", tmp_path, tmp_path / "job.json", tmp_path / "review")
    assert "PNG" in hook(event("PreToolUse", [html, png]), *args)["systemMessage"]
    assert "未确认打开" in hook(event("PreToolUse", [png]), *args)["systemMessage"]
    assert hook(event("PreToolUse", [html]), *args)["hookSpecificOutput"]["permissionDecision"] == "deny"
    png.write_bytes(b"different")
    assert hook(event("PreToolUse", [html, png]), *args)["hookSpecificOutput"]["permissionDecision"] == "deny"
    pptx = tmp_path / "draft.pptx"
    for locator in (pptx, pptx.as_uri()):
        result = hook(event("PreToolUse", [locator]), *args)
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_setup_is_local_idempotent_and_keeps_other_hooks(tmp_path):
    settings = tmp_path / ".workbuddy" / "settings.local.json"
    settings.parent.mkdir()
    original = {"matcher": "Read", "hooks": []}
    settings.write_text(json.dumps({"model": "existing", "hooks": {"PreToolUse": [original]}}), encoding="utf-8")
    setup(tmp_path, tmp_path / "job.json", tmp_path / "review")
    setup(tmp_path, tmp_path / "job.json", tmp_path / "second review")
    config = json.loads(settings.read_text(encoding="utf-8"))
    assert config["model"] == "existing"
    assert config["hooks"]["PreToolUse"][0] == original
    assert len(config["hooks"]["PreToolUse"]) == 2
    assert "second review" in config["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
    assert len(config["hooks"]["PostToolUse"]) == 1


def test_workbuddy_hook_reads_utf8_transport_with_a_legacy_stdio_encoding(tmp_path):
    project = tmp_path / "开源"
    png = project / PREVIEW
    png.parent.mkdir(parents=True)
    png.write_bytes(b"backup")
    request = event("PostToolUse", [png], {
        "type": "present_files_result", "files": [str(png)], "previewed": [], "explanation": "原案例",
    })
    script = Path(__file__).resolve().parents[1] / "scripts" / "workbuddy_delivery.py"
    result = subprocess.run([sys.executable, str(script), "hook", "post", str(project)],
                            input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                            capture_output=True, check=True, env={**os.environ, "PYTHONIOENCODING": "gbk"})
    output = json.loads(result.stdout)
    assert "预览面板未确认打开" in output["systemMessage"]
    assert "未挂上" not in output["systemMessage"]
