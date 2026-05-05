# AGENTS.md

Instruções para agentes trabalhando neste repositório.

## Visão Geral

Geldmacht API é um backend FastAPI para importar, pré-visualizar e persistir transações financeiras extraídas de PDFs ou planilhas.

Este arquivo é a documentação operacional viva do backend. Sempre que uma alteração mudar lógica de negócio, contrato de API, arquitetura, fluxo de dados, schema, parser, serviço ou migração, atualize também este `AGENTS.md` na mesma tarefa.

Stack principal:

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy 2.0 + Alembic
- SQLite local via `geldmacht.db`
- PostgreSQL em produção, configurado por `DATABASE_URL`
- `pdfplumber` para parsers de extratos PDF
- `pytest` para testes

## Estrutura

- `app/main.py`: ponto de entrada FastAPI e registro dos routers.
- `app/config.py`: configurações via `.env`, usando `pydantic-settings`.
- `app/database.py`: engine SQLAlchemy, `SessionLocal` e dependency `get_db`.
- `app/api/`: endpoints HTTP.
- `app/models/`: modelos SQLAlchemy.
- `app/schemas/`: schemas Pydantic.
- `app/services/`: serviços de domínio reutilizáveis, como cálculo de resumos.
- `app/parsers/`: parsers de extratos e autodetecção.
- `app/categorization/`: regras auxiliares de categorização.
- `alembic/`: migrações do banco.
- `tests/`: testes automatizados e fixtures sintéticas.

## Setup Local

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API local:

- `http://localhost:8000`
- `http://localhost:8000/docs`
- `http://localhost:8000/health`

## Comandos Úteis

Rodar testes:

```bash
source venv/bin/activate
pytest
```

Rodar teste específico:

```bash
source venv/bin/activate
pytest tests/test_nubank_pf.py
```

Aplicar migrações:

```bash
source venv/bin/activate
alembic upgrade head
```

Criar nova migração manualmente:

```bash
source venv/bin/activate
alembic revision -m "descricao_da_migracao"
```

## Rotas Principais

- `GET /`: health básico com nome, versão e docs.
- `GET /health`: status simples.
- `POST /api/upload`: recebe extrato PDF/Excel, detecta parser e retorna preview. Não persiste no banco. Quando o parser for `faturacartaonubank`, inclui `summary`.
- `POST /api/import`: recebe transações selecionadas, cria ou resolve `Account`, remove duplicatas e persiste novas transações. Quando a importação vier de `faturacartaonubank`, inclui `summary` calculado apenas sobre as transações realmente importadas.
- `GET /api/transactions`: lista transações persistidas, com filtros por mês, categoria e conta.
- `GET /api/dashboard/monthly`: agrega transações por mês para o dashboard anual.

## Convenções de Dados

- `Transaction.amount` usa negativo para saída e positivo para entrada.
- `ParsedTransaction.account` usa chaves como `nubank_pf`, `nubank_pj`, `nubank_cartao`, `itau`, `mercado_pago` e `b3`.
- `category` e `category_group` devem permanecer `None` no MVP quando vindos dos parsers. A categorização é tratada fora do backend nesse fluxo.
- Transferências internas devem marcar `is_internal_transfer=True` quando o parser conseguir identificar conta própria.
- Parcelamentos usam `installment_current` e `installment_total`.
- Importação considera duplicata por data, valor, descrição bruta e conta.

## Summary da Fatura

O backend calcula um resumo de fatura para o cartão Nubank usando `app/services/summary_service.py::calculate_invoice_summary`.

Schema:

- `app/schemas/summary.py::InvoiceSummary`
- `UploadResponse.summary: InvoiceSummary | None`
- `ImportResponse.summary: InvoiceSummary | None`

Contrato:

- `summary` só deve aparecer quando `parser_used == "faturacartaonubank"`.
- Os endpoints usam `response_model_exclude_none=True`, então para outros parsers a chave `summary` não deve aparecer no JSON.
- No `POST /api/upload`, o summary é calculado sobre todas as transações parseadas válidas da fatura.
- No `POST /api/import`, o summary é calculado apenas sobre as transações que foram realmente importadas. Transações ignoradas por duplicidade não entram no summary.

