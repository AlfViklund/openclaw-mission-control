"""Local filesystem storage for artifact files."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_DIR = BACKEND_ROOT / "storage" / "artifacts"


class ArtifactStorageError(Exception):
    """Raised when an artifact storage operation fails."""


def _storage_root() -> Path:
    """Return the configured artifact storage root directory."""
    storage_env = getattr(settings, "artifact_storage_path", None)
    if storage_env:
        return Path(storage_env)
    return DEFAULT_STORAGE_DIR


def _ensure_board_dir(board_id: str) -> Path:
    """Ensure the board-scoped subdirectory exists and return it."""
    board_dir = _storage_root() / str(board_id)
    board_dir.mkdir(parents=True, exist_ok=True)
    return board_dir


def compute_checksum(data: bytes) -> str:
    """Compute SHA-256 hex digest for the given bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_checksum_stream(stream: BinaryIO, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hex digest for a binary stream without loading it all into memory."""
    hasher = hashlib.sha256()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()


def save_artifact_file(
    *,
    board_id: str,
    filename: str,
    content: bytes | None = None,
    stream: BinaryIO | None = None,
) -> tuple[str, int, str]:
    """Save an artifact file to local storage.

    Args:
        board_id: Board UUID for directory scoping.
        filename: Original filename (will be made safe).
        content: Raw bytes to write (mutually exclusive with stream).
        stream: Binary stream to read from (mutually exclusive with content).

    Returns:
        Tuple of (storage_path, size_bytes, checksum).

    Raises:
        ArtifactStorageError: If neither content nor stream is provided, or on write failure.
    """
    if content is None and stream is None:
        raise ArtifactStorageError("Either content or stream must be provided.")

    safe_filename = Path(filename).name
    board_dir = _ensure_board_dir(board_id)
    target_path = board_dir / safe_filename

    try:
        if content is not None:
            checksum = compute_checksum(content)
            target_path.write_bytes(content)
            size = len(content)
        else:
            with target_path.open("wb") as f:
                shutil.copyfileobj(stream, f)
            with target_path.open("rb") as f:
                checksum = compute_checksum_stream(f)
            size = target_path.stat().st_size

        relative_path = str(target_path.relative_to(_storage_root()))
        return relative_path, size, checksum

    except OSError as exc:
        raise ArtifactStorageError(f"Failed to save artifact file: {exc}") from exc


def read_artifact_file(storage_path: str) -> bytes:
    """Read an artifact file from storage and return its bytes."""
    full_path = _storage_root() / storage_path
    if not full_path.exists():
        raise FileNotFoundError(f"Artifact file not found: {full_path}")
    return full_path.read_bytes()


def delete_artifact_file(storage_path: str) -> None:
    """Delete an artifact file from storage."""
    full_path = _storage_root() / storage_path
    if full_path.exists():
        full_path.unlink()


def get_artifact_preview(storage_path: str, max_bytes: int = 65536) -> str | None:
    """Return a text preview of the artifact if it appears to be text-based.

    Returns None for binary files or if the file cannot be decoded.
    """
    full_path = _storage_root() / storage_path
    if not full_path.exists():
        return None

    try:
        raw = full_path.read_bytes()[:max_bytes]
        return raw.decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return None
