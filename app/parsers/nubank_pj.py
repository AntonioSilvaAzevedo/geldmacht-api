"""
Parser do extrato Nubank conta corrente PJ (conta 43185640-8).

Formato idêntico ao Nubank PF — mesma máquina de estados.
Diferenças do cabeçalho:
  - Nome: "ANTONIO CARLOS SILVA DE AZEVEDO SERVICOS"
  - CNPJ em vez de CPF
  - Conta: 43185640-8
"""
import io
import logging

import pdfplumber

from .nubank_pf import NubankPFParser

logger = logging.getLogger(__name__)


class NubankPJParser(NubankPFParser):
    """
    Parser para o extrato de conta corrente Nubank PJ.
    Conta: Agência 0001 / 43185640-8
    Herda toda a lógica de parsing do NubankPFParser.
    """

    ACCOUNT_KEY = "nubank_pj"
    _IDENTIFIERS = ["43185640-8", "agência 0001"]

    def can_parse(self, file_content: bytes) -> bool:
        """Retorna True se o PDF pertencer à conta Nubank PJ 43185640-8."""
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                if not pdf.pages:
                    return False
                sample = ""
                for page in pdf.pages[:2]:
                    sample += (page.extract_text() or "").lower()
            return all(ident.lower() in sample for ident in self._IDENTIFIERS)
        except Exception as exc:
            logger.debug("can_parse NubankPJ: %s", exc)
            return False
