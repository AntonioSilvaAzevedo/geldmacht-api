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
- `GET /api/cards/{card_id}/invoices`: lista invoices reais (`Invoice` table) com totais calculados das transactions. Usado para navegação entre faturas e listagem completa.
- `GET /api/cards/{card_id}/invoices/{invoice_id}`: retorna fatura completa (metadados + transactions + summary).
- `GET /api/cards/{card_id}/dashboard`: visão geral agregada do cartão — última fatura, média mensal, maior fatura, parcelas futuras estimadas, evolução, top categorias e faturas recentes.
- `GET /api/cards/{card_id}/invoices-by-month/{due_month}`: busca invoice por `due_month` (compat. legada com `/cartao/[cardId]/[anoMes]`).
- `GET /api/categories?scope=credit_card[&card_id=N]`: lista categorias manuais do usuário. Quando `card_id` é informado, retorna categorias globais (`card_id=null`) + específicas daquele cartão.
- `POST /api/categories`: cria categoria/subcategoria manual. Aceita `name`, `scope=credit_card`, `icon`, `color`, `card_id`, `parent_id`, `invoice_budget_limit`.
- `PATCH /api/categories/{category_id}`: edita categoria. Sentinelas: `card_id=0` torna global; `parent_id=0` torna categoria principal; `invoice_budget_limit=0` remove o limite.
- `DELETE /api/categories/{category_id}`: remove categoria e suas subcategorias (cascade), desvinculando transações que usavam qualquer um dos `category_id` removidos.
- `GET /api/dashboard/monthly`: agrega transações por mês para o dashboard anual.
- `GET /api/release-notes/pending`: retorna a release note mais recente com `show_modal=true` que o usuário ainda não visualizou. `204 No Content` quando não há nenhuma pendente.
- `POST /api/release-notes/{id}/mark-seen`: registra que o usuário viu a release note. Idempotente — chamadas repetidas não duplicam registro.

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
- `scope` — apenas `credit_card` por enquanto. Obrigatório.
- `color` — legado, mantido para compatibilidade. Não é o principal identificador visual.
- `icon` — chave de ícone (ex: `"shopping-cart"`, `"utensils"`, `"car"`). Nullable. Migration `a1b2c3d4e5f6`.
- `card_id` — FK para `credit_cards`, **nullable**. `null` = categoria global (todos os cartões); preenchido = exclusiva do cartão. Migration `c1d2e3f4a5b6`. `ON DELETE SET NULL`.
- `parent_id` — FK self-referencial para `categories`, nullable. `null` = categoria principal; preenchido = subcategoria. Profundidade máxima de 1 nível (validado no app). `ON DELETE CASCADE`. Migration `c1d2e3f4a5b6`.
- `invoice_budget_limit` — Float, nullable. Limite de gasto **por fatura**. Quando informado deve ser `> 0`. Não bloqueia lançamentos; é usado apenas para indicador visual no frontend. Migration `c1d2e3f4a5b6`.
- `created_at`
- `updated_at`

Regras gerais:

- Neste momento só existe `scope = credit_card`.
- Categorias são sempre filtradas por `user_id`.
- Importação de fatura aceita `category_id` por transação, valida que a categoria pertence ao usuário e salva também `category` com o nome atual para compatibilidade.
- Não existe categorização automática, regra por descrição, sugestão inteligente ou IA.
- `PATCH /api/categories/{id}` aceita `name`, `color`, `icon`, `card_id`, `parent_id`, `invoice_budget_limit`. Atualiza apenas os campos enviados.
- `icon` é a representação visual principal. `color` é mantido como legado.
- O backend armazena apenas a chave do ícone (string). Ex: `"shopping-cart"`, não componente visual.
- Para `icon`: valor `null` = não altera; string vazia = salva como `null` (limpeza explícita).
- `PATCH /api/categories/{id}` valida que a categoria pertence ao `user_id` autenticado.

### Aplicação por cartão (`card_id`)

