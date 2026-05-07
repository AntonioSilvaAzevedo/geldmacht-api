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
- `docs/`: documentação técnica complementar — `docs/FATURA-NUBANK-PDF.md` (fatura Nubank).
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
- `GET /api/transactions/invoice?invoice_id={id}`: **preferencial** — lista transações de uma fatura pelo `invoice_id`, retornando `transactions` e `summary`.
- `GET /api/transactions/invoice?card_id={id}&month=YYYY-MM`: legado — busca por `reference_month` com fallback para `billing_month` e depois `date`.
- `GET /api/cards`: lista cartões de crédito do usuário autenticado.
- `GET /api/cards/{card_id}`: retorna um cartão do usuário autenticado.
- `POST /api/cards`: cria cartão com `name`, `institution`, `closing_day` e `due_day`.
- `PATCH /api/cards/{card_id}`: edita configuração do cartão do usuário.
- `DELETE /api/cards/{card_id}`: remove cartão e exclui em cascata transactions + invoices vinculadas. Operação atômica.
- `GET /api/cards/{card_id}/invoices`: lista invoices reais (`Invoice` table) com totais calculados das transactions.
- `GET /api/cards/{card_id}/invoices/{invoice_id}`: retorna fatura completa (metadados + transactions + summary).
- `GET /api/cards/{card_id}/invoices-by-month/{due_month}`: busca invoice por `due_month` (compat. legada com `/cartao/[cardId]/[anoMes]`).
- `GET /api/categories?scope=credit_card`: lista categorias manuais do usuário para fatura de cartão.
- `POST /api/categories`: cria categoria manual. Neste momento aceita apenas `scope = credit_card`.
- `PATCH /api/categories/{category_id}`: edita categoria do usuário.
- `DELETE /api/categories/{category_id}`: remove categoria do usuário e desvincula transações que usavam `category_id`.
- `GET /api/dashboard/monthly`: agrega transações por mês para o dashboard anual.

## Convenções de Dados

- `Transaction.amount` usa negativo para saída e positivo para entrada.
- `ParsedTransaction.account` usa chaves como `nubank_pf`, `nubank_pj`, `nubank_cartao`, `itau`, `mercado_pago` e `b3`.
- Categorias manuais usam tabela `categories` com `scope = credit_card`.
- Transferências internas devem marcar `is_internal_transfer=True` quando o parser conseguir identificar conta própria.
- Pagamentos da fatura anterior no cartão Nubank devem marcar `is_payment=True`.
- Parcelamentos usam `installment_current` e `installment_total`.
- Faturas de cartão importadas por cartão cadastrado devem salvar `card_id`, `invoice_id` e `reference_month` (legado).
- `transaction.date` é a **data real da compra** e deve sempre ser preservada. Nunca deve ser usada como fonte primária para determinar a fatura.
- `invoice_id` é a âncora principal de cada transação de fatura. Todas as transactions novas de cartão devem ter `invoice_id`.
- `reference_month` e `billing_month` são campos legados mantidos para compatibilidade com dados antigos.
- Importação considera duplicata por data, valor, descrição bruta e conta.

## Entidade Invoice / Fatura

Model: `app/models/invoice.py::Invoice`.

Representa um ciclo real de fatura de cartão. É a âncora principal para as transactions importadas — toda transaction de cartão deve ter um `invoice_id`.

Campos:

