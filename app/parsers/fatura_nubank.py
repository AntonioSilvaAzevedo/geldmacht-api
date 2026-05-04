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
  DD MMM Pagamento em DD MMM              −R$ X.XXX,XX   ← pagamento da fatura (ignorar)

Linhas a ignorar:
  USD XX.XX                        ← conversão de moeda
  Conversão: USD 1 = R$ X,XX      ← taxa de câmbio
  Pagamento em DD MMM              ← pagamento da fatura (já no extrato conta corrente)

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

# ── Cabeçalho "FATURA DD MMM YYYY" — extrai o ano da fatura ──────────────────
_FATURA_HEADER_RE = re.compile(
    r"FATURA\s+\d{2}\s+[A-Z]{3}\s+(\d{4})", re.IGNORECASE
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

# ── Linhas a ignorar completamente ───────────────────────────────────────────
_SKIP_RE = re.compile(
    r"""
      ^antonio\s+carlos\s+silva       # nome do titular
    | ^fatura\s+\d{2}\s+[a-z]{3}     # "FATURA DD MMM YYYY EMISSÃO..."
    | ^transa[çc][oõ]es\s+de\s+\d{2} # "TRANSAÇÕES DE 04 FEV A 04 MAR"
    | ^usd\s+[\d.,]+                  # linha com valor em dólar
    | convers[aã]o:\s+usd             # "Conversão: USD 1 = R$ 5,40"
    | ^pagamento\s+em\s+\d{2}         # pagamento da fatura (já no extrato)
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
                **classification,
            })

        return transactions

    def _extract_year(self, text: str) -> int:
        """Extrai o ano do cabeçalho 'FATURA DD MMM YYYY'."""
        m = _FATURA_HEADER_RE.search(text)
        if m:
            return int(m.group(1))
        # Fallback: ano corrente
        return date.today().year