- `card_id = null` → categoria global. Aparece em qualquer fatura.
- `card_id = N` → categoria exclusiva do cartão `N`. Só aparece em faturas desse cartão.
- Não há relação muitos-para-muitos. A regra é: global OU um cartão específico.
- `POST /api/categories` valida que o cartão pertence ao usuário autenticado. Cartão de outro usuário → `404`.
- `PATCH` aceita sentinela: `card_id = 0` limpa o vínculo (vira global); `card_id = N` define o cartão; `card_id` ausente/`null` = não altera.
- Filtro: `GET /api/categories?scope=credit_card&card_id=N` retorna **categorias globais (`card_id = null`) + categorias específicas do cartão N**. Categorias de outro cartão são excluídas. Se `card_id` não pertence ao usuário, retorna `404`.

### Subcategorias (`parent_id`)

- `parent_id = null` → categoria principal.
- `parent_id = N` → subcategoria filha da categoria `N`.
- **Profundidade máxima 1**: subcategoria não pode ter subcategoria. `POST /categories` com `parent_id` apontando para uma subcategoria retorna `400`.
- Categoria pai deve pertencer ao mesmo `user_id`. Senão `404`.
- Categoria pai deve ter o mesmo `scope`. Se diferente, `400`.
- Subcategoria respeita o `card_id` da categoria pai:
  - Se a pai é global (`card_id = null`), a sub pode ser global ou definir um `card_id` próprio.
  - Se a pai é específica (`card_id = N`), a sub só pode ter `card_id = N` ou herdar (não enviar). Divergência → `400`.
- Quando `card_id` não é enviado e a pai é específica, a sub herda o `card_id` da pai automaticamente.
- Não permite ciclo: `parent_id` não pode ser igual ao `id` da própria categoria. Verificado no `PATCH`.
- Não é permitido transformar uma categoria em subcategoria se ela já tem filhas. Validação no `PATCH` retorna `400`.
- Exclusão (`DELETE`) usa cascade: ao remover a categoria pai, suas subcategorias também são removidas e todas as transactions vinculadas têm `category_id` zerado.

### Limite de gasto por fatura (`invoice_budget_limit`)

- Opcional (nullable). Quando informado, deve ser `> 0`. Validação Pydantic + checagem no endpoint.
- Apenas visual. **Não bloqueia lançamentos**, **não altera** `invoice.total_amount` nem `transaction.amount`.
- Subcategoria pode ter limite próprio. Não é inferido do limite da pai.
- `PATCH` aceita sentinela: `invoice_budget_limit = 0` remove o limite; `> 0` define; ausente/`null` = não altera.
- O valor permite o frontend renderizar a barra de progresso (`gasto / limite`) na tela da fatura.

### Endpoints (`/api/categories`)

- `GET /api/categories?scope=credit_card[&card_id=N]` — lista categorias do usuário, opcionalmente filtradas por cartão (mostra globais + específicas do cartão).
- `POST /api/categories` — cria categoria/subcategoria. Valida `card_id`, `parent_id` e `invoice_budget_limit`.
- `PATCH /api/categories/{id}` — edita campos enviados. Sentinelas explicadas acima.
- `DELETE /api/categories/{id}` — exclui categoria + subcategorias + zera `category_id` das transactions afetadas.

### Validação de `category_id` em transações pelo cartão

- **`POST /api/import`**: ao importar fatura, se a transaction trouxer `category_id` cuja categoria tem `card_id` específico diferente do cartão da fatura, retorna `400 — Categoria não é aplicável a este cartão.` Categorias globais (`card_id = null`) são sempre aceitas.
- **`PATCH /api/transactions/{id}`**: idem — `category_id` apontando para categoria de outro cartão retorna `400`.
- Continua valendo o bloqueio de categoria em lançamentos sistêmicos (parcelas e pagamentos).

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

## Bloqueio de Categoria em Lançamentos Sistêmicos

Lançamentos sistêmicos não recebem `category_id` manual. São considerados sistêmicos:

