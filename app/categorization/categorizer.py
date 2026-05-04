"""
Detecção de transferências internas.
A categorização em si é responsabilidade do frontend.
"""
import re
from .rules import (
    INTERNAL_ACCOUNT_HINTS,
    INTERNAL_TRANSFER_PATTERNS,
)


def is_internal_transfer(description: str) -> bool:
    """
    Retorna True se a transação for entre contas próprias do titular.
    Transferências internas não somam como entrada nem como gasto real.
    """
    desc_lower = description.lower()

    # Padrões explícitos (RDB, caixinha, etc.)
    for pattern in INTERNAL_TRANSFER_PATTERNS:
        if re.search(pattern, desc_lower, re.IGNORECASE):
            return True

    # Transferências Pix/TED que mencionam conta própria como contraparte
    if "pix" in desc_lower or "transfer" in desc_lower:
        for hint in INTERNAL_ACCOUNT_HINTS:
            if hint.lower() in desc_lower:
                return True

    return False


def classify_transaction(description: str) -> dict:
    """
    Retorna metadados de classificação para uma transação.
    - is_internal_transfer: se é movimentação entre contas próprias
    - category / category_group: vazios — serão preenchidos pelo frontend
    """
    return {
        "is_internal_transfer": is_internal_transfer(description),
        "category": None,
        "category_group": None,
    }