| Campo                | Tipo         | Descrição                                                         |
|----------------------|--------------|-------------------------------------------------------------------|
| `id`                 | Integer      | PK da fatura                                                      |
| `user_id`            | Integer      | Dono da fatura                                                    |
| `card_id`            | Integer      | Cartão ao qual pertence                                           |
| `due_month`          | String(7)    | Mês de pagamento/vencimento no formato `YYYY-MM` (ex: `2026-04`) |
| `due_date`           | Date         | Data exata de vencimento (ex: `2026-04-13`); null para legados    |
| `cycle_start_date`   | Date         | Início do período vigente (ex: `2026-03-04`); null para legados   |
| `cycle_end_date`     | Date         | Fim do período vigente (ex: `2026-04-04`); null para legados      |
| `issue_date`         | Date         | Data de emissão/envio da fatura; null para legados                |
| `closing_date`       | Date         | Data de fechamento (= `cycle_end_date` em geral); null p/ legados |
| `total_amount`       | Float        | Valor total extraído do PDF ("Total a pagar"); null para legados  |
| `source`             | String(50)   | Origem: `nubank_pdf` para novos, `legacy` para dados antigos      |
| `raw_reference_month`| String(7)    | Campo legado — valor original do `reference_month` detectado      |
| `created_at`         | DateTime     |                                                                    |
| `updated_at`         | DateTime     |                                                                    |

**Diferença fundamental entre os campos de data:**

- `transaction.date` = data real da compra (sempre preservada).
- `invoice.cycle_start_date` / `cycle_end_date` = período em que as compras foram feitas para esta fatura.
- `invoice.due_date` = data em que a fatura vence.
- Uma fatura pode ter `cycle_start_date` em março e `due_date` em abril — estas são datas distintas e não devem ser confundidas.

**Regras de invoice:**

- Toda transaction de fatura (`card_id` preenchido) deve ter `invoice_id`.
- Dados legados importados antes da criação da tabela têm invoices com `due_date = null` e `source = "legacy"`.
- Não inventar datas para dados históricos: se não existe informação confiável, deixar null.
- Um usuário nunca pode acessar invoice de outro usuário.
- Uma invoice de um cartão não pode aparecer em outro cartão.

## Cartões de Crédito

Model: `app/models/credit_card.py::CreditCard`.

Campos: `id`, `user_id`, `name`, `institution`, `closing_day`, `due_day`, `created_at`, `updated_at`.

Regras:

- Todas as rotas de cartão usam `get_current_user`.
- O backend valida que o cartão pertence ao usuário autenticado antes de retornar, editar, excluir, listar faturas ou importar transações vinculadas.
- `closing_day` e `due_day` devem estar entre 1 e 31.
- `GET /api/cards/{card_id}/invoices` retorna invoices reais da tabela `Invoice`.

### Exclusão de cartão (`DELETE /api/cards/{card_id}`)

- Valida que o cartão pertence ao `user_id` do usuário autenticado (via `_get_user_card`).
- Se cartão não encontrado ou de outro usuário: retorna `404`.
- Limpa `invoice_id` das transactions (FK SET NULL), depois exclui transactions e invoices do cartão.
- Exclui o cartão.
- Commita a operação. SQLAlchemy garante que, em caso de erro no commit, nenhuma exclusão parcial persiste.
- Não exclui categorias.
- Não afeta transações ou cartões de outros usuários.
- Retorna `{ "deleted": true }` em caso de sucesso.

## Categorias Manuais

Model: `app/models/category.py::Category`.

Campos:

- `id`
- `user_id`
- `name`
- `scope`
- `color` — legado, mantido para compatibilidade. Não é o principal identificador visual.
- `icon` — chave de ícone (ex: `"shopping-cart"`, `"utensils"`, `"car"`). Nullable. Migration `a1b2c3d4e5f6`.
- `created_at`
- `updated_at`

Regras:

- Neste momento só existe `scope = credit_card`.
- Categorias são sempre filtradas por `user_id`.
- Importação de fatura aceita `category_id` por transação, valida que a categoria pertence ao usuário e salva também `category` com o nome atual para compatibilidade.
- Não existe categorização automática, regra por descrição, sugestão inteligente ou IA.
- `PATCH /api/categories/{id}` aceita `name`, `color` e `icon`. Atualiza apenas os campos enviados.
- `icon` é a representação visual principal. `color` é mantido como legado.
- O backend armazena apenas a chave do ícone (string). Ex: `"shopping-cart"`, não componente visual.
- Para `icon`: valor `null` = não altera; string vazia = salva como `null` (limpeza explícita).
- `PATCH /api/categories/{id}` valida que a categoria pertence ao `user_id` autenticado.

