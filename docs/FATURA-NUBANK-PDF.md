# Extração da fatura de cartão Nubank (PDF)

Documentação técnica do parser **`FaturaCartaoNubank`** (`app/parsers/fatura_nubank.py`), usado quando o arquivo enviado a `POST /api/upload` é um PDF reconhecido como fatura do cartão de crédito Nubank.

---

## Visão geral

1. O PDF é lido com **pdfplumber** (`page.extract_text`).
2. O backend **detecta automaticamente** se o arquivo é uma fatura Nubank (não pelo nome do arquivo, mas pelo texto extraído).
3. Para cada linha que casa com o padrão de **transação** (`DD MMM … valor`), monta um dicionário compatível com `ParsedTransaction`.
4. O nome do parser na API é derivado da classe: `faturacartaonubank` (`FaturaCartaoNubankParser` → normalização em `upload.py`).
5. Nessa resposta o backend também pode incluir:
   - `detected_reference_month` (`YYYY-MM`) — quando o cabeçalho da fatura permitir inferir;
   - `summary` — resumo calculado apenas para esse parser (`InvoiceSummary`), via `calculate_invoice_summary`.

Nada é persistido no `POST /api/upload`: só preview. A gravação ocorre no `POST /api/import` após confirmação no frontend.

---

## Como o PDF é identificado (`can_parse`)

- Abre as **3 primeiras páginas** e concatena o texto em minúsculas.
- Exige uma linha compatível com o padrão exclusivo da fatura de cartão:
  - `fatura\s+\d{2}\s+[a-z]{3}\s+\d{4}\s+emiss[aã]o`
- Em outras palavras: texto no formato **`FATURA DD MMM YYYY EMISSÃO …`** (ex.: `FATURA 11 MAR 2026 EMISSÃO E ENVIO …`).

Objetivo: diferenciar a **fatura do cartão** de outros PDFs Nubank (extrato PF/PJ), que aparecem antes na lista global de parsers em `app/parsers/__init__.py`.

---

## Extração do texto (`parse`)

- Percorre **todas** as páginas.
- Para cada página: `extract_text(x_tolerance=3, y_tolerance=3)` — tolerâncias extras ajudam a juntar palavras que o PDF pode fragmentar.
- Concatena todas as páginas com quebras de linha e repassa para `_parse_text`.

### Valor total oficial (`invoice_metadata.total_amount`)

Função **`_pick_invoice_total_amount`** atua sobre o mesmo texto concatenado usado em `extract_invoice_metadata`:

1. Encontra todas as ocorrências de **`Total a pagar R$ …`** (`_TOTAL_RE`).
2. Para cada ocorrência, monta contexto só **até o fim da linha** da ocorrência, com lookback de até 400 caracteres. **Não** inclui texto abaixo dessa linha: do contrário, uma seção “Próxima fatura” mais adiante no PDF pode invalidar erroneamente um total válido do resumo da fatura atual.
3. Descarta ocorrências cuja janela case com **`_TOTAL_CONTEXT_SKIP`** (próxima fatura, saldo em aberto total, pagamento mínimo / parcelamento mínimo / composição do pagamento mínimo).
4. Se sobrar ao menos uma válida, usa **a última** — em layouts reais aparecem dois ou mais “Total a pagar” com valores diferentes (resumo parcial vs conferência final).
5. Se todas forem filtradas, fallback: **última** ocorrência bruta de `_TOTAL_RE`.
6. Sem nenhuma ocorrência de “total a pagar”, fallback: linha de cabeçalho **`no valor de R$ …`** (`_HEADER_VALOR_NO_RE`).

Ou seja: o total oficial **não** vem de “Total de compras de todos os cartões” (regex distinta) nem da soma das transações parseadas.

Para diagnóstico local (comparar PDF vs lançamentos vs summary), use **`python scripts/diagnose_nubank_totals.py arquivo.pdf`** no repositório da API (PDF local, não versionado).

---

## Dados tirados diretamente do PDF

### Cabeçalho da fatura

Regex: `FATURA\s+\d{2}\s+([A-Z]{3})\s+(\d{4})`.

- **Ano da fatura** (`year`): segundo grupo da regex (YYYY).
- **`detected_reference_month`**: método `extract_reference_month` — string `YYYY-MM` montada com o ano do cabeçalho e o mês textual do primeiro grupo (`JAN`…`DEZ`).
- Se o cabeçalho não for encontrado ao extrair ano, `_extract_year` usa **ano atual** como fallback (apenas datas das linhas de transação).

### Cada linha de transação (quando válida)

Padrão de linha (`_TX_LINE_RE`):

```text
^(\d{2})\s+([A-Z]{3})\s+(.+?)\s+([−\-]?R\$\s*[\d.]+,\d{2})$
```

Ou seja, no mínimo:

| Campo | Origem |
|-------|--------|
| **Dia** | Primeiro grupo (`DD`) |
| **Mês** | Segundo grupo (`MMM` — JAN, FEV, MAR, …) combinado com o **ano do cabeçalho** |
| **Descrição** | Terceiro grupo (texto até o valor monetário) |
| **Valor bruto na linha** | Quarto grupo (string `R$ …` ou `−R$` / `-R$`) |

