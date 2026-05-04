"""
Gera um PDF sintético de extrato Nubank PF para testes.
Executar uma vez: python tests/fixtures/make_nubank_pf_fixture.py
Requer: pip install fpdf2
"""
import sys
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("fpdf2 não instalado. Instalando...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fpdf2"])
    from fpdf import FPDF


NUBANK_PF_TEXT = """\
Antonio Carlos Silva de Azevedo
CPF ....520.120-.. Agência 0001 Conta
4365066-8
01 DE JANEIRO DE 2026 a 31 DE JANEIRO DE 2026 VALORES EM R$

05 JAN 2026 Total de entradas + 12.133,00
Transferência recebida pelo Pix ANTONIO CARLOS SILVA AZEVEDO - ITAÚ UNICLASS 10.899,00
Agência: 502 Conta: 079787-1
CAIXA ECONOMICA FEDERAL FGTS 1.234,00

Total de saídas - 3.273,31
Pagamento de boleto efetuado N N IMOVEIS LTDA 3.273,31

10 JAN 2026 Total de saídas - 3.246,52
Compra no débito BMB*COPEL 246,52
Transferência enviada pelo Pix Antonio Carlos Silva de Azevedo 3.000,00
mercado pago ip (0260) Agência: 1 Conta: 9084085

15 JAN 2026 Total de saídas - 1.058,90
Compra no débito iFood 58,90
Aplicação RDB 1.000,00

20 JAN 2026 Total de saídas - 499,90
Compra de FII HGLG11 312,50
Pagamento de boleto efetuado LIGGA 99,90
Compra no débito Mercadão de Carnes 187,40
"""


def create_fixture() -> Path:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    for line in NUBANK_PF_TEXT.splitlines():
        pdf.cell(0, 6, txt=line, ln=True)

    out_path = Path(__file__).parent / "nubank_pf_jan2026.pdf"
    pdf.output(str(out_path))
    print(f"Fixture criada: {out_path}")
    return out_path


if __name__ == "__main__":
    create_fixture()
