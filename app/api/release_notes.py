"""
Endpoints de release notes / notas de atualização por versão.

  GET  /api/release-notes/pending           → lista acumulativa de releases que
                                              o usuário ainda não visualizou e
                                              têm show_modal=true. Ordem cronológica
                                              ascendente (mais antiga primeiro).
                                              Retorna {"releases": [...]} sempre,
                                              vazio quando não há pendências.

  POST /api/release-notes/mark-seen         → marca múltiplas como vistas
                                              (idempotente). Body: {release_note_ids: [int]}.

  POST /api/release-notes/{id}/mark-seen    → legado/compat. — marca uma única
                                              release como vista. Mantido para não
                                              quebrar clientes antigos.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.release_note import ReleaseNote, UserReleaseNoteView
from ..models.user import User
from ..schemas.release_note import (
    MarkSeenRequest,
    MarkSeenResponse,
    PendingReleaseNotesResponse,
    ReleaseNoteOut,
)

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


def _record_views(db: Session, user_id: int, release_note_ids: list[int]) -> list[int]:
    """
    Cria UserReleaseNoteView para cada release que ainda não tem registro.
    Idempotente — se uma já existe, não duplica. Retorna a lista de ids
    realmente persistidos como novos (ou pré-existentes — sempre os ids válidos).
    """
    if not release_note_ids:
        return []
    # Carrega todas as releases válidas em uma só query.
    rns = db.query(ReleaseNote).filter(ReleaseNote.id.in_(release_note_ids)).all()
    found_ids = {rn.id for rn in rns}
    # Quais já estão marcadas como vistas?
    existing = db.query(UserReleaseNoteView.release_note_id).filter(
        UserReleaseNoteView.user_id == user_id,
        UserReleaseNoteView.release_note_id.in_(found_ids),
    ).all()
    existing_ids = {row[0] for row in existing}
    to_create = [rn for rn in rns if rn.id not in existing_ids]
    for rn in to_create:
        db.add(UserReleaseNoteView(
            user_id=user_id,
            release_note_id=rn.id,
            version=rn.version,
        ))
    if to_create:
        db.commit()
    # Retorna todos os ids válidos (visto agora ou anteriormente).
    return sorted(found_ids)


@router.get(
    "/release-notes/pending",
    response_model=PendingReleaseNotesResponse,
    summary="Releases pendentes (acumulativo)",
    description=(
        "Retorna todas as release notes com show_modal=true que o usuário "
        "autenticado ainda não visualizou, ordenadas da mais antiga para a "
        "mais recente. Quando não há pendências, retorna `releases: []`."
    ),
)
def get_pending_release_notes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PendingReleaseNotesResponse:
    seen_subq = (
        db.query(UserReleaseNoteView.release_note_id)
        .filter(UserReleaseNoteView.user_id == current_user.id)
        .subquery()
    )
    rows = (
        db.query(ReleaseNote)
        .filter(
            ReleaseNote.show_modal.is_(True),
            ~ReleaseNote.id.in_(seen_subq.select()),
        )
        .order_by(
            # Cronológico ascendente: mais antiga primeiro.
            # released_at null vai por último (entre os com data) — usamos
            # created_at como tiebreaker para garantir determinismo.
            ReleaseNote.released_at.asc().nullslast(),
            ReleaseNote.created_at.asc(),
            ReleaseNote.id.asc(),
        )
        .all()
    )
    return PendingReleaseNotesResponse(releases=[_serialize(rn) for rn in rows])


@router.post(
    "/release-notes/mark-seen",
    response_model=MarkSeenResponse,
    summary="Marcar múltiplas release notes como vistas (bulk)",
    description=(
        "Body: `{release_note_ids: [int, int, ...]}`. Idempotente — chamadas "
        "repetidas não duplicam registros. Lista vazia é aceita e retorna sucesso. "
        "Use ao fechar o modal acumulativo de novidades."
    ),
)
def mark_release_notes_seen_bulk(
    body: MarkSeenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkSeenResponse:
    ids = list({int(i) for i in body.release_note_ids if i is not None})
    marked = _record_views(db, current_user.id, ids)
    return MarkSeenResponse(success=True, seen=True, marked_as_seen=marked)


@router.post(
    "/release-notes/{release_note_id}/mark-seen",
    response_model=MarkSeenResponse,
    summary="Marcar release note como visualizada (legado, single)",
    description=(
        "Mantido para compatibilidade. Prefira o bulk "
        "`POST /release-notes/mark-seen`. Idempotente."
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
    marked = _record_views(db, current_user.id, [rn.id])
    return MarkSeenResponse(success=True, seen=True, marked_as_seen=marked)
