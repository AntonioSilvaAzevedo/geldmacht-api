"""
Geldmacht API — FastAPI entry point.

Rodar localmente:
    cd geldmacht-api
    source venv/bin/activate
    uvicorn app.main:app --reload --port 8010

Docs interativas: http://localhost:8010/docs
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .api import bank_accounts, cards, categories, dashboard, import_transactions, institutions, onboarding, release_notes, summary, tags, transactions, upload
from .api.auth import router as auth_router
from .services.release_notes_seed import seed_release_notes
from .services.test_user_seed import seed_test_user

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    description="API para importação e categorização de extratos financeiros.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

@app.middleware("http")
async def handle_unhandled_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logging.getLogger(__name__).exception(
            "Erro não tratado em %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno do servidor."},
        )


# ── CORS — lê origens da variável CORS_ORIGINS (vírgula-separadas) ──────────
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(bank_accounts.router, prefix="/api", tags=["Contas bancárias"])
app.include_router(institutions.router, prefix="/api", tags=["Instituições"])
app.include_router(import_transactions.router, prefix="/api", tags=["Import"])
app.include_router(transactions.router, prefix="/api", tags=["Transações"])
app.include_router(tags.router, prefix="/api", tags=["Tags"])
app.include_router(cards.router, prefix="/api", tags=["Cartões"])
app.include_router(categories.router, prefix="/api", tags=["Categorias"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(summary.router, prefix="/api", tags=["Resumo"])
app.include_router(release_notes.router, prefix="/api", tags=["Release Notes"])
app.include_router(onboarding.router, prefix="/api", tags=["Onboarding"])


@app.on_event("startup")
def _run_alembic_upgrade() -> None:
    """
    Aplica migrations no startup, em produção. Evita situação onde o backend
    sobe com schema desatualizado (ex: coluna nova ainda não criada) e endpoints
    quebram silenciosamente.

    Controle por env: AUTO_MIGRATE_ON_STARTUP (default "1"). Defina "0" para desligar.
    """
    import os
    if os.getenv("AUTO_MIGRATE_ON_STARTUP", "1") not in ("1", "true", "True"):
        return
    try:
        from alembic import command
        from alembic.config import Config
        from pathlib import Path
        cfg_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not cfg_path.exists():
            logging.getLogger(__name__).warning("alembic.ini não encontrado em %s — pulando upgrade", cfg_path)
            return
        cfg = Config(str(cfg_path))
        command.upgrade(cfg, "head")
        logging.getLogger(__name__).info("Alembic upgrade head aplicado no startup.")
    except Exception:
        logging.getLogger(__name__).exception("Falha ao aplicar migrations no startup")


@app.on_event("startup")
def _run_release_notes_seed() -> None:
    """Idempotente — só insere versões ainda não cadastradas."""
    try:
        seed_release_notes()
    except Exception:
        # Não trava o startup do app por falha de seed (logs já registrados).
        logging.getLogger(__name__).exception("Falha ao seedar release notes no startup")


@app.on_event("startup")
def _run_test_user_seed() -> None:
    """Idempotente — só cria o usuário de teste quando SEED_TEST_USER está habilitado."""
    try:
        seed_test_user()
    except Exception:
        logging.getLogger(__name__).exception("Falha ao seedar usuário de teste no startup")


@app.get("/", tags=["Health"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}