1. **Compra parcelada** — `installment_current IS NOT NULL AND installment_total IS NOT NULL AND installment_total > 1`.
2. **Pagamento da fatura** — `is_payment = True` (detectado pelo parser pelos padrões `Pagamento em DD MMM`, `Pagamento em DD/MM`, `Pagamento recebido em DD MMM`, etc.).

### Comportamento por endpoint

**`POST /api/import`** — *normaliza silenciosamente.* Se o frontend enviar `category_id` para um lançamento sistêmico, o backend salva com `category_id = null` e `category = null`. Não retorna erro — evita quebrar fluxo de importação.

**`PATCH /api/transactions/{id}`** — *rejeita explicitamente.* Tentar definir `category_id` (qualquer valor, inclusive `0`) em uma transaction sistêmica retorna:

```http
400 Bad Request
{
  "detail": "Este lançamento é sistêmico e não pode ser categorizado manualmente."
}
```

A descrição (`description`) continua editável em sistêmicos. Apenas `category_id`/`category` são bloqueados.

### Não criar categorias sistêmicas

Não existem categorias `"Compras parceladas"` ou `"Pagamento da fatura"` na tabela `categories` — essas são classificações puramente visuais derivadas dos campos da `Transaction`. Não devem ser criadas automaticamente.

## Dashboard do Cartão

`GET /api/cards/{card_id}/dashboard` retorna um agregado para a página `/cartao/[cardId]`.

Resposta (`CardDashboardResponse`):

| Campo | Descrição |
|---|---|
| `card_id` | ID do cartão |
| `invoice_count` | Total de faturas do cartão |
| `latest_invoice` | Fatura mais recente (`InvoiceMini`) |
| `monthly_average` | Média do `total_amount` (ou `computed_total`) das faturas |
| `highest_invoice` | Fatura com maior `total_amount` |
| `future_installments_total` | Soma de `abs(amount) * (installment_total - installment_current)` para parcelas com `remaining > 0` da **última fatura** |
| `invoice_evolution` | Lista cronológica crescente das últimas 12 faturas (para gráfico) |
| `top_categories` | Top 5 categorias por gasto absoluto (`amount < 0`) considerando todas as faturas do cartão |
| `recent_invoices` | Últimas 5 faturas (ordem cronológica decrescente) |

`InvoiceMini`: `{ id, due_month, due_date, total_amount, computed_total }`.
`TopCategoryItem`: `{ category_id, name, icon, total }`.

Regras:

- Valida que `card_id` pertence ao usuário autenticado (`_get_user_card`). Caso contrário, `404`.
- Categorias sistêmicas não aparecem em `top_categories` porque parcelas e pagamentos têm `category_id = null`.
- Se não houver faturas, retorna estrutura com `invoice_count = 0`, `latest_invoice = null`, `highest_invoice = null`, `monthly_average = 0`, `future_installments_total = 0`, listas vazias.

## Release Notes / Notas de Atualização

Models: `app/models/release_note.py::ReleaseNote` e `UserReleaseNoteView`.

### `ReleaseNote`

| Campo         | Tipo          | Descrição                                                        |
|---------------|---------------|------------------------------------------------------------------|
| `id`          | Integer       | PK                                                               |
| `version`     | String(40)    | **Único.** Ex: `"0.3.0"`. Mesma versão exibida na sidebar.       |
| `title`       | String(160)   | Título amigável da release.                                      |
| `description` | Text nullable | Descrição curta do release. Linguagem simples.                   |
| `items_json`  | Text          | Lista de tópicos serializada como JSON string (SQLite-friendly). |
| `show_modal`  | Boolean       | Default `True`. Quando `False`, não aparece em `pending`.        |
| `released_at` | DateTime      | Data de release (opcional).                                      |
| `created_at`  | DateTime      |                                                                  |
| `updated_at`  | DateTime      |                                                                  |

`items_json` é desserializado em `items: list[str]` no schema `ReleaseNoteOut`. Se o JSON for inválido, o endpoint retorna lista vazia em vez de erro.

### `UserReleaseNoteView`

