"""Exercise provider selection through real CLIs with synthetic offline services."""
import base64
import io
import json
import os
import subprocess
import sys
import textwrap
import venv
from pathlib import Path

import generate_backend
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "vendor/codex-ppt/skills/codex-ppt/scripts/codex_ppt_runtime.py"
PROVIDER_A = "https://provider-a.invalid/v1"
PROVIDER_B = "https://provider-b.invalid/v1"
OFFICIAL = "https://api.openai.com/v1"


@pytest.fixture
def offline_api(tmp_path, monkeypatch):
    """Only urllib and the image SDK are fake; setup, doctor and image are real."""
    shared = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False, system_site_packages=True).create(shared / ".venv")
    hooks = tmp_path / "offline-provider"
    hooks.mkdir()
    captured = tmp_path / "provider-calls.jsonl"
    image = io.BytesIO()
    Image.new("RGB", (2560, 1440), "navy").save(image, format="PNG")
    encoded = base64.b64encode(image.getvalue()).decode("ascii")
    (hooks / "sitecustomize.py").write_text(textwrap.dedent("""
        import json
        import os
        import urllib.request

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass

        def offline_urlopen(request, *args, **kwargs):
            authorization = request.get_header("Authorization")
            assert authorization.startswith("Bearer fixture-"), "Only synthetic keys are allowed"
            with open(os.environ["SLIDEMUSE_TEST_CAPTURE"], "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"kind": "doctor", "url": request.full_url,
                                         "authorization": authorization}) + "\\n")
            return Response()

        urllib.request.urlopen = offline_urlopen
    """), encoding="utf-8")
    (hooks / "openai.py").write_text(textwrap.dedent("""
        import json
        import os
        from types import SimpleNamespace

        class OpenAI:
            def __init__(self, **kwargs):
                assert kwargs["api_key"].startswith("fixture-"), "Only synthetic keys are allowed"
                self.configuration = kwargs
                self.images = self

            def generate(self, **kwargs):
                with open(os.environ["SLIDEMUSE_TEST_CAPTURE"], "a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"kind": "image", **self.configuration,
                                             "model": kwargs["model"]}) + "\\n")
                return SimpleNamespace(data=[SimpleNamespace(b64_json=ENCODED)])
    """).replace("ENCODED", repr(encoded)), encoding="utf-8")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_PPT_IMAGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CODEX_PPT_HOME", str(shared))
    monkeypatch.setenv("SLIDEMUSE_TEST_CAPTURE", str(captured))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, (str(hooks), os.getenv("PYTHONPATH")))))
    real_run = subprocess.run

    def run(*arguments):
        return real_run([sys.executable, str(ROOT / "slidemuse.py"), "generate", *map(str, arguments)],
                        capture_output=True, text=True, encoding="utf-8", check=False)

    def records():
        return [json.loads(line) for line in captured.read_text(encoding="utf-8").splitlines()] if captured.exists() else []

    return shared, run, records, real_run


@pytest.mark.parametrize("inherited", [(), ("key",), ("url",), ("key", "url")])
def test_explicit_setup_uses_selected_provider_for_doctor_and_future_images(
    offline_api, tmp_path, monkeypatch, inherited,
):
    shared, run, records, real_run = offline_api
    if "key" in inherited:
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-host-A")
    if "url" in inherited:
        monkeypatch.setenv("OPENAI_BASE_URL", PROVIDER_A)
    monkeypatch.setenv("CODEX_PPT_IMAGE_MODEL", "gpt-image-2")

    def offline_bootstrap(command, **kwargs):
        if command[1:3] == [str(RUNTIME), "bootstrap"]:
            # The fixture already supplies a runtime and fake image SDK.
            return subprocess.CompletedProcess(command, 0)
        return real_run(command, **kwargs, capture_output=True, text=True, encoding="utf-8")

    monkeypatch.setattr(generate_backend.subprocess, "run", offline_bootstrap)
    assert generate_backend.fyai_setup([
        "--api-key", "fixture-selected-B", "--base-url", PROVIDER_B,
        "--model", "gpt-image-2.6",
    ]) == 0
    assert (shared / ".env").is_file()
    generated = run("image", "generate", "--prompt", "synthetic page", "--out", tmp_path / "page.png")
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert records() == [
        {"kind": "doctor", "url": PROVIDER_B + "/models", "authorization": "Bearer fixture-selected-B"},
        {"kind": "image", "api_key": "fixture-selected-B", "base_url": PROVIDER_B, "model": "gpt-image-2.6"},
    ]
    with Image.open(tmp_path / "page.png") as result:
        assert result.size == (2560, 1440)


