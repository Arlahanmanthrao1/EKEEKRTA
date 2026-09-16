"""Opaque, private recording paths shared by intake and local media preparation."""
from pathlib import Path
import re

from app.config import settings


def recording_root() -> Path:
    configured = Path(settings.recording_storage_dir).expanduser()
    if not configured.is_absolute():
        configured = Path(__file__).resolve().parents[2] / configured
    root = configured.resolve()
    if root == root.parent or root == Path(__file__).resolve().parents[2]:
        raise ValueError("Choose a dedicated private recording directory")
    return root


def recording_path(root: Path, storage_key: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}\.(?:mp4|webm)", storage_key):
        raise ValueError("Invalid opaque recording key")
    target = (root / storage_key).resolve()
    if target.parent != root:
        raise ValueError("Recording path leaves the private directory")
    return target


def prepared_media_path(root: Path, storage_key: str) -> Path:
    recording_path(root, storage_key)
    parent = (root / "derived").resolve()
    if parent.parent != root:
        raise ValueError("Prepared-media parent leaves the private directory")
    target = (parent / storage_key.split(".", 1)[0]).resolve()
    if target.parent != parent:
        raise ValueError("Prepared-media path leaves the private directory")
    return target
