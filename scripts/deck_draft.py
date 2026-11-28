"""Retain a managed Office draft without leaving a stand-alone presentation."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MANAGED = ".workbuddy-review"
PACKAGE = ".draft-package"
DECK_NAME = re.compile(r"deck-[a-f0-9]{64}\.pptx")


def current_deck(work: Path) -> Path | None:
    from run_deck import cached_state

    record = cached_state(work).get("build")
    if record is None:
        return None
    path = Path(record["path"])
    if path.parent != work / "cache" or not DECK_NAME.fullmatch(path.name) or path.is_symlink():
        raise ValueError("Managed draft path differs from the owned cache")
    return path


def keep_draft(work: Path, deck: Path) -> None:
    from render_deck import sha256
    from run_deck import cached_state

    if sha256(deck) != cached_state(work)["build"]["sha256"]:
        raise ValueError("Managed draft changed during review")
    with tempfile.NamedTemporaryFile(prefix=".draft-", dir=work, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with ZipFile(temporary, "w") as package:
            package.write(deck, deck.name)
        os.replace(temporary, work / PACKAGE)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def office_draft(work: Path):
    """Use Office's native file format only while the workspace lock is held."""
    from render_deck import sha256
    from run_deck import cached_state

    cache = work / "cache"
    if cache.resolve() != cache:
        raise ValueError("Managed cache must stay inside the review workspace")
    stored = work / PACKAGE
    deck = current_deck(work)
    try:
        if deck and stored.is_file() and not deck.exists():
            try:
                with ZipFile(stored) as package:
                    if package.namelist() == [deck.name]:
                        cache.mkdir(parents=True, exist_ok=True)
                        with package.open(deck.name) as source, deck.open("xb") as destination:
                            shutil.copyfileobj(source, destination)
            except BadZipFile:
                deck.unlink(missing_ok=True)
            if deck.is_file() and sha256(deck) != cached_state(work)["build"]["sha256"]:
                deck.unlink()
        yield
    finally:
        try:
            current = current_deck(work)
            if current and current.is_file() and sha256(current) == cached_state(work)["build"]["sha256"]:
                keep_draft(work, current)
        finally:
            for path in cache.glob("deck-*.pptx"):
                if DECK_NAME.fullmatch(path.name):
                    path.unlink()
