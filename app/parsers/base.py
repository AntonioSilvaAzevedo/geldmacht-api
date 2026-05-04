from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Interface comum para todos os parsers de extrato."""

    @abstractmethod
    def can_parse(self, file_content: bytes) -> bool:
        """
        Detecta se o arquivo pertence a este parser.
        Deve ser rápido e não lançar exceções — retornar False em caso de erro.
        """
        ...

    @abstractmethod
    def parse(self, file_content: bytes) -> list[dict]:
        """
        Extrai lista de transações estruturadas do arquivo.

        Retorna lista de dicts com pelo menos:
          - date: str (YYYY-MM-DD)
          - description: str
          - raw_description: str
          - amount: float  (negativo = saída)
          - account: str   (identificador da conta: 'nubank_pf', 'itau', ...)
          - is_internal_transfer: bool
        """
        ...
