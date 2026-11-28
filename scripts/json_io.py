"""UTF-8 JSON input and atomic JSON output."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def checked_output_path(output, inputs):
    output = Path(output).resolve()
    if output in {Path(path).resolve() for path in inputs if path is not None}:
        raise ValueError("Report output must not overwrite an input or review artifact")
    return output


def write_json(path, value, *, ensure_ascii=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=ensure_ascii, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
