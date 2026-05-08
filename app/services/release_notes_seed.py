"""
Seed de release notes versionadas.

A lista `RELEASE_NOTES` abaixo é a fonte oficial de notas de atualização do app.
A função `seed_release_notes()` é idempotente — só insere versões que ainda
não existem no banco. Atualizações de texto em versões já existentes são
aplicadas via `_update_existing_fields`.

═══ Como adicionar uma nota nova ═══

Em prompts/features futuros que tragam mudanças visíveis ao usuário:

  1. Adicione um dicionário no topo de RELEASE_NOTES (versão mais nova primeiro).
  2. Use linguagem simples, sem termos técnicos (não cite migration, schema,
     endpoint, refactor, backend, frontend).
  3. Cada item da lista deve ser uma frase curta e útil ao usuário final.
  4. show_modal=True é o padrão; use False apenas quando a versão for
     interna/correção pequena que não precisa ser comunicada.
  5. Atualize `version` no `frontend/package.json` para a mesma versão.

Quando uma versão já existir no banco e o seed for chamado novamente, os
campos de texto são atualizados — então seguir o seed como fonte de verdade
ao corrigir typos/ajustar conteúdo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TypedDict

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.release_note import ReleaseNote

logger = logging.getLogger(__name__)


class _ReleaseNoteSpec(TypedDict, total=False):
    version: str
    title: str
    description: str | None
    items: list[str]
    show_modal: bool
    released_at: str  # ISO date


# ── Lista oficial de release notes (versão mais nova primeiro) ──────────────

RELEASE_NOTES: list[_ReleaseNoteSpec] = [
    {
        "version": "0.4.0",
        "title": "Ajustes finos no app",
        "description": (
            "Corrigimos a listagem de categorias e melhoramos a experiência "
            "ao entrar no app após uma atualização."
        ),
        "items": [
            "Suas categorias voltam a aparecer corretamente na tela de Categorias.",
            "Mensagens mais claras quando ocorre algum erro de carregamento.",
            "Ao publicarmos atualizações importantes, pediremos um novo login para garantir uma experiência consistente.",
        ],
        "show_modal": True,
        "released_at": "2026-05-08T00:00:00",
    },
    {
        "version": "0.3.0",
        "title": "Melhorias em Categorias",
        "description": (
            "Agora ficou mais fácil organizar seus gastos por cartão e "
            "acompanhar limites por categoria."
        ),
        "items": [
            "Crie categorias aplicadas a todos os cartões ou a um cartão específico.",
            "Organize seus gastos com subcategorias.",
            "Defina limite de gasto por fatura em cada categoria.",
            "Acompanhe visualmente quando uma categoria está perto do limite.",
            "A página de categorias recebeu melhorias visuais.",
        ],
        "show_modal": True,
        "released_at": "2026-05-07T00:00:00",
    },
]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _update_existing_fields(rn: ReleaseNote, spec: _ReleaseNoteSpec) -> bool:
    """Atualiza campos de texto da release note. Retorna True se algo mudou."""
    changed = False
    new_title = spec.get("title")
    new_desc = spec.get("description")
    new_items = json.dumps(spec.get("items", []), ensure_ascii=False)
    new_show = spec.get("show_modal", True)
    new_released = _parse_dt(spec.get("released_at"))

    if new_title and rn.title != new_title:
        rn.title = new_title; changed = True
    if rn.description != new_desc:
        rn.description = new_desc; changed = True
    if rn.items_json != new_items:
        rn.items_json = new_items; changed = True
    if rn.show_modal != new_show:
        rn.show_modal = new_show; changed = True
    if new_released and rn.released_at != new_released:
        rn.released_at = new_released; changed = True
    return changed


def seed_release_notes(db: Session | None = None) -> int:
    """
    Insere/atualiza release notes do `RELEASE_NOTES`. Idempotente.

    Retorna o número de versões criadas (não conta atualizações).
    """
    own_session = db is None
    session: Session = db or SessionLocal()
    created = 0
    try:
        for spec in RELEASE_NOTES:
            version = spec["version"]
            existing = session.query(ReleaseNote).filter(ReleaseNote.version == version).first()
            if existing:
                if _update_existing_fields(existing, spec):
                    logger.info("Release note v%s atualizada.", version)
                continue
            rn = ReleaseNote(
                version=version,
                title=spec["title"],
                description=spec.get("description"),
                items_json=json.dumps(spec.get("items", []), ensure_ascii=False),
                show_modal=spec.get("show_modal", True),
                released_at=_parse_dt(spec.get("released_at")),
            )
            session.add(rn)
            created += 1
            logger.info("Release note v%s criada.", version)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Erro ao seedar release notes")
        raise
    finally:
        if own_session:
            session.close()
    return created
