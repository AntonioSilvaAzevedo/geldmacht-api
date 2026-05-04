"""
Parser do extrato Mercado Pago (conta 83623266135).

Formato extraído via pdfplumber:
─────────────────────────────────────────────────────
Cabeçalho:
  EXTRATO DE CONTA
  Antonio Carlos Silva de Azevedo
  CPF/CNPJ: 03952012092 Agência: 1 Conta: 83623266135
  Periodo: De DD-MM-YYYY al DD-MM-YYYY

Tabela de transações (5 colunas: Data | Descrição | ID | Valor | Saldo):
O pdfplumber extrai o texto mesclando as colunas, gerando 3 padrões:

  Padrão A — descrição antes da linha de dados:
    Pix recebido Isadora Sloniak
    01-03-2026 148401738090 R$ 1.850,78 R$ 1.850,78
    Gomes                                             ← sufixo da descrição

  Padrão B — descrição na mesma linha dos dados:
    01-03-2026 Dinheiro reservado Saldo amor 148402263736 R$ -1.730,78 R$ 0,00

  Padrão C — sem descrição inline, descrição apenas no texto adjacente:
    Pix recebido Antonio Carlos
    01-03-2026 148963312316 R$ 1.000,00 R$ 1.000,00
    Silva de Azevedo

Estratégia de parsing:
  • Linha de dados: começa com DD-MM-YYYY + ID (12+ dígitos) + R$ valor + R$ saldo
  • Linhas sem data antes da linha de dados → pré-descrição
  • Linha imediatamente após uma linha de dados (sem data) → sufixo da descrição
  • Descrição final = pré_desc + inline_desc + sufixo
"""
import io
import re
import logging
from datetime import date

import pdfplumber

from .base import BaseParser
from ..categorization.categorizer import classify_transaction

logger = logging.getLogger(__name__)

# ── Linha de dados: DD-MM-YYYY [desc_inline] ID R$ valor R$ saldo ─────────────
_DATA_LINE_RE = re.compile(
    r"^(\d{2}-\d{2}-\d{4})"          # data
    r"(?:\s+(.+?))?"                   # descrição inline (opcional)
    r"\s+(\d{10,})"                    # ID da operação (≥10 dígitos)
    r"\s+R\$\s*(-?[\d.]+,\d{2})"      # valor (com ou sem sinal)
    r"\s+R\$\s*[-\d.,]+"              # saldo (ignorado)
    r"$"
)

# ── Valor numérico em formato brasileiro ──────────────────────────────────────
def _parse_mp_value(value_str: str) -> float:
    raw = value_str.replace(".", "").replace(",", ".")
    return float(raw)

# ── Data DD-MM-YYYY → date ────────────────────────────────────────────────────
def _parse_mp_date(date_str: str) -> date | None:
    try:
        day, month, year = date_str.split("-")
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None

# ── Linhas de cabeçalho/rodapé a ignorar ─────────────────────────────────────
_SKIP_RE = re.compile(
    r"""
      ^extrato\s+de\s+conta           # título
    | ^antonio\s+carlos               # nome do titular
    | cpf/cnpj:                       # CPF/CNPJ
    | ^periodo:                       # período
    | ^entradas:                      # resumo de entradas
    | ^saldo\s+(inicial|final):       # saldo inicial/final
    | ^saidas:                        # resumo de saídas
    | detalhe\s+dos\s+movimentos      # cabeçalho da seção
    | ^data\s+descri[çc][aã]o         # cabeçalho da tabela
    | ^\d+/\d+$                       # paginação "1/5"
    """,
    re.IGNORECASE | re.VERBOSE,
)


class MercadoPagoParser(BaseParser):
    """
    Parser para o extrato de conta Mercado Pago.
    Conta: Agência 1 / 83623266135
    """

    ACCOUNT_KEY = "mercado_pago"
    _IDENTIFIERS = ["83623266135", "extrato de conta"]

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
            logger.debug("can_parse MercadoPago: %s", exc)
            return False

    def parse(self, file_content: bytes) -> list[dict]:
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                lines: list[str] = []
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                    lines.extend(ln.strip() for ln in text.splitlines())
        except Exception as exc:
            logger.error("Falha ao ler PDF Mercado Pago: %s", exc)
            return []

        transactions = self._parse_lines(lines)
        logger.info("MercadoPagoParser: %d transações extraídas", len(transactions))
        return transactions

    def _parse_lines(self, lines: list[str]) -> list[dict]:
        """
        Máquina de estados para lidar com a descrição particionada em 3 partes.
        """
        transactions: list[dict] = []
        pending_pre: list[str] = []   # linhas de descrição antes da linha de dados
        expect_suffix = False          # True = próxima linha não-dados é sufixo da desc

        for line in lines:
            if not line:
                continue
            if _SKIP_RE.search(line):
                pending_pre = []
                expect_suffix = False
                continue

            m = _DATA_LINE_RE.match(line)
            if m:
                date_str     = m.group(1)
                inline_desc  = (m.group(2) or "").strip()
                value_str    = m.group(4)

                # Monta descrição: pré-desc + inline
                parts = [p for p in pending_pre + [inline_desc] if p]
                description = " ".join(parts)

                tx_date = _parse_mp_date(date_str)
                if tx_date is None:
                    pending_pre = []
                    expect_suffix = False
                    continue

                amount = _parse_mp_value(value_str)
                classification = classify_transaction(description)

                transactions.append({
                    "date": tx_date.isoformat(),
                    "description": description,
                    "raw_description": line,
                    "amount": amount,
                    "account": self.ACCOUNT_KEY,
                    **classification,
                })

                pending_pre = []
                # Só espera sufixo quando não havia descrição inline.
                # Se havia inline_desc, a próxima linha sem data é pré-desc da próxima TX.
                expect_suffix = not bool(inline_desc)

            elif expect_suffix:
                # Sufixo da última transação (ex: "Gomes", "Silva de Azevedo")
                if transactions:
                    last = transactions[-1]
                    last["description"] = (last["description"] + " " + line).strip()
                expect_suffix = False

            else:
                # Pré-descrição para a próxima transação
                pending_pre.append(line)

        return transactions
