"""
Parser da fatura do cartão de crédito Nubank.

Formato extraído via pdfplumber:
─────────────────────────────────────────────────────
Cabeçalho de seção (repetido por página):
  ANTONIO CARLOS SILVA DE AZEVEDO
  FATURA 11 MAR 2026 EMISSÃO E ENVIO 04 MAR 2026
  TRANSAÇÕES DE 04 FEV A 04 MAR

Linha de transação:
  DD MMM Descrição                         R$ X.XXX,XX   ← compra (negativo)
  DD MMM Estorno / Ajuste a crédito       −R$ X.XXX,XX   ← crédito (positivo, usa −)
  DD MMM Pagamento em DD/MM               −R$ X.XXX,XX   ← pagamento da fatura anterior

Linhas a ignorar:
  USD XX.XX                        ← conversão de moeda
  Conversão: USD 1 = R$ X,XX      ← taxa de câmbio

Regras:
  • Ano extraído do cabeçalho "FATURA DD MMM YYYY"
  • Sinal: R$ = negativo (compra), −R$ (U+2212) ou -R$ = positivo (crédito/estorno)
  • Account key: "nubank_cartao"
"""
import io
import re
import logging
from datetime import date

import pdfplumber

from .base import BaseParser
from ..categorization.categorizer import classify_transaction

logger = logging.getLogger(__name__)

# ── Mapeamento de meses ───────────────────────────────────────────────────────
_MONTH_MAP = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4,
    "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8,
    "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

_MONTH_LABELS_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

# ── Cabeçalho "FATURA DD MMM YYYY" — extrai o ano da fatura ──────────────────
_FATURA_HEADER_RE = re.compile(
    r"FATURA\s+\d{2}\s+([A-Z]{3})\s+(\d{4})", re.IGNORECASE
)

# ── Cabeçalho completo: "FATURA DD MMM YYYY EMISSÃO E ENVIO DD MMM YYYY" ─────
_FATURA_FULL_RE = re.compile(
    r"FATURA\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{4})", re.IGNORECASE
)

# ── "EMISSÃO E ENVIO DD MMM YYYY" — data de emissão ─────────────────────────
_ISSUE_DATE_RE = re.compile(
    r"emiss[aã]o\s+[Ee]\s+envio\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{4})", re.IGNORECASE
)

# ── "Data de vencimento: DD ABR 2026" — vencimento explícito ─────────────────
_DUE_DATE_RE = re.compile(
    r"data\s+de\s+vencimento[:\s]+(\d{1,2})\s+([A-Z]{3})\s+(\d{4})", re.IGNORECASE
)

# ── "Período vigente: 04 MAR a 04 ABR" ───────────────────────────────────────
_PERIOD_RE = re.compile(
    r"per[íi]odo\s+vigente[:\s]+(\d{1,2})\s+([A-Z]{3})\s+[Aa]\s+(\d{1,2})\s+([A-Z]{3})",
    re.IGNORECASE,
)

# ── "TRANSAÇÕES DE 04 FEV A 04 MAR" (cabeçalho repetido por página) ──────────
_PERIOD_ALT_RE = re.compile(
    r"transa[çc][oõ]es\s+de\s+(\d{1,2})\s+([A-Z]{3})\s+[Aa]\s+(\d{1,2})\s+([A-Z]{3})",
    re.IGNORECASE,
)

# ── "Total a pagar R$ 12.542,08" ─────────────────────────────────────────────
# Pode aparecer mais de uma vez no PDF (ex.: resumo x detalhes). Preferimos a
# última ocorrência com contexto de fatura atual, ignorando próximas faturas,
# pagamento mínimo e saldos externos.
_TOTAL_RE = re.compile(
    r"total\s+a\s+pagar\s+R\$\s*([\d.]+,\d{2})", re.IGNORECASE
)

