"""Offline integration checks for setup and the interpreter used by API images."""
import base64
import io
import os
import subprocess
import sys
import venv
from pathlib import Path

import generate_backend
from PIL import Image


def python_in(environment):
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_core_install_uses_runtime_prepared_by_fyai_setup(tmp_path, monkeypatch):
    """No API is contacted; only the configured runtime has the test image SDK."""
    core = tmp_path / "core-venv"
    shared = tmp_path / "shared-runtime"
    venv.EnvBuilder(with_pip=False).create(core)
    core_python = python_in(core)
    shared_python = python_in(shared / ".venv")
    monkeypatch.setenv("CODEX_PPT_HOME", str(shared))
    for key in ("PYTHONPATH", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_PPT_IMAGE_MODEL"):
        monkeypatch.delenv(key, raising=False)
    real_run = subprocess.run
    result = real_run([str(core_python), "-c",
                       "import importlib.util; print(importlib.util.find_spec('openai'))"],
                      check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "None"
    image = io.BytesIO()
    Image.new("RGB", (2560, 1440), "navy").save(image, format="PNG")
    encoded = base64.b64encode(image.getvalue()).decode("ascii")
    calls = []
    runtime = generate_backend.ROOT / generate_backend.VENDOR / generate_backend.SKILL / "scripts/codex_ppt_runtime.py"

    def offline_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == [str(runtime), "bootstrap"]:
            # Bootstrap only needs a local test SDK; inherit existing core image
            # packages so this regression never installs or downloads anything.
            venv.EnvBuilder(with_pip=False, system_site_packages=True).create(shared / ".venv")
            site = real_run([str(shared_python), "-c",
                             "import sysconfig; print(sysconfig.get_path('purelib'))"],
                            check=True, capture_output=True, text=True).stdout.strip()
            (Path(site) / "openai.py").write_text(
                "from types import SimpleNamespace\n"
                "class OpenAI:\n"
                "    def __init__(self, **kwargs): self.images = self\n"
                f"    def generate(self, **kwargs): return SimpleNamespace(data=[SimpleNamespace(b64_json={encoded!r})])\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)
        if command[1:3] == [str(runtime), "doctor"]:
            # Check the real prepared interpreter, but omit the HTTP probe.
            return real_run([str(shared_python), "-c", "import openai, PIL, pptx"],
                            env=kwargs["env"], check=False)
        return real_run(command, **kwargs)

    monkeypatch.setattr(generate_backend.sys, "executable", str(core_python))
    monkeypatch.setattr(generate_backend.subprocess, "run", offline_run)
    assert generate_backend.fyai_setup([
        "--api-key", "local-test-key", "--base-url", "http://127.0.0.1:9/v1",
    ]) == 0
    assert (shared / ".env").is_file()
    output = tmp_path / "generated.png"
    assert generate_backend.run_backend([
        "image", "generate", "--prompt", "offline test", "--out", str(output),
    ]) == 0
    assert calls[-1][0] == str(shared_python.absolute())
    with Image.open(output) as generated:
        assert generated.size == (2560, 1440)
        assert generated.getpixel((0, 0)) == (0, 0, 128)


def test_image_without_shared_runtime_keeps_current_interpreter(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_PPT_HOME", str(tmp_path / "unconfigured"))
    calls = []
    def capture(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(generate_backend.subprocess, "run", capture)
    assert generate_backend.run_backend(["image", "generate", "--help"]) == 0
    assert calls[0][0] == sys.executable
