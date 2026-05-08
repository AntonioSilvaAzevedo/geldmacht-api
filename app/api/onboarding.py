"""
Endpoints do onboarding inicial do usuário.

  GET  /api/onboarding/status      → retorna se o usuário precisa ver o onboarding.
  POST /api/onboarding/mark-seen   → marca como visualizado. Idempotente.

Onboarding é por usuário e persiste em `users.onboarding_seen_at`.
Não confundir com release notes — release notes anunciam novidades por versão;
onboarding apresenta o sistema para usuários novos uma única vez.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..schemas.onboarding import OnboardingMarkSeenResponse, OnboardingStatusResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/onboarding/status",
    response_model=OnboardingStatusResponse,
    summary="Status do onboarding do usuário",
    description=(
        "Retorna `should_show_onboarding=true` quando o usuário ainda não "
        "marcou o onboarding inicial como visto. `onboarding_key` identifica "
        "qual onboarding (atualmente apenas `initial_app_overview`)."
    ),
)
def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),  # noqa: ARG001 (usado em outros endpoints)
) -> OnboardingStatusResponse:
    return OnboardingStatusResponse(
        should_show_onboarding=current_user.onboarding_seen_at is None,
        onboarding_key="initial_app_overview",
        seen_at=current_user.onboarding_seen_at,
    )


@router.post(
    "/onboarding/mark-seen",
    response_model=OnboardingMarkSeenResponse,
    summary="Marcar onboarding como visualizado",
    description=(
        "Define `users.onboarding_seen_at = now()` para o usuário autenticado. "
        "Idempotente — se já estiver definido, mantém o valor anterior e retorna sucesso."
    ),
)
def mark_onboarding_seen(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingMarkSeenResponse:
    if current_user.onboarding_seen_at is None:
        current_user.onboarding_seen_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(current_user)
    return OnboardingMarkSeenResponse(
        success=True,
        seen_at=current_user.onboarding_seen_at,
    )
