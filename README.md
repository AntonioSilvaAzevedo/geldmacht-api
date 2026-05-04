# Geldmacht API

Backend FastAPI do sistema financeiro Geldmacht.

## Stack

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy 2.0 + Alembic
- SQLite (local) / PostgreSQL (produção via Supabase)
- pdfplumber (parsers de extrato)

## Rodar localmente

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# editar .env com seus valores

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API disponível em http://localhost:8000  
Docs em http://localhost:8000/docs

## Variáveis de ambiente

Ver `.env.example` para referência completa.

## Deploy

Railway detecta o `railway.toml` automaticamente.  
Configurar as variáveis `DATABASE_URL` e `CORS_ORIGINS` no painel do Railway.
