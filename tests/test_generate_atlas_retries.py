"""Offline provider protocol fixtures; no network or paid calls occur."""
import asyncio
import base64
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure_stage", ["poll", "download"])
@pytest.mark.parametrize("failed_image", [1, 2])
def test_accepted_predictions_and_completed_images_survive_batch_retries(monkeypatch, failure_stage, failed_image):
    scripts = Path(__file__).resolve().parents[1] / "vendor/codex-ppt/skills/codex-ppt/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from image_providers.atlascloud import AtlasCloudImageProvider

    calls = []
    posted = []
    failed = []

    class Response:
        def __init__(self, value):
            self.value = value

        def read(self):
            return self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def fake_urlopen(request, timeout):
        method, url = request.get_method(), request.full_url
        calls.append((method, url))
        if method == "POST":
            posted.append(len(posted) + 1)
            return Response({"data": {"id": str(posted[-1])}})
        is_download = "assets.example.invalid" in url
        index = int(url.rsplit("/", 1)[1].removesuffix(".png"))
        stage = "download" if is_download else "poll"
        if index == failed_image and stage == failure_stage and not failed:
            failed.append(True)
            raise TimeoutError("Synthetic transient failure after accepted submission")
        if is_download:
            return Response(f"synthetic-image-{index}".encode())
        return Response({"data": {"status": "completed", "outputs": [f"https://assets.example.invalid/{index}.png"]}})

    async def no_sleep(_):
        pass

    monkeypatch.setattr("image_providers.atlascloud.asyncio.sleep", no_sleep)
    provider = AtlasCloudImageProvider(api_key="synthetic", base_url="https://api.example.invalid", urlopen=fake_urlopen)
    output = asyncio.run(provider.generate_batch({"model": "gpt-image-2.6", "prompt": "Synthetic fixture", "n": 2},
                                                 attempts=2, job_label="synthetic"))
    assert posted == [1, 2]
    assert output == [base64.b64encode(f"synthetic-image-{index}".encode()).decode() for index in (1, 2)]
    failed_url = f"https://assets.example.invalid/{failed_image}.png" if failure_stage == "download" else f"https://api.example.invalid/api/v1/model/result/{failed_image}"
    assert calls.count(("GET", failed_url)) == 2


def test_exhausted_poll_retries_do_not_submit_another_prediction(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "vendor/codex-ppt/skills/codex-ppt/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from image_providers.atlascloud import AtlasCloudImageProvider

    provider = AtlasCloudImageProvider(api_key="synthetic", base_url="https://api.example.invalid")
    accepted = []
    polled = []

    def submit(*_, **__):
        accepted.append("accepted-id")
        return "https://api.example.invalid/result/accepted-id"

    def poll(url):
        polled.append(url)
        raise TimeoutError("Synthetic polling outage")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(provider, "_submit_prediction", submit)
    monkeypatch.setattr(provider, "_poll_prediction", poll)
    monkeypatch.setattr("image_providers.atlascloud.asyncio.sleep", no_sleep)
    with pytest.raises(TimeoutError, match="Synthetic"):
        asyncio.run(provider.generate_batch({"n": 2}, attempts=3, job_label="synthetic"))
    assert accepted == ["accepted-id"]
    assert polled == ["https://api.example.invalid/result/accepted-id"] * 3
