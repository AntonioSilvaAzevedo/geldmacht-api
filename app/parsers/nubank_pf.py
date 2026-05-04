"""
Parser do extrato Nubank conta corrente PF (conta 4365066-8).

Formato REAL do PDF Nubank (extraído com pdfplumber):
─────────────────────────────────────────────────────
Cabeçalho por página (repetido):
  Antonio Carlos Silva de Azevedo
  CPF •••.520.120-•• Agência 0001 Conta
  4365066-8
  01 DE MARÇO DE 2026 a 31 DE MARÇO DE 2026 VALORES EM R$

Bloco por dia:
  01 MAR 2026 Total de entradas + 488,43       ← header do dia (entradas)
  Descrição da Transação                   488,43   ← valor no FIM da linha, sem R$
  Linha de continuação (agência, conta)           ← SEM valor → ignorar
  Total de saídas - 488,43                        ← muda sinal para negativo
  Descrição da Transação                   488,43   ← saída (negativo)

Regras:
  • Valor sempre no fim da linha: NNNNN,NN (com ou sem pontos como separador)
  • Sinal determinado pela seção: entradas → +, saídas → −
  • Linhas sem valor no fim são continuações (banco, agência, número de conta) → ignorar
  • Rodapé longo "Tem alguma dúvida?" → ignorar
  • Paginação "X de Y" (e variante com letras duplicadas "XX ddee YY") → ignorar
"""
import io
import re
import logging
from datetime import date

import pdfplumber

from .base import BaseParser
from ..categorization.categorizer import classify_transaction

logger = logging.getLogger(__name__)

# ── Mapeamento de meses (português, uppercase) ────────────────────────────────
_MONTH_MAP: dict[str, int] = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4,
    "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8,
    "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
    # minúsculas também (para fixtures sintéticas e testes)
    "jan": 1, "fev": 2, "mar": 3, "abr": 4,
    "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
    # nomes completos (testes unitários de _parse_date)
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# ── Padrão do cabeçalho de dia ────────────────────────────────────────────────
# Exemplos: "01 MAR 2026 Total de entradas + 488,43"
#           "05 MAR 2026 Total de saídas - 10.851,40"
_DAY_HEADER_RE = re.compile(
    r"^(\d{2})\s+([A-Za-z]{3,4})\s+(\d{4})\s+Total\s+de\s+(entradas|sa[íi]das)",
    re.IGNORECASE,
)

# ── "Total de saídas" sem prefixo de data (muda seção no meio do dia) ─────────
_TOTAL_SAIDAS_RE = re.compile(
    r"^Total\s+de\s+sa[íi]das\s",
    re.IGNORECASE,
)

# ── Valor monetário no FIM da linha ──────────────────────────────────────────
# Captura: "10.874,00"  "488,43"  "2.205,17"
# NÃO captura: "8362326613-5"  "62409967-4"  (não terminam em ,DD)
_END_VALUE_RE = re.compile(
    r"(\d{1,3}(?:\.\d{3})*,\d{2})$"
)

# Também captura valores com prefixo "R$" (para fixtures sintéticas / testes)
_RS_VALUE_RE = re.compile(
    r"([+-])?\s*R\$\s*([\d.]+,\d{2})"
)


def _parse_amount(text: str) -> float | None:
    """
    Extrai valor monetário com prefixo R$ e sinal opcional (+/-).
    Usado pelos testes unitários de helpers.
    Retorna None se não encontrar padrão R$ na string.

    Exemplos:
      "R$ 10.899,00"            →  10899.0
      "-R$ 3.273,31"            → -3273.31
      "+R$ 500,00"              →    500.0
      "- R$ 246,52"             →  -246.52
      "Transferência R$ 10,00"  →    10.0
      "Sem valor"               →   None
    """
    m = _RS_VALUE_RE.search(text)
    if not m:
        return None
    sign = -1 if (m.group(1) or "+") == "-" else 1
    raw = m.group(2).replace(".", "").replace(",", ".")
    return sign * float(raw)