Registro de visualização. Garante exibição única do modal por usuário/versão.

| Campo             | Tipo                            | Descrição                                  |
|-------------------|---------------------------------|--------------------------------------------|
| `id`              | Integer                         | PK                                         |
| `user_id`         | FK `users.id` (CASCADE)         | Quem visualizou                            |
| `release_note_id` | FK `release_notes.id` (CASCADE) | Qual release foi visualizada               |
| `version`         | String(40)                      | Snapshot da versão (denormalizado)         |
| `seen_at`         | DateTime                        | Momento da visualização                    |

**Constraint única:** `uq_user_release_view (user_id, release_note_id)` — impede duplicidade.

### Endpoints

- `GET /api/release-notes/pending`
  - Retorna a release note mais recente com `show_modal=True` que o usuário ainda **não** visualizou.
  - Ordem: `released_at desc nullslast`, depois `created_at desc`, depois `id desc`.
  - Quando não há nenhuma pendente, retorna **`204 No Content`**.
  - Requer autenticação.

- `POST /api/release-notes/{release_note_id}/mark-seen`
  - Cria `UserReleaseNoteView` se ainda não existir; **idempotente**.
  - `404` quando a release note não existe.
  - Retorna `{ "success": true, "seen": true }`.
  - Requer autenticação.

### Regra de exibição única

- Só são pendentes release notes com `show_modal=True`.
- Após `mark-seen`, o usuário não recebe mais aquela versão como pendente.
- Quando uma versão nova é cadastrada (`show_modal=True`), volta a aparecer como pendente para usuários que ainda não a visualizaram.
- `show_modal=False` nunca dispara modal — usado para ajustes internos / correções pequenas que não devem ser comunicadas ao usuário.

### Cadastro de release notes (seed)

A fonte oficial é a lista `RELEASE_NOTES` em `app/services/release_notes_seed.py`. A função `seed_release_notes()` é chamada no startup do FastAPI (`@app.on_event("startup")` em `app/main.py`):

- **Idempotente**: só insere versões cuja `version` ainda não existe no banco.
- Atualiza campos de texto (`title`, `description`, `items_json`, `show_modal`, `released_at`) quando a versão já existe — útil para corrigir typos sem migration.
- Não há tela administrativa — para adicionar uma nota, edite `RELEASE_NOTES` (mais nova primeiro) e faça redeploy.

### Como adicionar release notes em prompts/features futuros

Sempre que um prompt entregar mudanças relevantes para o usuário final:

1. Adicione um dicionário no topo de `RELEASE_NOTES` com `version` nova (alinhada ao `frontend/package.json`).
2. Use linguagem simples — **não** mencione `schema`, `migration`, `endpoint`, `refactor`, `card_id`, `parent_id`, `backend`, `frontend` ou outros termos técnicos.
3. Cada item deve ser uma frase curta e útil para o usuário.
4. `show_modal=True` é o padrão. Use `False` apenas quando a versão for ajuste interno/correção pequena.
5. Atualize `frontend/package.json#version` para a mesma versão.
6. Opcional: defina `released_at` ISO para manter ordenação coerente entre versões.

Sugestão de bloco para usar nos próximos prompts:

```
RELEASE NOTES:
  - Atualizar ou criar release note da versão atual.
  - Usar linguagem simples.
  - Listar apenas mudanças úteis para o usuário final.
  - Evitar detalhes técnicos.
  - Definir show_modal = true, salvo quando explicitamente solicitado o contrário.
```

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
- Migration `c1d2e3f4a5b6` adiciona em `categories`: `card_id` (FK `credit_cards`, nullable, ON DELETE SET NULL), `parent_id` (self-FK, nullable, ON DELETE CASCADE) e `invoice_budget_limit` (Float, nullable). Índices em `card_id` e `parent_id`.
- Migration `d2e3f4a5b6c7` cria `release_notes` (notas de atualização por versão) e `user_release_note_views` (registro de visualização por usuário, com unique `user_id + release_note_id`).

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
