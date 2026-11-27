"""Decide whether a main-branch push requires a new release."""

import os
import re
import subprocess
from pathlib import Path

import yaml


def version_from_manifest(text: str) -> str:
    version = yaml.safe_load(text)["version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid release version")
    return version


def should_publish(event: str, before_sha: str, current_version: str) -> bool:
    if event == "workflow_dispatch":
        return True
    if event != "push" or not re.fullmatch(r"[0-9a-f]{40}", before_sha):
        raise ValueError("Expected a push event with a valid before SHA")
    if before_sha == "0" * 40:
        return True
    previous = subprocess.run(
        ["git", "show", f"{before_sha}:manifest.yaml"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return version_from_manifest(previous.stdout) != current_version


def main() -> None:
    current = version_from_manifest(Path("manifest.yaml").read_text(encoding="utf-8"))
    publish = should_publish(
        os.environ["GITHUB_EVENT_NAME"], os.environ.get("BEFORE_SHA", ""), current
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"publish={str(publish).lower()}\n")
    if not publish:
        print(f"Manifest version {current} unchanged; no release needed.")


if __name__ == "__main__":
    main()
