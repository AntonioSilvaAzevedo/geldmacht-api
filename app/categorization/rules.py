"""
Detecção de transferências internas.
Categorização será feita no frontend — aqui apenas identificamos
se uma transação é entre contas próprias do titular.
"""

# ─── Contas próprias do titular ──────────────────────────────────────────────
# Usado em can_parse e para identificação geral
OWN_ACCOUNTS = [
    "antonio carlos silva de azevedo",
    "4365066-8",       # nubank pf
    "43185640-8",      # nubank pj
    "079787-1",        # itaú
    "mercado pago",
    "nuinvest",
    "9084085",
]

# ─── Identificadores usados para detectar transferências internas ─────────────
# NÃO inclui:
#   - nome do titular  → aparece como remetente em TODO Pix enviado
#   - "4365066-8"      → aparece como conta de origem em continuações de saídas
# Inclui apenas identificadores das OUTRAS contas próprias (contraparte real)
INTERNAL_ACCOUNT_HINTS = [
    "43185640-8",      # nubank pj
    "079787-1",        # itaú
    "mercado pago",
    "nuinvest",
    "9084085",
]

# ─── Padrões de descrição que indicam movimentação interna ───────────────────
INTERNAL_TRANSFER_PATTERNS = [
    r"resgate\s+rdb",
    r"aplica[çc][aã]o\s+rdb",
    r"dinheiro\s+reservado",
    r"dinheiro\s+retirado",
    r"transfer[eê]ncia\s+entre\s+contas",
    r"poupan[çc]a\s+programada",
]
