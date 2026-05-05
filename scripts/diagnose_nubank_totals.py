#!/usr/bin/env python3
"""
Diagnóstico offline (não usado pelo CI):

  cd geldmacht-api && source venv/bin/activate
  python scripts/diagnose_nubank_totals.py /caminho/fatura.pdf

Imprime invoice_metadata.total_amount (PDF), summary.total_invoice (soma de gastos
nos lançamentos parseados), soma líquida das linhas e contagens — útil para achar em
qual etapa um valor diverge.

Não versionar PDFs reais sensíveis; passe um arquivo local.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.parsers.fatura_nubank import FaturaCartaoNubankParser  # noqa: E402
from app.services.summary_service import calculate_invoice_summary  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostica totais da fatura Nubank PDF.")
    parser.add_argument("pdf", type=Path, help="Caminho do arquivo PDF da fatura")
    args = parser.parse_args()

    path: Path = args.pdf
    if not path.is_file():
        print(f"Arquivo não encontrado: {path}", file=sys.stderr)
        sys.exit(1)

    raw = path.read_bytes()
    p = FaturaCartaoNubankParser()
    txs = p.parse(raw)
    meta = p.extract_invoice_metadata(raw)
    summary = calculate_invoice_summary(txs)
    gross_neg = round(sum(abs(t["amount"]) for t in txs if t["amount"] < 0), 2)
    net_sum = round(sum(t["amount"] for t in txs), 2)

    print(f"PDF: {path}")
    print(f"  invoice_metadata.total_amount (extraído): {meta.get('total_amount') if meta else None}")
    print(f"  lançamentos parseados: {len(txs)}")
    print(f"  summary.total_invoice (= soma |gasto| lançamentos): {summary.total_invoice}")
    print(f"  conferência soma manual |amount| se amount<0: {gross_neg}")
    print(f"  soma líquida Σ amount (todas linhas): {net_sum}")
    print(f"  summary.total_credits (Σ créditos positivos): {summary.total_credits}")
    print(f"  summary.payment_amount: {summary.payment_amount}")


if __name__ == "__main__":
    main()
