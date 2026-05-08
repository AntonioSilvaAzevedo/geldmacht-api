"""
Endpoints de release notes / notas de atualização por versão.

  GET  /api/release-notes/pending          → release note mais recente que o
                                              usuário ainda não visualizou e que
                                              tem show_modal=true. Retorna 204
                                              quando não há nenhuma pendente.
  POST /api/release-notes/{id}/mark-seen   → marca como visualizada (idempotente).
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.release_note import ReleaseNote, UserReleaseNoteView
from ..models.user import User
from ..schemas.release_note import MarkSeenResponse, ReleaseNoteOut

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize(rn: ReleaseNote) -> ReleaseNoteOut:
    try:
        items = json.loads(rn.items_json) if rn.items_json else []
        if not isinstance(items, list):
            items = []
    except json.JSONDecodeError:
        items = []
    return ReleaseNoteOut(
        id=rn.id,
        version=rn.version,
        title=rn.title,
        description=rn.description,
        items=[str(it) for it in items],
        show_modal=rn.show_modal,
        released_at=rn.released_at,
        created_at=rn.created_at,
        updated_at=rn.updated_at,
    )


@router.get(
    "/release-notes/pending",
    response_model=ReleaseNoteOut | None,
    summary="Próxima release note pendente para o usuário",
    description=(
        "Retorna a release note mais recente que o usuário autenticado ainda "
        "não visualizou e que possui show_modal=true. Quando não há nenhuma "
        "pendente, retorna 204 No Content."
    ),
)
def get_pending_release_note(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    seen_subq = (
        db.query(UserReleaseNoteView.release_note_id)
        .filter(UserReleaseNoteView.user_id == current_user.id)
        .subquery()
    )
    rn = (
        db.query(ReleaseNote)
        .filter(
            ReleaseNote.show_modal.is_(True),
            ~ReleaseNote.id.in_(seen_subq),
        )
        .order_by(
            ReleaseNote.released_at.desc().nullslast(),
            ReleaseNote.created_at.desc(),
            ReleaseNote.id.desc(),
        )
        .first()
    )
    if not rn:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return _serialize(rn)


@router.post(
    "/release-notes/{release_note_id}/mark-seen",
    response_model=MarkSeenResponse,
    summary="Marcar release note como visualizada",
    description=(
        "Registra que o usuário autenticado já viu a release note. "
        "Idempotente — chamadas subsequentes não duplicam o registro."
    ),
)
def mark_release_note_seen(
    release_note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkSeenResponse:
    rn = db.query(ReleaseNote).filter(ReleaseNote.id == release_note_id).first()
    if not rn:
        raise HTTPException(status_code=404, detail="Release note não encontrada.")

    existing = db.query(UserReleaseNoteView).filter(
        UserReleaseNoteView.user_id == current_user.id,
        UserReleaseNoteView.release_note_id == rn.id,
    ).first()
    if existing:
        return MarkSeenResponse(success=True, seen=True)

    view = UserReleaseNoteView(
        user_id=current_user.id,
        release_note_id=rn.id,
        version=rn.version,
    )
    db.add(view)
    db.commit()
    return MarkSeenResponse(success=True, seen=True)