Regras de negócio:

- `amount < 0` é gasto de cartão.
- `amount > 0` é crédito, estorno, cashback ou entrada.
- `total_invoice` soma apenas gastos, usando valor positivo: `sum(abs(amount) for amount < 0)`.
- `total_credits` soma apenas entradas/créditos: `sum(amount for amount > 0)`.
- Entradas não entram no total da fatura.
- `largest_expense` é o valor absoluto do gasto mais negativo.
- `largest_expense_description` é a descrição do maior gasto.
- Compras parceladas são despesas com `installment_total is not None`.
- `total_installment_value` soma o valor absoluto das compras parceladas.
- `future_commitment` soma, para cada parcelada, `abs(amount) * (installment_total - installment_current)` quando houver parcelas restantes.

Campos do `InvoiceSummary`:

- `total_invoice: float`
- `total_credits: float`
- `total_transactions: int`
- `total_expenses: int`
- `total_credits_count: int`
- `largest_expense: float`
- `largest_expense_description: str`
- `total_installment_value: float`
- `total_installment_count: int`
- `future_commitment: float`

Validação real feita com `../geldmacht/docs-geldmacht/data/fatura.pdf`:

- `parser_used`: `faturacartaonubank`
- `total_transactions`: `104`
- `total_invoice`: `9039.17`
- `total_credits`: `12857.23`
- `total_expenses`: `97`
- `total_credits_count`: `7`
- `largest_expense`: `460.0`
- `largest_expense_description`: `Mercadao de Carnes`
- `total_installment_value`: `2506.3`
- `total_installment_count`: `23`
- `future_commitment`: `9321.91`

Testes específicos:

```bash
source venv/bin/activate
pytest tests/test_summary_service.py -v
```

## Parsers

O registro de parsers fica em `app/parsers/__init__.py`. A ordem de `ALL_PARSERS` importa: parsers mais específicos devem vir antes de parsers genéricos.

Todo parser deve:

- Implementar `can_parse(file_content: bytes)`.
- Implementar `parse(file_content: bytes)`.
- Retornar dicts compatíveis com `app/schemas/transaction.py::ParsedTransaction`.
- Evitar lançar erro em `can_parse`; em caso de arquivo inválido ou não reconhecido, retornar `False`.
- Usar fixtures sintéticas em testes sempre que possível. Não versionar extratos reais.

## Banco e Migrações

- Modelos ficam em `app/models/`.
- Sempre crie migração Alembic quando alterar schema persistido.
- `alembic/env.py` importa os models para popular `Base.metadata`.
- SQLite local usa `check_same_thread=False`; PostgreSQL não aceita esse argumento, e `app/database.py` já trata isso.

## Cuidados de Segurança

- Nunca commitar `.env`, `*.db`, `*.sqlite`, `venv/` ou dados reais em `data/`.
- Não commitar extratos bancários reais. Use fixtures sintéticas em `tests/fixtures/`.
- Ao tocar em upload/parsers, trate arquivos vazios, tipos não suportados e PDFs corrompidos sem expor detalhes sensíveis além do necessário.

## Estilo de Mudança

- Atualize este `AGENTS.md` sempre que mudar lógica de negócio, arquitetura, contrato de endpoint, schemas, parsers, serviços ou migrações.
- Preserve o estilo atual do projeto: módulos pequenos, funções diretas e comentários curtos quando ajudam.
- Prefira schemas Pydantic para validar fronteiras de API.
- Use SQLAlchemy ORM conforme os endpoints existentes.
- Mantenha mudanças focadas. Evite refactors amplos quando a tarefa for localizada.
- Ao alterar comportamento de parser, adicione ou ajuste testes em `tests/`.

## Verificação Recomendada

Antes de encerrar mudanças de backend:

```bash
source venv/bin/activate
pytest
```

Se mexer em banco ou modelos:

```bash
source venv/bin/activate
alembic upgrade head
pytest
```
