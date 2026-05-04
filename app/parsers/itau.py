"""
Parser do extrato Itaú Uniclass (conta 079787-1).

Formato extraído via pdfplumber:
─────────────────────────────────────────────────────
Cabeçalho (1ª linha):
  ANTONIO CARLOS SILVA DE AZEVEDO 039.520.120-92 agência: 0502 conta: 079787-1

Linha de transação:
  DD/MM/YYYY  DESCRIÇÃO  VALOR
  29/04/2026  PIX TRANSF Antonio29/04  -150,00
  24/04/2026  REMUNERACAO/SALARIO       15.878,00

Linha a ignorar:
  DD/MM/YYYY  SALDO DO DIA  VALOR  → saldo do dia, não é transação

Regras:
  • Valor sempre no fim da linha: [+-]?\d{1,3}(?:\.\d{3})*,\d{2}
  • Positivo = crédito (entrada), negativo = débito (saída)
  • Sem símbolo R$ — apenas número com vírgula decimal
"""
import io
import re
import logging
from datetime import date

import pdfplumber

from .base import BaseParser
from ..categorization.categorizer import classify_transaction

logger = logging.getLogger(__name__)

# ── Regex de linha de transação ───────────────────────────────────────────────
# Captura: data, descrição, valor (com sinal)
_TX_LINE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([-+]?\d{1,3}(?:\.\d{3})*,\d{2})$"
)

# ── Linhas a ignorar ──────────────────────────────────────────────────────────
_SKIP_RE = re.compile(
    r"""
      saldo\s+do\s+dia              # linha de saldo diário — não é transação
    | ^saldo\s+em\s+conta           # cabeçalho de resumo
    | limite\s+da\s+conta           # cabeçalho de limites
    | per[íi]odo\s+de\s+visualiza   # "período de visualização: ..."
    | emitido\s+em:                 # "emitido em: DD/MM/YYYY HH:MM:SS"
    | ^data\s+lan[çc]amentos        # cabeçalho da tabela
    | os\s+saldos\s+acima           # rodapé legal
    | consulte\s+a\s+[uú]ltima\s+vers  # rodapé legal
    | conforme\s+resolu[çc][aã]o    # rodapé legal
    | consultas,\s+informa[çc][oõ]es  # rodapé SAC
    | reclama[çc][oõ]es,\s+cancelamento # rodapé SAC
    | se\s+n[aã]o\s+ficar\s+satisfeito # rodapé ouvidoria
    | deficiente\s+auditivo         # rodapé acessibilidade
    | ou\s+entre\s+em\s+contato     # rodapé
    | aviso!                        # aviso do extrato
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_itau_date(date_str: str) -> date | None:
    """Converte DD/MM/YYYY em objeto date."""
    try:
        day, month, year = date_str.split("/")
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None


def _parse_itau_value(value_str: str) -> float:
    """Converte '1.234,56' ou '-1.234,56' em float."""
    raw = value_str.replace(".", "").replace(",", ".")
    return float(raw)


class ItauParser(BaseParser):
    """
    Parser para o extrato Itaú Uniclass.
    Conta: Agência 0502 / 079787-1
    """

    ACCOUNT_KEY = "itau"
    _IDENTIFIERS = ["079787-1", "agência: 0502"]

    def can_parse(self, file_content: bytes) -> bool:
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                if not pdf.pages:
                    return False
                sample = ""
                for page in pdf.pages[:2]:
                    sample += (page.extract_text() or "").lower()
            return all(ident.lower() in sample for ident in self._IDENTIFIERS)
        except Exception as exc:
            logger.debug("can_parse Itau: %s", exc)
            return False

    def parse(self, file_content: bytes) -> list[dict]:
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                lines: list[str] = []
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                    lines.extend(ln.strip() for ln in text.splitlines())
        except Exception as exc:
            logger.error("Falha ao ler PDF Itaú: %s", exc)
            return []

        transactions = self._parse_lines(lines)
        logger.info("ItauParser: %d transações extraídas", len(transactions))
        return transactions

    def _parse_lines(self, lines: list[str]) -> list[dict]:
        transactions: list[dict] = []

        for line in lines:
            if not line:
                continue
            if _SKIP_RE.search(line):
                continue

            m = _TX_LINE_RE.match(line)
            if not m:
                continue

            date_str, description, value_str = m.group(1), m.group(2), m.group(3)

            # Ignora linhas de saldo do dia que passaram pelo _SKIP_RE
            if re.search(r"saldo\s+do\s+dia", description, re.IGNORECASE):
                continue

            tx_date = _parse_itau_date(date_str)
            if tx_date is None:
                continue

            amount = _parse_itau_value(value_str)
            classification = classify_transaction(description)

            transactions.append({
                "date": tx_date.isoformat(),
                "description": description,
                "raw_description": line,
                "amount": amount,
                "account": self.ACCOUNT_KEY,
                **classification,
            })

        return transactions
