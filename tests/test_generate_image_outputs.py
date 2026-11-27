"""Offline API boundary checks; providers and returned images are synthetic fixtures."""
import base64
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "vendor/codex-ppt/skills/codex-ppt/scripts"


def image_bytes(color="navy"):
    stream = io.BytesIO()
    Image.new("RGB", (160, 90), color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("slidemuse_test_image_outputs", SCRIPTS / "image_gen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_load_runtime_env", lambda: None)
    monkeypatch.setattr(module, "_ensure_api_key", lambda *_: None)
    monkeypatch.delenv("CODEX_PPT_IMAGE_MODEL", raising=False)
    encoded = base64.b64encode(image_bytes()).decode()
    provider = SimpleNamespace(generate=Mock(return_value=[encoded]), edit=Mock(return_value=[encoded]),
                               generate_batch=AsyncMock(return_value=[encoded]))
    factory = Mock(return_value=provider)
    monkeypatch.setattr(module, "create_image_provider", factory)

    def run(*arguments):
        monkeypatch.setattr(sys, "argv", ["image_gen.py", *map(str, arguments)])
        return module.main()

    return SimpleNamespace(run=run, provider=provider, factory=factory, encoded=encoded)


def command(tmp_path, kind, out, *extra):
    if kind == "generate-batch":
        jobs = tmp_path / "jobs.jsonl"
        jobs.write_text(json.dumps({"prompt": "Synthetic slide", "out": out.name}) + "\n")
        return [kind, "--input", jobs, "--out-dir", out.parent, *extra]
    args = [kind, "--prompt", "Synthetic slide", "--out", out, *extra]
    if kind == "edit":
        source = tmp_path / "source.png"
        source.write_bytes(image_bytes("green"))
        args.extend(["--image", source])
    return args


@pytest.mark.parametrize("kind", ["generate", "edit", "generate-batch"])
@pytest.mark.parametrize("conflict", ["original", "downscaled"])
def test_known_output_conflicts_do_not_call_provider(cli, tmp_path, kind, conflict):
    out = tmp_path / "output.png"
    existing = out if conflict == "original" else tmp_path / "output-web.png"
    existing.write_bytes(b"previous output")
    with pytest.raises(SystemExit) as error:
        cli.run(*command(tmp_path, kind, out, "--downscale-max-dim", 80))
    assert error.value.code == 1
    cli.factory.assert_not_called()
    assert existing.read_bytes() == b"previous output"


@pytest.mark.parametrize("kind", ["generate", "edit", "generate-batch"])
@pytest.mark.parametrize("response", [[], [None], ["not-base64"], ["bm90LWFuLWltYWdl"], ["extra", "result"]])
def test_invalid_responses_fail_without_changing_prior_output(cli, tmp_path, kind, response):
    out = tmp_path / "output.png"
    out.write_bytes(b"previous output")
    getattr(cli.provider, "generate_batch" if kind == "generate-batch" else kind).return_value = response
    with pytest.raises(SystemExit) as error:
        cli.run(*command(tmp_path, kind, out, "--force"))
    assert error.value.code == 1
    assert out.read_bytes() == b"previous output"


@pytest.mark.parametrize("kind", ["generate", "edit", "generate-batch"])
def test_valid_response_saves_original_and_downscaled_image(cli, tmp_path, kind):
    out = tmp_path / "output.png"
    assert cli.run(*command(tmp_path, kind, out, "--downscale-max-dim", 80)) == 0
    assert out.read_bytes() == image_bytes()
    with Image.open(tmp_path / "output-web.png") as image:
        assert image.size == (80, 45)


def test_batch_preflights_all_jobs_before_any_request(cli, tmp_path):
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text("\n".join(json.dumps({"prompt": "Synthetic slide", "out": name})
                              for name in ("first.png", "existing.png")))
    (tmp_path / "existing.png").write_bytes(b"previous")
    with pytest.raises(SystemExit):
        cli.run("generate-batch", "--input", jobs, "--out-dir", tmp_path)
    cli.factory.assert_not_called()
    assert not (tmp_path / "first.png").exists()


def test_batch_rejects_overlapping_output_names_even_with_force(cli, tmp_path):
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text("\n".join(json.dumps({"prompt": f"Synthetic slide {i}", "out": "same.png"})
                              for i in (1, 2)))
    with pytest.raises(SystemExit):
        cli.run("generate-batch", "--input", jobs, "--out-dir", tmp_path, "--force")
    cli.factory.assert_not_called()


def test_every_response_is_validated_before_writing_first_image(cli, tmp_path):
    cli.provider.generate.return_value = [cli.encoded, "invalid base64"]
    with pytest.raises(SystemExit):
        cli.run("generate", "--prompt", "Synthetic slides", "--n", 2, "--out", tmp_path / "deck.png")
    assert not (tmp_path / "deck-1.png").exists()
    assert not (tmp_path / "deck-2.png").exists()


def test_explicit_force_replaces_existing_output(cli, tmp_path):
    out = tmp_path / "output.png"
    out.write_bytes(b"previous")
    assert cli.run("generate", "--prompt", "Synthetic slide", "--out", out, "--force") == 0
    assert out.read_bytes() == image_bytes()
    cli.provider.generate.assert_called_once()


def test_truncated_jpeg_cannot_overwrite_previous_output(cli, tmp_path):
    stream = io.BytesIO()
    Image.new("RGB", (1600, 900), "navy").save(stream, format="JPEG")
    original = stream.getvalue()
    truncated = original[:-100]
    out = tmp_path / "output.jpg"
    out.write_bytes(original)
    cli.provider.generate.return_value = [base64.b64encode(truncated).decode()]
    with pytest.raises(SystemExit) as error:
        cli.run("generate", "--prompt", "Synthetic slide", "--out", out,
                "--output-format", "jpeg", "--force")
    assert error.value.code == 1
    assert out.read_bytes() == original
