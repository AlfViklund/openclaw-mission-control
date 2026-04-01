"""CRUD operations for Artifact model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col

from app.models.artifacts import Artifact

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


async def create_artifact(
    session: AsyncSession,
    *,
    board_id: UUID,
    filename: str,
    storage_path: str,
    task_id: UUID | None = None,
    artifact_type: str = "other",
    source: str = "web",
    mime_type: str | None = None,
    size_bytes: int = 0,
    checksum: str | None = None,
    version: int = 1,
    created_by: UUID | None = None,
) -> Artifact:
    """Create a new artifact record."""
    artifact = Artifact(
        board_id=board_id,
        task_id=task_id,
        type=artifact_type,
        source=source,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        storage_path=storage_path,
        checksum=checksum,
        version=version,
        created_by=created_by,
    )
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def get_artifact_by_id(session: AsyncSession, artifact_id: UUID) -> Artifact | None:
    """Fetch a single artifact by its ID."""
    return await Artifact.objects.by_id(artifact_id).first(session)


async def list_artifacts(
    session: AsyncSession,
    *,
    board_id: UUID | None = None,
    task_id: UUID | None = None,
    artifact_type: str | None = None,
) -> list[Artifact]:
    """List artifacts with optional filters."""
    statement = Artifact.objects.all()
    if board_id is not None:
        statement = statement.filter(col(Artifact.board_id) == board_id)
    if task_id is not None:
        statement = statement.filter(col(Artifact.task_id) == task_id)
    if artifact_type is not None:
        statement = statement.filter(col(Artifact.type) == artifact_type)
    statement = statement.order_by(col(Artifact.created_at).desc())
    return await statement.all(session)


async def update_artifact(
    session: AsyncSession,
    artifact: Artifact,
    *,
    task_id: UUID | None = None,
    filename: str | None = None,
) -> Artifact:
    """Update artifact metadata fields."""
    if task_id is not None:
        artifact.task_id = task_id
    if filename is not None:
        artifact.filename = filename
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def delete_artifact(session: AsyncSession, artifact: Artifact) -> None:
    """Delete an artifact record. Caller is responsible for removing the file."""
    await session.delete(artifact)
    await session.commit()
