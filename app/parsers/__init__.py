from .base import BaseParser
from .nubank_pf import NubankPFParser
from .nubank_pj import NubankPJParser
from .itau import ItauParser
from .fatura_nubank import FaturaCartaoNubankParser
from .mercadopago import MercadoPagoParser

# Registro de todos os parsers — ordem importa para auto-detecção.
# Parsers mais específicos devem vir antes dos mais genéricos.
ALL_PARSERS: list[BaseParser] = [
    NubankPJParser(),           # nubank_pj  — conta 43185640-8
    NubankPFParser(),           # nubank_pf  — conta 4365066-8
    FaturaCartaoNubankParser(), # nubank_cartao — fatura cartão de crédito
    MercadoPagoParser(),        # mercado_pago — conta 83623266135
    ItauParser(),               # itau       — conta 079787-1
]


def detect_parser(file_content: bytes) -> BaseParser | None:
    """Detecta automaticamente qual parser usar para o arquivo enviado."""
    for parser in ALL_PARSERS:
        try:
            if parser.can_parse(file_content):
                return parser
        except Exception:
            continue
    return None
