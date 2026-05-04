"""
GET /api/dashboard/monthly

Agrega as transações do banco por mês e retorna estrutura compatível
com o tipo MonthlyData do frontend (src/types/financial.ts).

Lógica de agregação (sem categorização — category/category_group são null no MVP):
  - Identifica entradas e saídas por padrões de descrição
  - category/category_group ficam null — não implementar lógica de categorização
"""
import re
import logging
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.transaction import Transaction
from ..models.account import Account

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Padrões de identificação de entradas ─────────────────────────────────────
_SALARIO_RE  = re.compile(r"itaú unibanco|itau unibanco|salário|salario", re.IGNORECASE)
_PJ_RE       = re.compile(r"dez comunica[çc]ao|dceg|honorário|honorario", re.IGNORECASE)
_FGTS_RE     = re.compile(r"caixa econômica federal|caixa economica federal|fgts", re.IGNORECASE)
_VALE_RE     = re.compile(r"ifood bene|vale.?alim", re.IGNORECASE)
_CASHBACK_RE = re.compile(r"méliuz|meliuz|cashback|crédito em conta|credito em conta", re.IGNORECASE)

# ── Padrões de identificação de investimentos (saídas) ───────────────────────
_INVEST_RE = re.compile(
    r"compra de (ações|acoes|fii|etf|ação|acao)|aplicação rdb|aplicacao rdb",
    re.IGNORECASE,
)

# ── Padrões de fatura de cartão ───────────────────────────────────────────────
_FATURA_RE = re.compile(r"pagamento de fatura", re.IGNORECASE)

# ── Nomes dos meses ────────────────────────────────────────────────────────────
_MONTH_NAMES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def _month_key(date_obj) -> str:
    """Retorna 'YYYY-MM' a partir de um objeto date."""
    return f"{date_obj.year:04d}-{date_obj.month:02d}"


@router.get(
    "/dashboard/monthly",
    summary="Resumo mensal para o Dashboard Anual",
    description=(
        "Agrega transações por mês e retorna estrutura compatível com "
        "MonthlyData (src/types/financial.ts). "
        "category/category_group são null — sem categorização no MVP."
    ),
)
def get_monthly_dashboard(db: Session = Depends(get_db)) -> dict:
    transactions = db.query(Transaction).order_by(Transaction.date).all()

    if not transactions:
        return {}

    # Agrupa por mês
    by_month: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        by_month[_month_key(tx.date)].append(tx)

    result = {}

    for month_key in sorted(by_month.keys()):
        txs = by_month[month_key]
        year, month_num = int(month_key[:4]), int(month_key[5:7])

        # Entradas (amount > 0)
        salario_clt     = 0.0
        honorarios_pj   = 0.0
        fgts            = 0.0
        vale_alimentacao = 0.0
        cashback        = 0.0
        outras_entradas = 0.0

        # Saídas (amount < 0) — valor absoluto
        fatura_cartao   = 0.0
        investimentos   = 0.0
        fixos_moradia   = 0.0

        for tx in txs:
            desc = tx.description or ""

            if tx.amount > 0:
                if _SALARIO_RE.search(desc):
                    salario_clt += tx.amount
                elif _PJ_RE.search(desc):
                    honorarios_pj += tx.amount
                elif _FGTS_RE.search(desc):
                    fgts += tx.amount
                elif _VALE_RE.search(desc):
                    vale_alimentacao += tx.amount
                elif _CASHBACK_RE.search(desc):
                    cashback += tx.amount
                else:
                    outras_entradas += tx.amount

            else:  # amount < 0
                valor_abs = abs(tx.amount)
                if _FATURA_RE.search(desc):
                    fatura_cartao += valor_abs
                elif _INVEST_RE.search(desc):
                    investimentos += valor_abs
                else:
                    fixos_moradia += valor_abs

        total_entradas     = salario_clt + honorarios_pj + fgts + vale_alimentacao + cashback + outras_entradas
        total_gastos       = fatura_cartao + fixos_moradia
        total_investimentos = investimentos
        saldo_liquido      = total_entradas - total_gastos - total_investimentos

        result[month_key] = {
            "month": _MONTH_NAMES[month_num],
            "year": year,
            "entradas": {
                "salarioCLT":      round(salario_clt, 2),
                "honorariosPJ":    round(honorarios_pj, 2),
                "fgts":            round(fgts, 2),
                "valeAlimentacao": round(vale_alimentacao, 2),
                "cashback":        round(cashback, 2),
            },
            "gastos": {
                "faturaCartao": round(fatura_cartao, 2),
                "fixosMoradia": round(fixos_moradia, 2),
                "valeGasto":    0.0,
            },
            "investimentos": {
                "acoes":     0.0,
                "fiis":      0.0,
                "etfs":      0.0,
                "bitcoin":   0.0,
                "rendaFixa": 0.0,
            },
            "totalEntradas":      round(total_entradas, 2),
            "totalGastos":        round(total_gastos, 2),
            "totalInvestimentos": round(total_investimentos, 2),
            "saldoLiquido":       round(saldo_liquido, 2),
        }

    logger.info("dashboard/monthly: %d meses agregados", len(result))
    return result
