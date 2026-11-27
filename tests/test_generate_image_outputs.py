"""Offline API boundary checks; providers and returned images are synthetic fixtures."""
import base64
import hashlib
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


def image_bytes(color="navy", size=(2560, 1440)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
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


@pytest.mark.parametrize("kind", ["generate", "edit", "generate-batch"])
def test_wrong_response_dimensions_never_replace_previous_outputs(cli, tmp_path, kind):
    out = tmp_path / "output.png"
    out.write_bytes(b"previous approved original")
    downscaled = tmp_path / "output-web.png"
    downscaled.write_bytes(b"previous approved preview")
    getattr(cli.provider, "generate_batch" if kind == "generate-batch" else kind).return_value = [
        base64.b64encode(image_bytes(size=(16, 9))).decode()]
    with pytest.raises(SystemExit) as error:
        cli.run(*command(tmp_path, kind, out, "--size", "2560x1440", "--force", "--downscale-max-dim", 80))
    assert error.value.code == 1
    assert out.read_bytes() == b"previous approved original"
    assert downscaled.read_bytes() == b"previous approved preview"


@pytest.mark.parametrize("kind", ["generate", "edit", "generate-batch"])
def test_auto_size_accepts_provider_selected_dimensions(cli, tmp_path, kind):
    out = tmp_path / "output.png"
    raw = image_bytes(size=(1280, 720))
    getattr(cli.provider, "generate_batch" if kind == "generate-batch" else kind).return_value = [base64.b64encode(raw).decode()]
    assert cli.run(*command(tmp_path, kind, out, "--size", "auto")) == 0
    assert out.read_bytes() == raw


def test_every_response_size_is_checked_before_writing_any_image(cli, tmp_path):
    cli.provider.generate.return_value = [cli.encoded, base64.b64encode(image_bytes(size=(16, 9))).decode()]
    with pytest.raises(SystemExit):
        cli.run("generate", "--prompt", "Synthetic slides", "--n", 2, "--out", tmp_path / "deck.png")
    assert not (tmp_path / "deck-1.png").exists()
    assert not (tmp_path / "deck-2.png").exists()


def structured_request(tmp_path, kind="job"):
    reference = tmp_path / "single-page-reference.png"
    reference.write_bytes(image_bytes("purple", (480, 270)))
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    if kind == "job":
        value = {"prompt": "Synthetic independent slide; preserve the selected visual style",
                 "input_images": [{"path": str(reference), "sha256": digest}], "requires_context_images": True}
    else:
        value = {"instructions": "Synthetic independent produce request", "slide": {"id": "s01"},
                 "style_reference": {"kind": "preview-crop", "sha256": digest, "source_sha256": "1" * 64,
                                     "reference_snapshot": f"artifacts/{digest}.style-reference.png",
                                     "source_snapshot": "artifacts/selected-overview.style-source.png"}}
    request = tmp_path / "request.json"
    request.write_text(json.dumps(value), encoding="utf-8")
    return request, reference


@pytest.mark.parametrize("kind", ["job", "produce"])
@pytest.mark.parametrize("dry", [False, True])
def test_generate_never_silently_drops_structured_reference_images(cli, tmp_path, capsys, kind, dry):
    request, _ = structured_request(tmp_path, kind)
    with pytest.raises(SystemExit):
        cli.run("generate", "--prompt-file", request, "--out", tmp_path / "output.png", *(["--dry-run"] if dry else []))
    assert "edit --prompt-file" in capsys.readouterr().err
    cli.factory.assert_not_called()
    assert not (tmp_path / "output.png").exists()


@pytest.mark.parametrize("kind", ["job", "produce"])
def test_structured_edit_dry_run_attaches_the_actual_selected_pixels(cli, tmp_path, capsys, kind):
    request, reference = structured_request(tmp_path, kind)
    # Produce snapshots are relative to a different root. A copy with exactly
    # the declared bytes must work without guessing artifacts/artifacts paths.
    attached = tmp_path / "actual-upload.png"
    attached.write_bytes(reference.read_bytes())
    assert cli.run("edit", "--prompt-file", request, "--image", attached,
                   "--dry-run", "--out", tmp_path / "output.png") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == [str(attached)]
    assert payload["endpoint"].endswith("/edits")
    if kind == "job":
        assert "Synthetic independent slide" in payload["prompt"]
        assert "input_images" not in payload["prompt"]
    cli.factory.assert_not_called()


@pytest.mark.parametrize("kind", ["job", "produce"])
@pytest.mark.parametrize("problem", ["wrong", "extra-overview"])
def test_structured_edit_rejects_wrong_or_additional_reference_images(cli, tmp_path, kind, problem):
    request, reference = structured_request(tmp_path, kind)
    overview = tmp_path / "overview.png"
    overview.write_bytes(image_bytes("orange", (1600, 900)))
    attachments = ["--image", overview] if problem == "wrong" else ["--image", reference, "--image", overview]
    with pytest.raises(SystemExit):
        cli.run("edit", "--prompt-file", request, *attachments, "--out", tmp_path / "output.png")
    cli.factory.assert_not_called()


def test_structured_edit_preserves_input_order_and_checks_missing_images(cli, tmp_path):
    request, reference = structured_request(tmp_path)
    asset = tmp_path / "evidence.png"
    asset.write_bytes(image_bytes("green", (80, 80)))
    value = json.loads(request.read_text())
    value["input_images"].append({"path": "evidence.png"})
    request.write_text(json.dumps(value), encoding="utf-8")
    for attachments in ([reference], [asset, reference]):
        arguments = [argument for path in attachments for argument in ("--image", path)]
        with pytest.raises(SystemExit):
            cli.run("edit", "--prompt-file", request, *arguments, "--out", tmp_path / "output.png")
    cli.factory.assert_not_called()
    assert cli.run("edit", "--prompt-file", request, "--image", reference, "--image", asset,
                   "--out", tmp_path / "output.png") == 0
    payload, paths, _ = cli.provider.edit.call_args.args
    assert paths == [reference, asset]
    assert "input_images" not in payload["prompt"]


def test_plain_text_prompt_file_keeps_existing_generate_behavior(cli, tmp_path):
    request = tmp_path / "prompt.txt"
    request.write_text("Synthetic plain text slide", encoding="utf-8")
    assert cli.run("generate", "--prompt-file", request, "--out", tmp_path / "output.png") == 0
    cli.provider.generate.assert_called_once()


def test_batch_with_image_inputs_fails_before_calling_provider(cli, tmp_path):
    request, _ = structured_request(tmp_path)
    batch = tmp_path / "jobs.jsonl"
    batch.write_text(json.dumps(json.loads(request.read_text())) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.run("generate-batch", "--input", batch, "--out-dir", tmp_path)
    cli.factory.assert_not_called()


@pytest.mark.parametrize("kind", ["job", "produce"])
def test_inline_structured_requests_require_the_same_actual_image_inputs(cli, tmp_path, capsys, kind):
    request, reference = structured_request(tmp_path, kind)
    inline = request.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.run("generate", "--prompt", inline, "--dry-run", "--out", tmp_path / "output.png")
    assert "edit --prompt-file" in capsys.readouterr().err
    cli.factory.assert_not_called()
    assert cli.run("edit", "--prompt", inline, "--image", reference,
                   "--dry-run", "--out", tmp_path / "output.png") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == [str(reference)]
    cli.factory.assert_not_called()
    assert not (tmp_path / "output.png").exists()


@pytest.mark.parametrize("inline", [False, True])
def test_legacy_style_anchor_requires_its_declared_image_bytes(cli, tmp_path, capsys, inline):
    request, reference = structured_request(tmp_path)
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    packet = {"instructions": "Synthetic legacy produce request", "slide": {"id": "s02"},
              "style_anchor": {"slide_id": "s01", "image_snapshot": f"artifacts/{digest}.png",
                               "image_sha256": digest, "use": "Preserve the selected design language"}}
    request.write_text(json.dumps(packet), encoding="utf-8")
    source = ["--prompt", json.dumps(packet)] if inline else ["--prompt-file", request]
    with pytest.raises(SystemExit):
        cli.run("generate", *source, "--dry-run", "--out", tmp_path / "output.png")
    assert "edit --prompt-file" in capsys.readouterr().err
    wrong = tmp_path / "different-reference.png"
    wrong.write_bytes(image_bytes("orange", (480, 270)))
    with pytest.raises(SystemExit):
        cli.run("edit", *source, "--image", wrong, "--dry-run", "--out", tmp_path / "output.png")
    assert "differs from" in capsys.readouterr().err
    cli.factory.assert_not_called()
    assert cli.run("edit", *source, "--image", reference,
                   "--dry-run", "--out", tmp_path / "output.png") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == [str(reference)]
    cli.factory.assert_not_called()
    assert not (tmp_path / "output.png").exists()