# ── Linhas a ignorar completamente ───────────────────────────────────────────
_SKIP_RE = re.compile(
    r"""
      ^antonio\s+carlos\s+silva          # nome na primeira linha de cada página
    | ^cpf\s+[•\d]                       # CPF mascarado
    | agência\s+0001\s+conta             # linha do cabeçalho
    | \d+\s+de\s+\w+\s+de\s+\d{4}\s+a   # "01 DE MARÇO DE 2026 a ..."
    | valores\s+em\s+r\$                 # "VALORES EM R$"
    | ^saldo\s+(inicial|final|do\s+per|do\s+dia)  # saldo inicial/final/do dia (PJ)
    | ^rendimento\s+l[íi]quido           # rendimento do saldo
    | ^r\$\s+[\d.,]+\s+total\s+de        # "R$ 0,00 Total de entradas..."
    | ^movimenta[çc][õo]es$              # separador de seção
    | tem\s+alguma\s+d[úu]vida           # rodapé longo
    | caso\s+a\s+solu[çc][aã]o           # rodapé longo
    | extrato\s+gerado\s+dia             # "Extrato gerado dia..."
    | ^[\d\s]+de\s+[\d\s]+$             # paginação "1 de 10" ou "66 ddee 1100"
    | ouvidoria                          # linha de ouvidoria
    | atendimento\s+24h                  # rodapé
    | o\s+saldo\s+l[íi]quido\s+corresponde   # disclaimer legal Nubank
    | n[aã]o\s+nos\s+responsabilizamos       # disclaimer legal Nubank
    | asseguramos\s+a\s+autenticidade        # disclaimer legal Nubank
    | nu\s+financeira\s+s\.?a\.?             # entidade jurídica Nubank
    | nu\s+pagamentos\s+s\.?a\.?             # entidade jurídica Nubank Pagamentos
    | cnpj\s+\d{2}\.\d{3}\.\d{3}            # cabeçalho PJ "CNPJ 47.014.242/..."
    | cnpj:\s*\d{2}\.\d{3}\.\d{3}           # linhas com CNPJ "cnpj: XX.XXX..."
    | sociedade\s+de\s+cr[eé]dito            # denominação social
    | institui[çc][aã]o\s+de\s+pagamento     # denominação social
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_date(day: str, month_str: str, year: str) -> date | None:
    """Converte componentes de data em objeto date. Retorna None se inválido."""
    month_num = _MONTH_MAP.get(month_str.strip())
    if not month_num:
        # Tenta ignorar caixa
        month_num = _MONTH_MAP.get(month_str.strip().upper())
    if not month_num:
        return None
    try:
        return date(int(year), month_num, int(day))
    except ValueError:
        return None


def _extract_value_from_line(line: str) -> tuple[float, str] | None:
    """
    Extrai o valor monetário do fim da linha e retorna (valor_abs, descrição).
    Retorna None se a linha não terminar com um valor monetário.

    Suporta dois formatos:
      - Formato real Nubank: "Descrição 10.874,00"   (sem R$)
      - Formato fixture/teste: "Descrição R$ 10.874,00" ou "-R$ 10.874,00"
    """
    # Formato real: valor no fim sem R$
    m = _END_VALUE_RE.search(line)
    if m:
        raw_val = m.group(1).replace(".", "").replace(",", ".")
        description = line[: m.start()].strip()
        return float(raw_val), description

    # Formato alternativo com R$ (fixtures sintéticas)
    m2 = _RS_VALUE_RE.search(line)
    if m2:
        sign = -1 if (m2.group(1) or "+") == "-" else 1
        raw_val = m2.group(2).replace(".", "").replace(",", ".")
        description = line[: m2.start()].strip().strip("+-").strip()
        # Ignora o sinal aqui — o sinal final vem da seção (entradas/saídas)
        return abs(float(raw_val)), description

    return None


def _extract_all_text(file_content: bytes) -> str:
    """Extrai todo o texto do PDF concatenando todas as páginas."""
    with pdfplumber.open(io.BytesIO(file_content)) as pdf:
        parts: list[str] = []
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                parts.append(text)
    return "\n".join(parts)


class NubankPFParser(BaseParser):
    """
    Parser para o extrato de conta corrente Nubank PF.
    Conta: Agência 0001 / 4365066-8
    """

    ACCOUNT_KEY = "nubank_pf"
    _IDENTIFIERS = ["4365066-8", "agência 0001"]

    # ── can_parse ─────────────────────────────────────────────────────────────

    def can_parse(self, file_content: bytes) -> bool:
        """
        Retorna True se o PDF pertencer à conta Nubank PF 4365066-8.
        Verifica as 2 primeiras páginas para não ser lento.
        """
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                if not pdf.pages:
                    return False
                sample = ""
                for page in pdf.pages[:2]:
                    sample += (page.extract_text() or "").lower()
            return all(ident.lower() in sample for ident in self._IDENTIFIERS)
        except Exception as exc:
            logger.debug("can_parse NubankPF: %s", exc)
            return False

    # ── parse ─────────────────────────────────────────────────────────────────

    def parse(self, file_content: bytes) -> list[dict]:
        """Extrai transações do extrato. Retorna lista de dicts."""
        try:
            full_text = _extract_all_text(file_content)
        except Exception as exc:
            logger.error("Falha ao ler PDF Nubank PF: %s", exc)
            return []

        transactions = self._parse_text(full_text)
        logger.info("NubankPFParser: %d transações extraídas", len(transactions))
        return transactions

    # ── _parse_text ───────────────────────────────────────────────────────────

    def _parse_text(self, text: str) -> list[dict]:
        """
        Máquina de estados linha-a-linha.

        Estado mantido:
          current_date — data do bloco atual
          sign         — +1 (entradas) ou -1 (saídas)
        """
        lines = [ln.strip() for ln in text.splitlines()]
        transactions: list[dict] = []
        current_date: date | None = None
        sign: int = 1  # entradas por padrão

        for line in lines:
            if not line:
                continue

            # ── 1. Ignorar linhas de cabeçalho / rodapé ──────────────────────
            if _SKIP_RE.search(line):
                continue

            # ── 2. Cabeçalho de dia: "DD MMM YYYY Total de entradas/saídas + X"
            m = _DAY_HEADER_RE.match(line)
            if m:
                current_date = _parse_date(m.group(1), m.group(2), m.group(3))
                section = m.group(4).lower()
                sign = 1 if "entrada" in section else -1
                continue

            # ── 3. "Total de saídas - X" sem prefixo de data ─────────────────
            if _TOTAL_SAIDAS_RE.match(line):
                sign = -1
                continue

            # ── 4. "Total de entradas + X" sem prefixo de data ───────────────
            if re.match(r"^Total\s+de\s+entradas", line, re.IGNORECASE):
                sign = 1
                continue

            # ── 5. Processar apenas quando já há data ────────────────────────
            if current_date is None:
                continue

            # ── 6. Linha de transação: termina com valor monetário ────────────
            result = _extract_value_from_line(line)
            if result is not None:
                abs_value, description = result
                if not description:
                    description = line  # usa linha inteira se desc vazia
                amount = abs_value * sign
                tx = self._build_transaction(description, line, amount, current_date)
                transactions.append(tx)
            else:
                # Linha de continuação (banco, agência, nº conta, "enviada)")
                # Adiciona à descrição da última transação e re-categoriza
                if transactions:
                    last = transactions[-1]
                    last["description"] = (last["description"] + " " + line).strip()
                    last["raw_description"] = (last["raw_description"] + " " + line).strip()
                    classification = classify_transaction(last["description"])
                    last.update(classification)

        return transactions

    # ── _build_transaction ────────────────────────────────────────────────────

    def _build_transaction(
        self,
        description: str,
        raw_line: str,
        amount: float,
        tx_date: date,
    ) -> dict:
        """Monta o dict final com categorização aplicada."""
        classification = classify_transaction(description)
        return {
            "date": tx_date.isoformat(),
            "description": description,
            "raw_description": raw_line,
            "amount": amount,
            "account": self.ACCOUNT_KEY,
            **classification,
        }