## Compras Parceladas (Classificação Sistêmica)

Compras parceladas **não** são uma categoria manual. São uma classificação derivada dos campos `installment_current` e `installment_total` na `Transaction`.

### Como são identificadas

O parser `FaturaCartaoNubankParser` (`app/parsers/fatura_nubank.py`) extrai o padrão via `_INSTALLMENT_RE`:

```
"<Descrição> - Parcela <X>/<Y>"  →  installment_current=X, installment_total=Y
```

Ao fazer match, o sufixo "- Parcela X/Y" é removido da `description`. `raw_description` preserva o texto original.

Critério de compra parcelada: `installment_current IS NOT NULL AND installment_total IS NOT NULL AND installment_total > 1`.

### Campos na Transaction

| Campo | Tipo | Descrição |
|---|---|---|
| `installment_current` | Integer nullable | Número da parcela atual (ex: 2) |
| `installment_total` | Integer nullable | Total de parcelas (ex: 4) |

`is_installment` não é persistido — é derivado no frontend.

### Relação com category_id

"Compras parceladas" é uma **classificação sistêmica**, independente da categoria manual.

- `category_id` manual **não é sobrescrito** pela identificação de parcelas.
- Uma transaction pode ter `installment_current=2, installment_total=4` **e** `category_id=3` simultaneamente.
- Não existe categoria `"Compras parceladas"` na tabela `categories`. Não deve ser criada automaticamente.

### Cálculo de parcelas futuras estimadas

```
parcelas_futuras = installment_total - installment_current
valor_futuro_estimado = abs(amount) * parcelas_futuras
```

Este cálculo é uma estimativa. **Não criar transações futuras automaticamente.** `invoice.total_amount` não é alterado por parcelas.

### Recategorização de transactions (`PATCH /api/transactions/{id}`)

Aceita `category_id` para alterar a categoria de uma transaction já importada.

- `category_id = 0` remove a categoria (seta `category_id = null` e `category = null`).
- `category_id` deve pertencer ao `user_id` autenticado e ter `scope = credit_card`.
- `installment_current`, `installment_total`, `card_id`, `invoice_id` **nunca** são alterados por este endpoint.

## Importação de Fatura por Cartão

### Upload (`POST /api/upload`)

Continua apenas fazendo preview (não persiste). Para fatura Nubank, retorna:

- `summary`
- `detected_reference_month` — igual a `invoice_metadata.due_month` quando extraído.
- `invoice_metadata` — metadados reais da fatura (novos):
  - `invoice_label_month` (ex: `"abril"`)
  - `due_date` — data de vencimento (`YYYY-MM-DD`) extraída do PDF
  - `due_month` — derivado de `due_date`
  - `cycle_start_date` — início do período vigente
  - `cycle_end_date` — fim do período vigente
  - `issue_date` — data de emissão/envio
  - `closing_date` — data de fechamento (= `cycle_end_date`)
  - `total_amount` — "Total a pagar" extraído do PDF
  - `source` — `"nubank_pdf"`

### Importação (`POST /api/import`)

Aceita:

- `card_id` — **obrigatório** para fatura de cartão
- `invoice` — objeto com metadados da fatura (obrigatório quando disponível):
  - `due_month` — **obrigatório** — mês de pagamento da fatura
  - `due_date`, `cycle_start_date`, `cycle_end_date`, `issue_date`, `closing_date`, `total_amount`, `source`
- `reference_month` — legado; usado como fallback para `due_month` quando `invoice` não é enviado
- `transactions[].category_id`

**Fluxo no import (`is_card_invoice = True`):**