_TOTAL_CONTEXT_SKIP = re.compile(
    r"""
      pr[oó]xima\s+fatura
    | saldo\s+em\s+aberto\s+total
    | pagamento\s+m[íi]nimo
    | parcelamento\s+m[íi]nimo
    | composi[çc][aã]o\s+do\s+pagamento
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Cabeçalho: "... no valor de R$ 12.542,08" (menos confiável que "total a pagar")
_HEADER_VALOR_NO_RE = re.compile(
    r"no\s+valor\s+de\s+R\$\s*([\d.]+,\d{2})", re.IGNORECASE
)


def _parse_brl_capture(group1: str) -> float | None:
    raw = group1.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _pick_invoice_total_amount(text: str) -> float | None:
    """
    Valor oficial do PDF para `invoice_metadata.total_amount`.

    1. Todas as ocorrências de "Total a pagar R$ ...", descartando contexto de
       próxima fatura / saldo em aberto total / parcelamento ou pagamento mínimo.
       Usa a **última** sobrevivente — em faturas reais há subtotais com o mesmo
       texto onde o menor valor não corresponde ao que o usuário deve pagar.
    2. Se nenhuma passar pelo filtro, usa a última ocorrência bruta desse mesmo padrão.
    3. Se não houver "total a pagar", tenta cabeçalho "no valor de R$ ...".
    """
    matches = list(_TOTAL_RE.finditer(text))
    filtered: list[float] = []

    for m in matches:
        value = _parse_brl_capture(m.group(1))
        if value is None:
            continue
        line_begin = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        # Só texto até o fim desta linha (+ lookback). Não olhar adiante: abaixo pode
        # vir "Próxima fatura" e invalidar indevidamente o total da fatura atual.
        win_start = max(0, line_begin - 400)
        window = text[win_start:line_end]
        tl = window.lower()
        if _TOTAL_CONTEXT_SKIP.search(tl):
            continue
        filtered.append(value)

    if filtered:
        return filtered[-1]

    # Fallback sem filtro: última linha literal "total a pagar"
    if matches:
        for m in reversed(matches):
            raw = _parse_brl_capture(m.group(1))
            if raw is not None:
                return raw
        return None

    for m in _HEADER_VALOR_NO_RE.finditer(text):
        v = _parse_brl_capture(m.group(1))
        if v is not None:
            return v
    return None

# ── "Esta é a sua fatura de abril" ────────────────────────────────────────────
_FATURA_LABEL_RE = re.compile(
    r"(?:esta\s+[eé]\s+a\s+sua\s+)?fatura\s+de\s+([a-z\u00e0-\u00fc]+)",
    re.IGNORECASE,
)

# ── Linha de transação: DD MMM Descrição R$ X,XX ─────────────────────────────
# Aceita − (U+2212) ou - como sinal de crédito antes de R$
_TX_LINE_RE = re.compile(
    r"^(\d{2})\s+([A-Z]{3})\s+(.+?)\s+([−\-]?R\$\s*[\d.]+,\d{2})$",
    re.IGNORECASE,
)

# ── Valor monetário com sinal opcional ───────────────────────────────────────
_VALUE_RE = re.compile(r"([−\-]?)R\$\s*([\d.]+,\d{2})", re.IGNORECASE)

# ── Parcela "- Parcela X/Y" embutida na descrição ────────────────────────────
_INSTALLMENT_RE = re.compile(
    r"\s*-\s*Parcela\s+(\d+)/(\d+)\s*$",
    re.IGNORECASE,
)

# ── Pagamento da fatura anterior ─────────────────────────────────────────────
_PAYMENT_RE = re.compile(
    r"Pagamento\s+(recebido\s+)?em\s+(?:\d{2}/\d{2}|\d{2}\s+[A-Z]{3})",
    re.IGNORECASE,
)

# ── Linhas a ignorar completamente ───────────────────────────────────────────
_SKIP_RE = re.compile(
    r"""
      ^antonio\s+carlos\s+silva       # nome do titular
    | ^fatura\s+\d{2}\s+[a-z]{3}     # "FATURA DD MMM YYYY EMISSÃO..."
    | ^transa[çc][oõ]es\s+de\s+\d{2} # "TRANSAÇÕES DE 04 FEV A 04 MAR"
    | ^usd\s+[\d.,]+                  # linha com valor em dólar
    | convers[aã]o:\s+usd             # "Conversão: USD 1 = R$ 5,40"
    | ^\d+\s+de\s+\d+$               # paginação "5 de 8"
    | em\s+cumprimento\s+[àa]\s+regula[çc][aã]o  # rodapé legal
    | sistema\s+de\s+informa[çc][oõ]es\s+de\s+cr[eé]dito  # SCR
    | nu\s+pagamentos                 # entidade jurídica
    | rua\s+capote                    # endereço
    | sac\s+\d{4}                     # SAC
    | ouvidoria                       # ouvidoria
    | juros\s+rotativo                # tabela de juros
    | pagamento\s+m[íi]nimo\s+para    # info de pagamento mínimo
    | composi[çc][aã]o\s+do\s+pagamento  # composição do pagamento mínimo
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_value(value_str: str) -> float:
    """
    Converte string de valor em float.
    '−R$ 3,78' ou '-R$ 3,78' → +3.78 (crédito)
    'R$ 65,73'               → -65.73 (débito — despesa no cartão)
    """
    m = _VALUE_RE.search(value_str)
    if not m:
        return 0.0
    sign_char = m.group(1)  # "−", "-", ou ""
    raw = m.group(2).replace(".", "").replace(",", ".")
    amount = float(raw)
    # Se tem sinal negativo (em-dash ou hífen) = crédito → positivo para o titular
    if sign_char in ("-", "−"):
        return amount
    # Sem sinal = compra → negativo para o titular
    return -amount


class FaturaCartaoNubankParser(BaseParser):
    """
    Parser para a fatura do cartão de crédito Nubank.
    Retorna todos os lançamentos da fatura como transações do cartão.
    """

    ACCOUNT_KEY = "nubank_cartao"
    _IDENTIFIERS = ["fatura", "nubank"]

    # Padrão exclusivo da fatura: "FATURA DD MMM YYYY EMISSÃO E ENVIO"
    _FATURA_CANPARSE_RE = re.compile(
        r"fatura\s+\d{2}\s+[a-z]{3}\s+\d{4}\s+emiss[aã]o",
        re.IGNORECASE,
    )

    def can_parse(self, file_content: bytes) -> bool:
        """
        Retorna True se o PDF for uma fatura do cartão Nubank.
        Requer o cabeçalho exclusivo "FATURA DD MMM YYYY EMISSÃO E ENVIO".
        """
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                if not pdf.pages:
                    return False
                sample = ""
                for page in pdf.pages[:3]:
                    sample += (page.extract_text() or "").lower()
            return bool(self._FATURA_CANPARSE_RE.search(sample))
        except Exception as exc:
            logger.debug("can_parse FaturaCartao: %s", exc)
            return False

    def parse(self, file_content: bytes) -> list[dict]:
        try:
            pages_text: list[str] = []
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                    pages_text.append(text)
        except Exception as exc:
            logger.error("Falha ao ler PDF Fatura Nubank: %s", exc)
            return []

        full_text = "\n".join(pages_text)
        transactions = self._parse_text(full_text)
        logger.info("FaturaCartaoNubankParser: %d transações extraídas", len(transactions))
        return transactions

    def _parse_text(self, text: str) -> list[dict]:
        # Extrai o ano da fatura do cabeçalho
        year = self._extract_year(text)

        lines = [ln.strip() for ln in text.splitlines()]
        transactions: list[dict] = []

        for line in lines:
            if not line:
                continue
            if _SKIP_RE.search(line):
                continue

            m = _TX_LINE_RE.match(line)
            if not m:
                continue

            day_str   = m.group(1)
            month_str = m.group(2).upper()
            description = m.group(3).strip()
            value_str = m.group(4)

            month_num = _MONTH_MAP.get(month_str)
            if not month_num:
                continue

            try:
                tx_date = date(year, month_num, int(day_str))
            except ValueError:
                continue

            amount = _parse_value(value_str)
            classification = classify_transaction(description)

            # Detectar "- Parcela X/Y" embutido na descrição
            installment_current: int | None = None
            installment_total: int | None = None
            inst_match = _INSTALLMENT_RE.search(description)
            if inst_match:
                installment_current = int(inst_match.group(1))
                installment_total   = int(inst_match.group(2))
                description = _INSTALLMENT_RE.sub("", description).strip()

            transactions.append({
                "date": tx_date.isoformat(),
                "description": description,
                "raw_description": line,
                "amount": amount,
                "account": self.ACCOUNT_KEY,
                "installment_current": installment_current,
                "installment_total":   installment_total,
                "is_payment": bool(_PAYMENT_RE.search(description)),
                **classification,
            })

        return transactions

    def _extract_year(self, text: str) -> int:
        """Extrai o ano do cabeçalho 'FATURA DD MMM YYYY'."""
        m = _FATURA_HEADER_RE.search(text)
        if m:
            return int(m.group(2))
        # Fallback: ano corrente
        return date.today().year

    def extract_invoice_metadata(self, file_content: bytes) -> dict | None:
        """
        Extrai metadados reais da fatura Nubank a partir do PDF.

        Retorna dict com os campos:
          invoice_label_month, due_date, due_month, cycle_start_date,
          cycle_end_date, issue_date, closing_date, total_amount, source

        Todos os campos de data são strings "YYYY-MM-DD" ou None.

        Regra de ano para o período vigente:
          - O ano base é extraído de due_date (ou do cabeçalho FATURA).
          - Se start_month > end_month → start pertence ao ano anterior.
          - Caso contrário → mesmo ano de end.
        """
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                text = "\n".join(
                    (page.extract_text(x_tolerance=3, y_tolerance=3) or "")
                    for page in pdf.pages
                )
        except Exception as exc:
            logger.error("extract_invoice_metadata: falha ao ler PDF: %s", exc)
            return None

        def _make_date(day: int, month: int, year: int) -> str | None:
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                return None

        # ── due_date ─────────────────────────────────────────────────────────
        due_date: str | None = None
        due_year: int | None = None
        due_month_num: int | None = None

        # 1ª prioridade: "Data de vencimento: DD ABR 2026"
        m = _DUE_DATE_RE.search(text)
        if m:
            dd, mmm, yyyy = int(m.group(1)), _MONTH_MAP.get(m.group(2).upper()), int(m.group(3))
            if mmm:
                due_date = _make_date(dd, mmm, yyyy)
                due_year = yyyy
                due_month_num = mmm

        # 2ª prioridade: "FATURA DD ABR 2026"
        if not due_date:
            m2 = _FATURA_FULL_RE.search(text)
            if m2:
                dd, mmm, yyyy = int(m2.group(1)), _MONTH_MAP.get(m2.group(2).upper()), int(m2.group(3))
                if mmm:
                    due_date = _make_date(dd, mmm, yyyy)
                    due_year = yyyy
                    due_month_num = mmm

        # ── due_month ────────────────────────────────────────────────────────
        due_month: str | None = None
        if due_year and due_month_num:
            due_month = f"{due_year:04d}-{due_month_num:02d}"

        # ── issue_date ───────────────────────────────────────────────────────
        issue_date: str | None = None
        m = _ISSUE_DATE_RE.search(text)
        if m:
            dd = int(m.group(1))
            mmm = _MONTH_MAP.get(m.group(2).upper())
            yyyy = int(m.group(3))
            if mmm:
                issue_date = _make_date(dd, mmm, yyyy)

        # ── cycle_start_date / cycle_end_date ─────────────────────────────
        cycle_start_date: str | None = None
        cycle_end_date: str | None = None

        period_match = _PERIOD_RE.search(text) or _PERIOD_ALT_RE.search(text)
        if period_match and due_year:
            s_day  = int(period_match.group(1))
            s_mmm  = _MONTH_MAP.get(period_match.group(2).upper())
            e_day  = int(period_match.group(3))
            e_mmm  = _MONTH_MAP.get(period_match.group(4).upper())

            if s_mmm and e_mmm:
                end_year = due_year
                # Se mês de início > mês de fim → início é do ano anterior
                start_year = end_year - 1 if s_mmm > e_mmm else end_year
                cycle_start_date = _make_date(s_day, s_mmm, start_year)
                cycle_end_date   = _make_date(e_day, e_mmm, end_year)

        # ── closing_date ─────────────────────────────────────────────────────
        # Por padrão = cycle_end_date (não há campo separado no PDF Nubank)
        closing_date = cycle_end_date

        # ── total_amount ─────────────────────────────────────────────────────
        total_amount = _pick_invoice_total_amount(text)

        # ── invoice_label_month ───────────────────────────────────────────────
        invoice_label_month: str | None = None
        m = _FATURA_LABEL_RE.search(text)
        if m:
            invoice_label_month = m.group(1).lower()

        # Se não encontrou pelo regex de label mas temos due_month_num, derivar
        if not invoice_label_month and due_month_num:
            invoice_label_month = _MONTH_LABELS_PT.get(due_month_num)

        return {
            "invoice_label_month": invoice_label_month,
            "due_date": due_date,
            "due_month": due_month,
            "cycle_start_date": cycle_start_date,
            "cycle_end_date": cycle_end_date,
            "issue_date": issue_date,
            "closing_date": closing_date,
            "total_amount": total_amount,
            "source": "nubank_pdf",
        }

    def extract_reference_month(self, file_content: bytes) -> str | None:
        """Extrai o mês de referência da fatura a partir do cabeçalho."""
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages[:3])
        except Exception:
            return None
        m = _FATURA_HEADER_RE.search(text)
        if not m:
            return None
        month_num = _MONTH_MAP.get(m.group(1).upper())
        if not month_num:
            return None
        return f"{int(m.group(2)):04d}-{month_num:02d}"
