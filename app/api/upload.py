import logging
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..middleware.auth import get_current_user
from ..models.user import User
from ..parsers import detect_parser
from ..schemas.transaction import ParsedTransaction, UploadResponse
from ..schemas.invoice import InvoiceMetadata
from ..services.summary_service import calculate_invoice_summary

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadResponse,
    response_model_exclude_none=True,
    summary="Enviar extrato (PDF ou Excel)",
    description=(
        "Detecta o tipo do arquivo, extrai as transações com o parser correto "
        "e retorna um preview. **Não salva no banco nesta etapa.** "
        "Etapa 2.3 adicionará a confirmação e persistência."
    ),
)
async def upload_statement(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    # ── Validação básica ─────────────────────────────────────────────────────
    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",  # alguns clientes enviam assim
    }
    content_type = file.content_type or ""
    filename = file.filename or "arquivo"

    is_pdf = filename.lower().endswith(".pdf") or "pdf" in content_type
    is_xlsx = filename.lower().endswith((".xlsx", ".xls")) or "excel" in content_type or "sheet" in content_type

    if not (is_pdf or is_xlsx):
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de arquivo não suportado: {content_type or filename}. Use PDF ou Excel.",
        )

    # ── Leitura do conteúdo ──────────────────────────────────────────────────
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    # ── Detecção do parser ───────────────────────────────────────────────────
    parser = detect_parser(content)
    if parser is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Nenhum parser reconhece o arquivo '{filename}'. "
                "Certifique-se de enviar um extrato Nubank PF, Nubank PJ, "
                "Itaú, Mercado Pago, Fatura Nubank ou planilha B3."
            ),
        )

    parser_name = type(parser).__name__.lower().replace("parser", "").strip("_")
    logger.info("Upload: '%s' → parser %s", filename, parser_name)

    # ── Parsing ──────────────────────────────────────────────────────────────
    try:
        raw_transactions = parser.parse(content)
    except Exception as exc:
        logger.exception("Erro ao parsear '%s'", filename)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar o arquivo: {exc}",
        ) from exc

    if not raw_transactions:
        raise HTTPException(
            status_code=422,
            detail="Arquivo reconhecido mas nenhuma transação foi extraída. "
                   "Verifique se o PDF não está corrompido ou protegido por senha.",
        )

    # ── Montar resposta ──────────────────────────────────────────────────────
    parsed = []
    for tx in raw_transactions:
        try:
            parsed.append(ParsedTransaction(**tx))
        except Exception as exc:
            logger.warning("Transação ignorada (schema inválido): %s — %s", tx, exc)

    summary = None
    detected_reference_month = None
    invoice_metadata: InvoiceMetadata | None = None

    if parser_name == "faturacartaonubank":
        summary = calculate_invoice_summary([tx.model_dump() for tx in parsed])

        # Extrai metadados reais da fatura (due_date, ciclo, total, etc.)
        if hasattr(parser, "extract_invoice_metadata"):
            raw_meta = parser.extract_invoice_metadata(content)
            if raw_meta:
                invoice_metadata = InvoiceMetadata(**raw_meta)
                detected_reference_month = invoice_metadata.due_month
        elif hasattr(parser, "extract_reference_month"):
            detected_reference_month = parser.extract_reference_month(content)

    return UploadResponse(
        parser_used=parser_name,
        source_file=filename,
        total_transactions=len(parsed),
        transactions=parsed,
        detected_reference_month=detected_reference_month,
        invoice_metadata=invoice_metadata,
        summary=summary,
    )