1. Valida `card_id` — retorna `400` se ausente, `404` se não encontrado ou de outro usuário.
2. Determina `due_month`: prioriza `invoice.due_month` → `reference_month` → frequência de `date` (fallback legado).
3. Chama `_get_or_create_invoice` — cria ou atualiza invoice com os metadados enviados.
4. Salva cada transaction com `card_id`, `invoice_id`, `reference_month` (legado), `category_id` e `is_payment`.
5. Preserva `date` (data real da compra) sem alteração.
6. Retorna `{ imported, skipped, card_id, invoice_id, due_month }`.

**Regras de vínculo:**

- Toda transaction de cartão importada recebe `invoice_id`.
- `reference_month` e `billing_month` continuam sendo salvos para compatibilidade com dados antigos.
- `transaction.date` **nunca** é usada como fonte principal para determinar a fatura.

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

- O **total oficial a pagar do PDF** está em `invoice_metadata.total_amount` / `Invoice.total_amount` (`_pick_invoice_total_amount` no parser). Isso **não** é derivado de `summary.total_invoice`.
- `amount < 0` é gasto de cartão.
- `amount > 0` é crédito, estorno, cashback ou entrada.
- `total_invoice` é a **soma dos gastos brutos** nas transações parseadas: `sum(abs(amount) for amount < 0)`. Pode diferir do “Total a pagar” do PDF (IOF, ajustes no resumo, créditos já descontados pelo banco, lançamentos não extraídos como linha, etc.). Use como conferência de lançamentos, não como substituto do `total_amount`.
- `total_credits` soma apenas entradas/créditos: `sum(amount for amount > 0)`.
- `total_credits` é retrocompatível e inclui todos os créditos: pagamento da fatura anterior mais estornos/reembolsos.
- Pagamento da fatura anterior é detectado pelo parser com descrições no padrão `Pagamento em DD/MM`, `Pagamento recebido em DD/MM`, `Pagamento em DD MMM` ou `Pagamento recebido em DD MMM`.
- `payment_amount` soma créditos marcados com `is_payment=True`.
- `payment_description` usa a descrição do primeiro pagamento encontrado, ou string vazia.
- `total_other_credits` soma créditos que não são pagamento.
- `total_other_credits_count` conta créditos que não são pagamento.
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
- `payment_amount: float`
- `payment_description: str`
- `total_other_credits: float`
- `total_other_credits_count: int`
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
- `payment_amount`: valor positivo do lançamento `Pagamento em 11 FEV`, quando presente na fatura parseada
- `payment_description`: `Pagamento em 11 FEV`, quando presente na fatura parseada
- `total_other_credits`: créditos sem pagamento da fatura anterior
- `total_other_credits_count`: quantidade de créditos sem pagamento da fatura anterior
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

Referência detalhada da extração de PDF da **fatura de cartão Nubank** (campos extraídos, regex, limitações): [docs/FATURA-NUBANK-PDF.md](docs/FATURA-NUBANK-PDF.md).

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
- `transactions.is_payment` persiste a identificação do pagamento da fatura anterior.
- `credit_cards` persiste cartões cadastrados pelo usuário.
- `categories` persiste categorias manuais do usuário.
- `transactions.card_id` vincula lançamentos de cartão a um cartão cadastrado.
- `transactions.invoice_id` — âncora principal da fatura. Adicionado pela migration `e5f6a7b8c9d0`.
- `transactions.reference_month` — legado, mantido para compatibilidade.
- `invoices` — tabela de faturas reais criada pela migration `e5f6a7b8c9d0`. Inclui migração automática de dados antigos (agrupa por `user_id + card_id + reference_month`).
- Migration `b8a741a98760` cria `credit_cards`, `categories` e adiciona `card_id`, `reference_month`, `category_id` em `transactions`.
- Migration `e5f6a7b8c9d0` cria `invoices`, adiciona `invoice_id` em `transactions` e migra dados antigos.
- Migration `a1b2c3d4e5f6` adiciona coluna `icon` (nullable String(50)) na tabela `categories`.

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