@pytest.mark.parametrize("endpoint", [None, PROVIDER_A])
@pytest.mark.parametrize("model_only_file", [False, True])
def test_environment_only_provider_remains_supported(
    offline_api, tmp_path, monkeypatch, endpoint, model_only_file,
):
    _, run, records, _ = offline_api
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-environment-key")
    monkeypatch.setenv("CODEX_PPT_IMAGE_MODEL", "gpt-image-2.6")
    if endpoint:
        monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    if model_only_file:
        configured = run("runtime", "config", "--model", "gpt-image-2.6")
        assert configured.returncode == 0, configured.stderr
    diagnosed = run("runtime", "doctor", "--check-api")
    assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
    generated = run("image", "generate", "--prompt", "synthetic page", "--out", tmp_path / "page.png",
                    "--model", "gpt-image-2")
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert records() == [
        {"kind": "doctor", "url": (endpoint or OFFICIAL) + "/models",
         "authorization": "Bearer fixture-environment-key"},
        {"kind": "image", "api_key": "fixture-environment-key", "base_url": endpoint, "model": "gpt-image-2"},
    ]


@pytest.mark.parametrize("change", [("--base-url", PROVIDER_A), ("--clear-base-url",)])
def test_endpoint_change_requires_its_key_and_keeps_previous_configuration(offline_api, change):
    shared, run, records, _ = offline_api
    configured = run("runtime", "config", "--api-key", "fixture-selected-B", "--base-url", PROVIDER_B)
    assert configured.returncode == 0, configured.stderr
    original = (shared / ".env").read_bytes()
    refused = run("runtime", "config", *change)
    assert refused.returncode != 0
    assert "requires --api-key" in refused.stderr
    assert (shared / ".env").read_bytes() == original
    assert records() == []


def test_key_rotation_and_explicit_provider_switch_are_persisted(offline_api):
    _, run, records, _ = offline_api
    commands = [
        ("--api-key", "fixture-selected-B", "--base-url", PROVIDER_B),
        ("--base-url", PROVIDER_B + "/"),
        ("--api-key", "fixture-rotated-B"),
    ]
    for command in commands:
        configured = run("runtime", "config", *command)
        assert configured.returncode == 0, configured.stderr
    diagnosed = run("runtime", "doctor", "--check-api")
    assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
    switched = run("runtime", "config", "--base-url", PROVIDER_A, "--api-key", "fixture-selected-A")
    assert switched.returncode == 0, switched.stderr
    diagnosed = run("runtime", "doctor", "--check-api")
    assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
    assert records() == [
        {"kind": "doctor", "url": PROVIDER_B + "/models", "authorization": "Bearer fixture-rotated-B"},
        {"kind": "doctor", "url": PROVIDER_A + "/models", "authorization": "Bearer fixture-selected-A"},
    ]


def test_explicit_official_selection_clears_inherited_host_url(offline_api, tmp_path, monkeypatch):
    _, run, records, _ = offline_api
    configured = run("runtime", "config", "--api-key", "fixture-selected-B", "--base-url", PROVIDER_B)
    assert configured.returncode == 0, configured.stderr
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-host-A")
    monkeypatch.setenv("OPENAI_BASE_URL", PROVIDER_A)
    cleared = run("runtime", "config", "--clear-base-url", "--api-key", "fixture-official-key")
    assert cleared.returncode == 0, cleared.stderr
    diagnosed = run("runtime", "doctor", "--check-api")
    assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
    generated = run("image", "generate", "--prompt", "synthetic page", "--out", tmp_path / "page.png")
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert records() == [
        {"kind": "doctor", "url": OFFICIAL + "/models", "authorization": "Bearer fixture-official-key"},
        {"kind": "image", "api_key": "fixture-official-key", "base_url": None, "model": "gpt-image-2.6"},
    ]


@pytest.mark.parametrize("selection", [("--base-url", PROVIDER_B), ("--clear-base-url",)])
def test_saved_endpoint_without_key_never_borrows_host_credentials(offline_api, tmp_path, monkeypatch, selection):
    _, run, records, _ = offline_api
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-host-A")
    monkeypatch.setenv("OPENAI_BASE_URL", PROVIDER_A)
    configured = run("runtime", "config", *selection)
    assert configured.returncode == 0, configured.stderr
    diagnosed = run("runtime", "doctor", "--check-api")
    assert diagnosed.returncode != 0
    generated = run("image", "generate", "--prompt", "synthetic page", "--out", tmp_path / "page.png")
    assert generated.returncode != 0
    assert records() == []
    assert not (tmp_path / "page.png").exists()
