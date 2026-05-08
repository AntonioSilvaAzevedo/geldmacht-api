"""Schemas Pydantic para o fluxo de onboarding inicial."""
from datetime import datetime

from pydantic import BaseModel


class OnboardingStatusResponse(BaseModel):
    """Status do onboarding do usuário autenticado."""
    should_show_onboarding: bool
    onboarding_key: str = "initial_app_overview"
    seen_at: datetime | None = None


class OnboardingMarkSeenResponse(BaseModel):
    success: bool
    seen_at: datetime
