import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..middleware.auth import get_current_user
from ..database import get_db
from ..models.user import User
from ..parsers import detect_parser
from ..parsers.ofx_bank_statement import detect_ofx_kind, parse_bank_statement_ofx
from ..schemas.transaction import ParsedTransaction, StatementMetadata, UploadResponse
from ..schemas.import_batch import ExistingImportBatchInfo
from ..services.bank_statement_import import find_already_imported_batch, sha256_hex
from ..schemas.invoice import InvoiceMetadata
from ..services.summary_service import calculate_invoice_summary

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadResponse,
    response_model_exclude_none=True,
    summary="Enviar extrato (PDF, Excel ou OFX)",
    description=(
        "Detecta o tipo do arquivo, extrai as transações com o parser correto "
        "e retorna um preview. **Não salva no banco nesta etapa.** "
        "Com `import_kind=bank_statement`, espera arquivo .ofx e usa o parser genérico de extrato."
    ),
)
async def upload_statement(
    file: UploadFile = File(...),
    import_kind: str | None = Form(None),
    bank_account_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    filename = file.filename or "arquivo"
    filename_lower = filename.lower()
    content_type = file.content_type or ""

    # ── Ramo extrato OFX ─────────────────────────────────────────────────────
    if import_kind == "bank_statement":
        if bank_account_id is None:
            raise HTTPException(
                status_code=422,
                detail="Para import_kind=bank_statement informe bank_account_id (multipart Form).",
            )
        is_ofx_ext = filename_lower.endswith(".ofx") or ".ofx" in filename_lower
        is_sgml_hint = (
            filename_lower.endswith(".qfx")  # mesmo formato
            or "ofx" in content_type.lower()
            or "application/x-ofx" in content_type.lower()
        )
        if not (is_ofx_ext or is_sgml_hint):
            raise HTTPException(
                status_code=415,
                detail="Para import_kind=bank_statement envie um arquivo OFX (.ofx ou .qfx).",
            )

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Arquivo vazio.")

        if detect_ofx_kind(content) == "credit_card":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Este arquivo OFX parece ser de fatura de cartão de crédito. "
                    "Para importá-lo, use Importar fatura."
                ),
            )

        from ..models.bank_account import BankAccount

        bacc_row = (
            db.query(BankAccount)
            .filter(
                BankAccount.id == bank_account_id,
                BankAccount.user_id == current_user.id,
            )
            .first()
        )
        if not bacc_row:
            raise HTTPException(status_code=404, detail="Conta bancária não encontrada.")
        if not bacc_row.is_active:
            raise HTTPException(status_code=400, detail="Conta bancária está desativada.")

        file_hash = sha256_hex(content)

        existing_batch = find_already_imported_batch(
            db,
            user_id=current_user.id,
            bank_account_id=bank_account_id,
            file_hash=file_hash,
        )
        if existing_batch:
            return UploadResponse(
                parser_used="bank_statement_ofx",
                source_file=filename,
                total_transactions=0,
                transactions=[],
                import_kind="bank_statement",
                file_hash=file_hash,
                already_imported=True,
                existing_import_batch=ExistingImportBatchInfo(
                    id=existing_batch.id,
                    file_name=existing_batch.file_name,
                    imported_at=existing_batch.imported_at,
                    imported_count=existing_batch.imported_count,
                    skipped_count=existing_batch.skipped_count,
                ),
            )

        try:
            raw_meta, raw_txs = parse_bank_statement_ofx(content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            stmt_meta = StatementMetadata(**raw_meta) if raw_meta else None
        except Exception as exc:
            logger.warning("statement_metadata inválido: %s", exc)
            stmt_meta = None

        parsed: list[ParsedTransaction] = []
        for tx in raw_txs:
            try:
                parsed.append(ParsedTransaction(**tx))
            except Exception as exc:
                logger.warning("Transação OFX ignorada (schema): %s — %s", tx, exc)

        if not parsed:
            raise HTTPException(
                status_code=422,
                detail="Nenhuma transação válida após validar o OFX.",
            )

        return UploadResponse(
            parser_used="bank_statement_ofx",
            source_file=filename,
            total_transactions=len(parsed),
            transactions=parsed,
            import_kind="bank_statement",
            statement_metadata=stmt_meta,
            file_hash=file_hash,
        )

    # ── Ramo fatura OFX ──────────────────────────────────────────────────────
    is_ofx_file = (
        filename_lower.endswith((".ofx", ".qfx"))
        or "ofx" in content_type.lower()
    )
    if import_kind == "credit_card_invoice" and is_ofx_file:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Arquivo vazio.")

        if detect_ofx_kind(content) == "bank_statement":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Este arquivo OFX parece ser de extrato de conta corrente. "
                    "Para importá-lo, use Importar extrato."
                ),
            )

        try:
            raw_meta, raw_txs = parse_bank_statement_ofx(content, invoice_context=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        parsed: list[ParsedTransaction] = []
        for tx in raw_txs:
            tx["account"] = "credit_card_ofx"
            try:
                parsed.append(ParsedTransaction(**tx))
            except Exception as exc:
                logger.warning("Transação OFX de fatura ignorada (schema): %s — %s", tx, exc)

        if not parsed:
            raise HTTPException(
                status_code=422,
                detail="Nenhuma transação válida após validar o OFX.",
            )

        detected_reference_month = None
        period_end = (raw_meta or {}).get("period_end")
        if period_end is not None:
            detected_reference_month = period_end.strftime("%Y-%m")
        else:
            from collections import Counter

            months = Counter(t.date.strftime("%Y-%m") for t in parsed)
            detected_reference_month = months.most_common(1)[0][0] if months else None

        return UploadResponse(
            parser_used="credit_card_ofx",
            source_file=filename,
            total_transactions=len(parsed),
            transactions=parsed,
            import_kind="credit_card_invoice",
            detected_reference_month=detected_reference_month,
        )

    # ── Fluxo legado PDF / Excel ─────────────────────────────────────────────
    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",  # alguns clientes enviam assim
    }
    is_pdf = filename_lower.endswith(".pdf") or "pdf" in content_type
    is_xlsx = filename_lower.endswith((".xlsx", ".xls")) or "excel" in content_type or "sheet" in content_type

    if not (is_pdf or is_xlsx):
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de arquivo não suportado: {content_type or filename}. Use PDF ou Excel.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

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

    parsed = []
    for tx in raw_transactions:
        try:
            parsed.append(ParsedTransaction(**tx))
        except Exception as exc:
            logger.warning("Transação ignorada (schema inválido): %s — %s", tx, exc)

    summary = None
    detected_reference_month = None
    invoice_metadata: InvoiceMetadata | None = None
    ik: str | None = None
    if import_kind == "credit_card_invoice":
        ik = "credit_card_invoice"

    if parser_name == "faturacartaonubank":
        summary = calculate_invoice_summary([tx.model_dump() for tx in parsed])

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
        import_kind=ik,
    )
