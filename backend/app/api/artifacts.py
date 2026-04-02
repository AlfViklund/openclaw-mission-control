"""Artifact CRUD and file upload/download endpoints."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlmodel import col

from app.api.deps import AUTH_DEP, require_user_auth
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.artifacts import Artifact
from app.models.boards import Board
from app.schemas.artifacts import ArtifactCreate, ArtifactRead, ArtifactUpdate
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.artifact_storage import (
    ArtifactStorageError,
    delete_artifact_file,
    get_artifact_preview,
    read_artifact_file,
    save_artifact_file,
)
from app.services.artifacts import (
    create_artifact,
    delete_artifact,
    get_artifact_by_id,
    list_artifacts,
    update_artifact,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.api.deps import ActorContext

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

SESSION_DEP = Depends(get_session)

UPLOAD_DEP = AUTH_DEP

USER_DEP = AUTH_DEP

_TEXT_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
)


def _is_text_mime(mime_type: str | None) -> bool:
    """Return True if the MIME type is likely text-based and safe to preview."""
    if not mime_type:
        return False
    return any(mime_type.startswith(prefix) for prefix in _TEXT_MIME_PREFIXES)


@router.post("", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    file: UploadFile,
    board_id: UUID = Query(...),
    task_id: UUID | None = Query(default=None),
    artifact_type: str = Query(default="other"),
    source: str = Query(default="web"),
    user: ActorContext = UPLOAD_DEP,
    session: AsyncSession = SESSION_DEP,
) -> Artifact:
    """Upload a file and create an artifact record."""
    board = await Board.objects.by_id(board_id).first(session)
    if not board:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )

    filename = file.filename or "unnamed"
    mime_type = file.content_type

    existing = await Artifact.objects.filter_by(
        board_id=board_id, filename=filename
    ).all(session)
    auto_version = max((a.version for a in existing), default=0) + 1

    try:
        storage_path, size_bytes, checksum = save_artifact_file(
            board_id=str(board_id),
            filename=filename,
            content=content,
        )
    except ArtifactStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    artifact = await create_artifact(
        session,
        board_id=board_id,
        filename=filename,
        storage_path=storage_path,
        task_id=task_id,
        artifact_type=artifact_type,
        source=source,
        mime_type=mime_type,
        size_bytes=size_bytes,
        checksum=checksum,
        version=auto_version,
        created_by=user.user.id if user.user else None,
    )
    return artifact


@router.post(
    "/metadata", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED
)
async def create_artifact_metadata(
    payload: ArtifactCreate,
    user: ActorContext = USER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> Artifact:
    """Create an artifact record without file upload (for externally-stored files)."""
    board = await Board.objects.by_id(payload.board_id).first(session)
    if not board:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
        )

    storage_path = f"external/{payload.board_id}/{payload.filename}"

    artifact = await create_artifact(
        session,
        board_id=payload.board_id,
        filename=payload.filename,
        storage_path=storage_path,
        task_id=payload.task_id,
        artifact_type=payload.type,
        source=payload.source,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        checksum=payload.checksum,
        version=payload.version,
        created_by=user.user.id if user.user else None,
    )
    return artifact


@router.get("", response_model=DefaultLimitOffsetPage[ArtifactRead])
async def list_artifacts_endpoint(
    board_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    artifact_type: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Search in filename"),
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> DefaultLimitOffsetPage[ArtifactRead]:
    """List artifacts with optional filtering by board, task, type, and search."""
    statement = Artifact.objects.all()
    if board_id is not None:
        statement = statement.filter(col(Artifact.board_id) == board_id)
    if task_id is not None:
        statement = statement.filter(col(Artifact.task_id) == task_id)
    if artifact_type is not None:
        statement = statement.filter(col(Artifact.type) == artifact_type)
    if q is not None:
        statement = statement.filter(col(Artifact.filename).ilike(f"%{q}%"))
    statement = statement.order_by(col(Artifact.created_at).desc())
    return await paginate(session, statement.statement)


@router.get("/{artifact_id}", response_model=ArtifactRead)
async def get_artifact(
    artifact_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> Artifact:
    """Get artifact metadata by ID."""
    artifact = await get_artifact_by_id(session, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
        )
    return artifact


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> StreamingResponse:
    """Download the artifact file."""
    artifact = await get_artifact_by_id(session, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
        )

    try:
        content = read_artifact_file(artifact.storage_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact file not found on disk",
        ) from None

    return StreamingResponse(
        io.BytesIO(content),
        media_type=artifact.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


@router.get("/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> dict[str, str | None]:
    """Get a text preview of the artifact (for text-based files only)."""
    artifact = await get_artifact_by_id(session, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
        )

    if not _is_text_mime(artifact.mime_type):
        return {"preview": None, "reason": "Binary file type not previewable"}

    preview = get_artifact_preview(artifact.storage_path)
    if preview is None:
        return {"preview": None, "reason": "File not found or not decodable as text"}

    return {"preview": preview}


@router.patch("/{artifact_id}", response_model=ArtifactRead)
async def update_artifact_endpoint(
    artifact_id: UUID,
    payload: ArtifactUpdate,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> Artifact:
    """Update artifact metadata."""
    artifact = await get_artifact_by_id(session, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
        )

    artifact = await update_artifact(
        session,
        artifact,
        task_id=payload.task_id,
        filename=payload.filename,
    )
    return artifact


@router.delete("/{artifact_id}", response_model=OkResponse)
async def delete_artifact_endpoint(
    artifact_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _actor: ActorContext = USER_DEP,
) -> OkResponse:
    """Delete an artifact and its stored file."""
    artifact = await get_artifact_by_id(session, artifact_id)
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
        )

    try:
        delete_artifact_file(artifact.storage_path)
    except OSError:
        pass

    await delete_artifact(session, artifact)
    return OkResponse(ok=True)
