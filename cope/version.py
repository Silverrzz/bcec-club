from __future__ import annotations

from importlib.resources import files


def app_version() -> str:
    """Return the deployment version shared by servers and workers."""
    version = files("cope").joinpath("VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("cope/VERSION is empty")
    return version
