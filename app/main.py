"""
Geldmacht API — FastAPI entry point.

Rodar localmente:
    cd backend
    source venv/bin/activate
    uvicorn app.main:app --reload --port 8000

Docs interativas: http://localhost:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .api import cards, categories, dashboard, import_transactions, release_notes, transactions, upload
from .api.auth import router as auth_router
from .services.release_notes_seed import seed_release_notes

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
app.include_router(import_transactions.router, prefix="/api", tags=["Import"])
app.include_router(transactions.router, prefix="/api", tags=["Transações"])
app.include_router(cards.router, prefix="/api", tags=["Cartões"])
app.include_router(categories.router, prefix="/api", tags=["Categorias"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(release_notes.router, prefix="/api", tags=["Release Notes"])


@app.on_event("startup")
def _run_release_notes_seed() -> None:
    """Idempotente — só insere versões ainda não cadastradas."""
    try:
        seed_release_notes()
    except Exception:
        # Não trava o startup do app por falha de seed (logs já registrados).
        logging.getLogger(__name__).exception("Falha ao seedar release notes no startup")


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