Datas inválidas (ex.: 31 num mês com 30 dias) **descartam** a linha.

### Conversão monetária (`_parse_value`)

- Valor parseado como decimal brasileiro (`.` milhar, `,` decimal).
- **Sem** `−` ou `-` antes de `R$` → tratado como **compra / gasto no cartão** → `amount` **negativo** no modelo interno.
- Com `−` (U+2212, minus matemático) ou `-` antes de `R$` → tratado como **crédito** (pagamento recebido, estorno etc.) → `amount` **positivo**.

### Parcelas (`- Parcela X/Y`)

Se a **descrição** terminar com algo como `- Parcela 2/3`:

- `installment_current` = X  
- `installment_total` = Y  
- Essa parte é **removida** da `description` final (fica apenas o texto antes do sufixo).

### Pagamento da fatura (`is_payment`)

`True` quando a descrição casa com algo como:

- `Pagamento em DD/MM` ou `Pagamento em DD MMM`
- `Pagamento recebido em …` (idem)

Usado pelo serviço de **summary** e pela lógica de fatura posteriormente.

---

## Metadados adicionados no backend (não vindos literalmente da linha)

Chamada `classify_transaction(description)` em `app/categorization/categorizer.py`:

- `is_internal_transfer` — heurística sobre transferências / contas próprias (lista de padrões em `rules`).
- `category`: sempre `None` aqui (categoria manual é escolha do usuário na revisão).

Ou seja: **o PDF não traz categorias persistíveis**; só descrições e valores.

---

## Linhas ignoradas (`_SKIP_RE`)

Trechos que não viram transação, incluindo (lista não exaustiva do regex):

- Nome do titular típico do PDF usado nos testes/fixtures;
- Cabeçalhos repetidos (`FATURA …`, intervalo “TRANSAÇÕES DE …”);
- Linhas só em **USD** e linhas **“Conversão: USD…”** (câmbio);
- Paginação (“5 de 8”);
- Rodapés (regulações, SAC, SCR, etc.);
- Alguns trechos de juros / pagamento mínimo na fatura estática.

**Importante:** se o layout oficial do PDF mudar, linhas válidas podem passar a ser ignoradas erroneamente ou o padrão de transação pode deixar de casar — aí o parser precisa ser ajustado.

---

## Objeto gerado por transação (`dict` → `ParsedTransaction`)

Para cada linha válida, o parser devolve algo na linha de:

```text
date              # ISO date (yyyy-mm-dd), ano do cabeçalho da fatura
description       # texto normalizado (sem sufixo de parcela, se havia)
raw_description   # linha inteira original do PDF
amount            # float (negativo = gasto, positivo = crédito)
account           # sempre "nubank_cartao"
installment_*     # opcionais
is_payment        # bool
is_internal_transfer
category
category_group
```

Esses dicts são validados pelo Pydantic `ParsedTransaction` no `upload`. Entradas inválidas são **descartadas** com log (`Transação ignorada`).

---

## Resposta HTTP do upload específica deste parser

Quando `parser_used == "faturacartaonubank"`:

- `transactions`: lista conforme acima.
- `detected_reference_month`: opcional (`YYYY-MM` do cabeçalho `FATURA …`).
- `summary`: métricas agregadas (total da fatura, créditos, maior gasto, parcelas, pagamento reconhecido, etc.) via `calculate_invoice_summary`.

---

## Testes automatizados

- `tests/test_fatura_nubank.py`: exemplos sintéticos (`_parse_text` / mocks) para `is_payment`, metadados e totais repetidos na fatura.
- Se existir **`tests/Nubank_2026-05-11.pdf`**, roda **`test_nubank_2026_05_11_pdf_de_para`**: garante entre outras coisas `total_amount == 5983.28`, datas de ciclo e contagem de lançamentos. **Ausente:** o teste é ignorado (`skip`). Evite commitar PDFs com dados sensíveis em forks públicos; em ambiente só seu, a fixture permite regressão contra o arquivo real.

Para comparar totals à mão sem pytest: **`python scripts/diagnose_nubank_totals.py tests/Nubank_2026-05-11.pdf`**.

---

## Arquivos relacionados no repositório

| Arquivo | Papel |
|---------|------|
| `app/parsers/fatura_nubank.py` | Parser PDF |
| `app/parsers/__init__.py` | Registro na ordem de detecção |
| `app/api/upload.py` | Detecção, parse, summary e `detected_reference_month` |
| `app/services/summary_service.py` | `calculate_invoice_summary` |
| `app/categorization/categorizer.py` | `classify_transaction` |
| `app/schemas/transaction.py` | Contrato `ParsedTransaction` / `UploadResponse` |

---

## Limitações atuais (importante saber para manutenção)

- Depende inteiramente da **forma do texto extraído** pelo pdfplumber; OCR ou PDF escaneado sem camada de texto não funciona.
- Padrões de cabeçalho e nome do titular no `_SKIP_RE` podem ser **brittle** entre versões diferentes do modelo de fatura ou titulares distintos.
- Compras em moeda estrangeira: apenas a estrutura de linha em BRL casa; linhas só em USD são ignoradas conforme `_SKIP_RE` (podem não refletir o lançamento em reais até que exista tratamento específico).
