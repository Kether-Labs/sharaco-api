from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import Response
from app.models.payment_schedule import PaymentSchedule, MilestoneStatus
from sqlalchemy import func, distinct
from app.services.pdfRenderer import pdf_renderer
from app.services.emailService import EmailService
from datetime import datetime, timezone
from app.services.paymentScheduleService import PaymentScheduleService
from app.core.config import settings
from app.services.notificationService import NotificationService
from uuid import UUID
from typing import Optional
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.document import DocumentType, DocumentStatus, DocumentItem
from app.services.documentService import DocumentService
from app.services.templateService import TemplateService
from app.utils.datetime import to_naive_utc
from datetime import datetime, timezone, timedelta
from app.services.clientService import ClientService
from app.schemas.document import (
    DocumentCreate,
    DocumentRead,
    DocumentUpdate,
    DocumentStatusUpdate,
    DocumentEmailRequest,
    DocumentListRead,
    DocumentProjectLink,
    DocumentPreviewRequest,
    SharedDocumentRead,
    AcceptDocumentRequest,
    RefuseDocumentRequest
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.document import Document
from pydantic import BaseModel, Field
import logging

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


# ============================================================
# 📄 LIVE PREVIEW (pas de sauvegarde DB)
# ============================================================

@router.get("/stats", response_model=dict)
async def get_documents_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"📊 GET /documents/stats")

    quotes_count_stmt = (
        select(Document.status, func.count(Document.id))
        .select_from(Document)
        .where(Document.user_id == current_user.id, Document.type == DocumentType.DEVIS)
        .group_by(Document.status)
    )
    quotes_count_result = await db.execute(quotes_count_stmt)
    quotes_by_status = {row[0].value: row[1] for row in quotes_count_result.all()}

    invoices_count_stmt = (
        select(
            Document.status,
            func.count(distinct(Document.id)),
        )
        .select_from(Document)
        .where(Document.user_id == current_user.id, Document.type == DocumentType.FACTURE)
        .group_by(Document.status)
    )
    invoices_count_result = await db.execute(invoices_count_stmt)
    invoices_count_by_status = {row[0].value: row[1] for row in invoices_count_result.all()}

    invoice_totals_subq = (
        select(
            Document.id.label("doc_id"),
            Document.status.label("status"),
            func.coalesce(
                func.sum(
                    DocumentItem.quantity * DocumentItem.unit_price_cents +
                    (DocumentItem.quantity * DocumentItem.unit_price_cents * DocumentItem.tax_rate / 100)
                ), 0
            ).label("total_cents")
        )
        .select_from(Document)
        .outerjoin(DocumentItem, DocumentItem.document_id == Document.id)
        .where(Document.user_id == current_user.id, Document.type == DocumentType.FACTURE)
        .group_by(Document.id, Document.status)
        .subquery()
    )

    invoices_totals_stmt = (
        select(
            invoice_totals_subq.c.status,
            func.sum(invoice_totals_subq.c.total_cents)
        )
        .group_by(invoice_totals_subq.c.status)
    )
    invoices_totals_result = await db.execute(invoices_totals_stmt)
    invoices_totals_by_status = {
        row[0].value: int(row[1]) for row in invoices_totals_result.all()
    }

    invoices_by_status = {}
    all_statuses = set(invoices_count_by_status.keys()) | set(invoices_totals_by_status.keys())
    for status in all_statuses:
        invoices_by_status[status] = {
            "count": invoices_count_by_status.get(status, 0),
            "total_cents": invoices_totals_by_status.get(status, 0),
        }

    pipeline_subq = (
        select(
            Document.id.label("doc_id"),
            func.coalesce(
                func.sum(
                    DocumentItem.quantity * DocumentItem.unit_price_cents +
                    (DocumentItem.quantity * DocumentItem.unit_price_cents * DocumentItem.tax_rate / 100)
                ), 0
            ).label("total_cents")
        )
        .select_from(Document)
        .outerjoin(DocumentItem, DocumentItem.document_id == Document.id)
        .where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
            Document.status == DocumentStatus.ACCEPTED,
        )
        .group_by(Document.id)
        .subquery()
    )

    pipeline_stmt = select(func.coalesce(func.sum(pipeline_subq.c.total_cents), 0))
    pipeline_result = await db.execute(pipeline_stmt)
    pipeline_cents = int(pipeline_result.scalar() or 0)

    paid = invoices_by_status.get("PAID", {"count": 0, "total_cents": 0})
    revenue_cents = paid["total_cents"]
    paid_count = paid["count"]

    sent = invoices_by_status.get("SENT", {"count": 0, "total_cents": 0})
    viewed = invoices_by_status.get("VIEWED", {"count": 0, "total_cents": 0})
    receivables_cents = sent["total_cents"] + viewed["total_cents"]
    receivables_count = sent["count"] + viewed["count"]

    drafts = invoices_by_status.get("DRAFT", {"count": 0, "total_cents": 0})
    drafts_cents = drafts["total_cents"]
    drafts_count = drafts["count"]

    overdue_cents = 0
    overdue_count = 0

    quotes_sent = (
        quotes_by_status.get("SENT", 0) +
        quotes_by_status.get("VIEWED", 0) +
        quotes_by_status.get("ACCEPTED", 0) +
        quotes_by_status.get("REFUSED", 0)
    )
    quotes_accepted = quotes_by_status.get("ACCEPTED", 0)
    conversion_rate = (quotes_accepted / quotes_sent * 100) if quotes_sent > 0 else 0

    total_invoices_count = paid_count + receivables_count + overdue_count
    collection_rate = (
        paid_count / total_invoices_count * 100
        if total_invoices_count > 0 else 0
    )

    return {
        "revenue_cents": revenue_cents,
        "paid_invoices_count": paid_count,
        "receivables_cents": receivables_cents,
        "receivables_count": receivables_count,
        "drafts_cents": drafts_cents,
        "drafts_count": drafts_count,
        "overdue_cents": overdue_cents,
        "overdue_count": overdue_count,
        "pipeline_cents": pipeline_cents,
        "accepted_quotes_count": quotes_accepted,
        "conversion_rate": round(conversion_rate, 1),
        "collection_rate": round(collection_rate, 1),
        "quotes_by_status": quotes_by_status,
        "invoices_by_status": invoices_by_status,
    }


@router.post("/preview", response_class=HTMLResponse)
async def preview_document_live(
    preview_data: DocumentPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aperçu HTML en temps réel."""
    try:
        doc_type = DocumentType(preview_data.type.upper()) if preview_data.type else DocumentType.DEVIS
    except ValueError:
        doc_type = DocumentType.DEVIS

    template_uuid = None
    if preview_data.template_id:
        try:
            template_uuid = UUID(preview_data.template_id)
        except ValueError:
            template_uuid = None

    html_content = await DocumentService.render_preview(
        db=db,
        user=current_user,
        type=doc_type,
        client_name=preview_data.client_name,
        client_email=preview_data.client_email,
        client_address=preview_data.client_address,
        client_phone=preview_data.client_phone,
        items=[item.model_dump() for item in preview_data.items],
        template_id=template_uuid,
        layout_style=preview_data.layout_style,
        primary_color=preview_data.primary_color,
        secondary_color=preview_data.secondary_color,
        accent_color=preview_data.accent_color,
        text_color=preview_data.text_color,
        background_color=preview_data.background_color,
        font_family=preview_data.font_family,
        header_text=preview_data.header_text,
        footer_text=preview_data.footer_text,
        show_bank_details=preview_data.show_bank_details,
        show_tax_id=preview_data.show_tax_id,
        reference=preview_data.reference,
        payment_schedule=[m.model_dump() for m in preview_data.payment_schedule] if preview_data.payment_schedule else None
    )
    return HTMLResponse(content=html_content)


@router.post("/preview/pdf")
async def preview_document_pdf(
    preview_data: DocumentPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Génère un PDF sans sauvegarder en DB (Playwright)."""
    try:
        doc_type = DocumentType(preview_data.type.upper()) if preview_data.type else DocumentType.DEVIS
    except ValueError:
        doc_type = DocumentType.DEVIS

    template_uuid = None
    if preview_data.template_id:
        try:
            template_uuid = UUID(preview_data.template_id)
        except ValueError:
            template_uuid = None

    html_content = await DocumentService.render_preview(
        db=db,
        user=current_user,
        type=doc_type,
        client_name=preview_data.client_name,
        client_email=preview_data.client_email,
        client_address=preview_data.client_address,
        client_phone=preview_data.client_phone,
        items=[item.model_dump() for item in preview_data.items],
        template_id=template_uuid,
        layout_style=preview_data.layout_style,
        primary_color=preview_data.primary_color,
        secondary_color=preview_data.secondary_color,
        accent_color=preview_data.accent_color,
        text_color=preview_data.text_color,
        background_color=preview_data.background_color,
        font_family=preview_data.font_family,
        header_text=preview_data.header_text,
        footer_text=preview_data.footer_text,
        show_bank_details=preview_data.show_bank_details,
        show_tax_id=preview_data.show_tax_id,
        payment_schedule=[m.model_dump() for m in preview_data.payment_schedule] if preview_data.payment_schedule else None,
        reference=preview_data.reference,
    )

    pdf_buffer = await pdf_renderer.render_pdf_from_html(html_content)

    prefix = "DEV" if doc_type == DocumentType.DEVIS else "FACT"
    filename = f"{preview_data.reference or prefix + '-Brouillon'}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


# ============================================================
# 📄 EMAIL & PARTAGE
# ============================================================

@router.post("/{document_id}/send-email")
async def send_document_email(
    document_id: UUID,
    email_data: DocumentEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"📧 POST /documents/{document_id}/send-email")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if document.status not in [DocumentStatus.DRAFT, DocumentStatus.SENT]:
        raise HTTPException(
            status_code=400,
            detail=f"Ce document ne peut pas être envoyé (statut actuel: {document.status.value})"
        )

    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    to_email = email_data.override_email or client.email
    if not to_email:
        raise HTTPException(status_code=400, detail="Email du client requis")

    if not document.share_token:
        document.share_token = Document.generate_share_token()
        document.share_enabled = True
        document.share_expires_at = to_naive_utc(
            datetime.now(timezone.utc) + timedelta(days=30)
        )

    if not document.client_token:
        document.client_token = Document.generate_share_token()
        document.client_token_email = to_email

    db.add(document)
    await db.commit()
    await db.refresh(document)

    base_url = settings.FRONTEND_URL or "http://localhost:3000"
    client_url = f"{base_url}/client/{document.client_token}"
    share_url = f"{base_url}/view/{document.share_token}"

    totals = DocumentService.calculate_totals(document.items)
    total_amount = f"{totals['grand_total_cents']:,} FCFA"

    due_date_str = None
    if document.due_date:
        due_date_str = document.due_date.strftime("%d/%m/%Y")

    user_name = (
        getattr(current_user, 'full_name', None) or
        getattr(current_user, 'first_name', None) or
        current_user.email.split('@')[0]
    )
    user_company = getattr(current_user, 'company_name', None) or "Sharaco"

    pdf_bytes = None
    if email_data.attach_pdf:
        try:
            template = await TemplateService.get_by_id(db, document.template_id, current_user.id)
            if not template:
                template = await TemplateService.get_default(db, current_user.id)

            pdf_buffer = await pdf_renderer.render_pdf(
                db=db,
                document=document,
                template=template,
                user=current_user,
                client=client,
            )
            pdf_bytes = pdf_buffer.read()
            logger.info(f"📄 PDF généré pour {document.number}")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de générer le PDF: {e}")
            pdf_bytes = None

    try:
        if document.type == DocumentType.DEVIS:
            result = await EmailService.send_devis(
                to_email=to_email,
                client_name=client.name,
                document_number=document.number or str(document_id),
                total_amount=total_amount,
                client_url=client_url,
                due_date=due_date_str,
                user_name=user_name,
                user_company=user_company,
                custom_message=email_data.custom_message or "",
            )
        else:
            result = await EmailService.send_facture(
                to_email=to_email,
                client_name=client.name,
                document_number=document.number or str(document_id),
                total_amount=total_amount,
                client_url=client_url,
                due_date=due_date_str,
                user_name=user_name,
                user_company=user_company,
                custom_message=email_data.custom_message or "",
            )
    except Exception as e:
        logger.error(f"❌ Erreur envoi email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur d'envoi: {str(e)}")

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Erreur d'envoi: {result.get('error', 'Erreur inconnue')}"
        )

    if document.status == DocumentStatus.DRAFT:
        document.status = DocumentStatus.SENT
        document.sent_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(document)
        await db.commit()

        logger.info(
            f"✅ {document.type.value} {document.number} envoyé à {to_email} "
            f"(statut: DRAFT → SENT)"
        )
    else:
        logger.info(
            f"📧 {document.type.value} {document.number} renvoyé à {to_email}"
        )

    return {
        "message": "Email envoyé avec succès",
        "to_email": to_email,
        "document_number": document.number,
        "document_type": document.type.value,
        "client_url": client_url,
        "share_url": share_url,
        "pdf_attached": pdf_bytes is not None,
        "provider": result.get("provider"),
        "email_id": result.get("id"),
    }


@router.post("/{document_id}/share", response_model=dict)
async def generate_share_link(
    document_id: UUID,
    expires_days: int = Query(default=30, ge=1, le=365, description="Durée de validité en jours"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"🔗 POST /documents/{document_id}/share")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    document.share_token = Document.generate_share_token()
    document.share_enabled = True
    document.share_expires_at = to_naive_utc(
        datetime.now(timezone.utc) + timedelta(days=expires_days)
    )

    db.add(document)
    await db.commit()
    await db.refresh(document)

    base_url = settings.FRONTEND_URL or "http://localhost:3000"
    share_url = f"{base_url}/view/{document.share_token}"

    logger.info(f"✅ Lien de partage généré: {share_url}")

    return {
        "share_url": share_url,
        "share_token": document.share_token,
        "expires_at": document.share_expires_at,
    }


@router.delete("/{document_id}/share")
async def revoke_share_link(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"🔗 DELETE /documents/{document_id}/share")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    document.share_token = None
    document.share_enabled = False
    document.share_expires_at = None

    db.add(document)
    await db.commit()

    return {"message": "Lien de partage révoqué"}


# ============================================================
# 📄 ACTIONS CLIENT (accepter/refuser)
# ============================================================

@router.post("/client/{token}/accept")
async def accept_document_as_client(
    token: str,
    data: AcceptDocumentRequest,
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"✅ POST /documents/client/{token[:8]}.../accept")

    result = await db.execute(
        select(Document)
        .options(selectinload(Document.items))
        .where(Document.client_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    if document.type != DocumentType.DEVIS:
        raise HTTPException(status_code=400, detail="Seuls les devis peuvent être acceptés")

    if document.status not in [DocumentStatus.SENT, DocumentStatus.VIEWED]:
        raise HTTPException(
            status_code=400,
            detail=f"Ce document ne peut pas être accepté (statut: {document.status})"
        )

    if document.status == DocumentStatus.ACCEPTED:
        logger.info(f"ℹ️ Document {document.id} déjà accepté")
        return {
            "message": "Devis déjà accepté",
            "status": document.status,
            "accepted_at": document.accepted_at,
            "signature_name": document.signature_name,
            "already_accepted": True,
            "invoice_created": False,
        }

    document.signature_name = data.signature_name
    db.add(document)

    logger.info(f"✍️ Signature enregistrée: '{data.signature_name}'")

    try:
        acceptance_result = await DocumentService.handle_quote_acceptance(
            db=db,
            quote=document,
        )
    except Exception as e:
        logger.error(f"❌ Erreur handle_quote_acceptance: {e}", exc_info=True)
        document.signature_name = data.signature_name
        document.status = DocumentStatus.ACCEPTED
        document.accepted_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(document)
        acceptance_result = {
            "invoice": None,
            "has_schedule": False,
            "auto_sent": False,
        }

    await db.commit()
    await db.refresh(document)

    invoice = acceptance_result.get("invoice")

    logger.info(
        f"✅ Devis {document.id} accepté par '{data.signature_name}'"
        + (f" → facture {invoice.number} créée" if invoice else " (pas de facture auto)")
    )

    return {
        "message": (
            f"Devis accepté avec succès"
            + (f". Facture {invoice.number} créée automatiquement." if invoice else ".")
        ),
        "status": document.status,
        "accepted_at": document.accepted_at,
        "signature_name": document.signature_name,
        "already_accepted": False,
        "invoice_created": invoice is not None,
        "invoice_id": str(invoice.id) if invoice else None,
        "invoice_number": invoice.number if invoice else None,
        "invoice_auto_sent": acceptance_result.get("auto_sent", False),
        "has_schedule": acceptance_result.get("has_schedule", False),
    }


@router.post("/client/{token}/refuse")
async def refuse_document_as_client(
    token: str,
    data: RefuseDocumentRequest,
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"❌ POST /documents/client/{token[:8]}.../refuse")

    result = await db.execute(
        select(Document).where(Document.client_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    if document.status == DocumentStatus.REFUSED:
        return {
            "message": "Devis déjà refusé",
            "status": document.status,
            "refused_at": document.refused_at,
            "already_refused": True,
        }

    if document.status not in [DocumentStatus.SENT, DocumentStatus.VIEWED]:
        raise HTTPException(
            status_code=400,
            detail=f"Ce document ne peut pas être refusé (statut: {document.status.value})"
        )

    document.status = DocumentStatus.REFUSED
    document.refused_at = to_naive_utc(datetime.now(timezone.utc))
    document.refusal_reason = data.reason

    db.add(document)
    await db.commit()

    logger.info(f"❌ Devis {document.id} refusé")

    try:
        await NotificationService.notify_document_refused(document.id, db)
    except Exception as e:
        logger.error(f"❌ Erreur lors de la notification: {e}", exc_info=True)

    return {
        "message": "Devis refusé",
        "status": document.status,
        "refused_at": document.refused_at,
        "already_refused": False,
    }


@router.post("/shared/{token}/refuse")
async def refuse_shared_document(
    token: str,
    data: RefuseDocumentRequest,
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"❌ POST /documents/shared/{token[:8]}.../refuse")

    result = await db.execute(
        select(Document).where(Document.share_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    if document.status not in [DocumentStatus.SENT, DocumentStatus.VIEWED]:
        raise HTTPException(
            status_code=400,
            detail=f"Ce document ne peut pas être refusé (statut actuel: {document.status})"
        )

    document.status = DocumentStatus.REFUSED
    document.refused_at = to_naive_utc(datetime.now(timezone.utc))
    document.refusal_reason = data.reason

    db.add(document)
    await db.commit()

    logger.info(f"❌ Document {document.id} refusé. Raison: {data.reason}")

    return {
        "message": "Document refusé",
        "status": document.status,
        "refused_at": document.refused_at,
    }


# ============================================================
# 📄 VISUALISATION PUBLIQUE & CLIENT
# ============================================================

@router.get("/shared/{token}", response_model=SharedDocumentRead)
async def get_shared_document_public(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Page PUBLIQUE : Visualisation uniquement (lecture seule)."""
    logger.info(f"👁️ GET /documents/shared/{token[:8]}... (public)")

    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.items),
            selectinload(Document.client),
            selectinload(Document.owner),
            selectinload(Document.payment_schedule),
        )
        .where(Document.share_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    if document.status == DocumentStatus.SENT and not document.viewed_at:
        document.status = DocumentStatus.VIEWED
        document.viewed_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(document)
        await db.commit()

    totals = DocumentService.calculate_totals(document.items)

    return {
        "id": document.id,
        "type": document.type,
        "status": document.status,
        "number": document.number,
        "created_at": document.created_at,
        "due_date": document.due_date,
        "layout_style": document.layout_style,
        "notes": document.notes,
        "items": document.items,
        "subtotal_cents": totals["subtotal_cents"],
        "tax_total_cents": totals["tax_total_cents"],
        "grand_total_cents": totals["grand_total_cents"],
        "primary_color": document.primary_color,
        "secondary_color": document.secondary_color,
        "accent_color": document.accent_color,
        "background_color": document.background_color,
        "text_color": document.text_color,
        "font_family": document.font_family,
        "company_name": getattr(document.owner, 'company_name', None) if document.owner else None,
        "company_email": getattr(document.owner, 'email', None) if document.owner else None,
        "company_phone": getattr(document.owner, 'phone', None) if document.owner else None,
        "client_name": document.client.name if document.client else None,
        "client_email": document.client.email if document.client else None,
        "payment_schedule": [
            {
                "id": str(ms.id),
                "sequence": ms.sequence,
                "title": ms.title,
                "percent": ms.percent,
                "amount_cents": ms.amount_cents,
                "description": ms.description,
                "trigger_date": ms.trigger_date.isoformat() if ms.trigger_date else None,
                "status": ms.status if isinstance(ms.status, str) else ms.status.value,
            }
            for ms in sorted(
                document.payment_schedule or [],
                key=lambda x: x.sequence
            )
        ],
        "can_validate": False,
    }


@router.get("/client/{token}", response_model=SharedDocumentRead)
async def get_document_for_client(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Page PRIVÉE CLIENT : Visualisation + Actions (accepter/refuser)."""
    logger.info(f"🔐 GET /documents/client/{token[:8]}... (privé)")

    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.items),
            selectinload(Document.client),
            selectinload(Document.owner),
            selectinload(Document.payment_schedule),
        )
        .where(Document.client_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    totals = DocumentService.calculate_totals(document.items)

    can_validate = document.type == DocumentType.DEVIS and document.status in [
        DocumentStatus.SENT,
        DocumentStatus.VIEWED
    ]

    return {
        "id": document.id,
        "type": document.type,
        "status": document.status,
        "number": document.number,
        "created_at": document.created_at,
        "due_date": document.due_date,
        "layout_style": document.layout_style,
        "notes": document.notes,
        "items": document.items,
        "subtotal_cents": totals["subtotal_cents"],
        "tax_total_cents": totals["tax_total_cents"],
        "grand_total_cents": totals["grand_total_cents"],
        "primary_color": document.primary_color,
        "secondary_color": document.secondary_color,
        "accent_color": document.accent_color,
        "background_color": document.background_color,
        "text_color": document.text_color,
        "font_family": document.font_family,
        "company_name": getattr(document.owner, 'company_name', None) if document.owner else None,
        "company_email": getattr(document.owner, 'email', None) if document.owner else None,
        "company_phone": getattr(document.owner, 'phone', None) if document.owner else None,
        "client_name": document.client.name if document.client else None,
        "client_email": document.client.email if document.client else None,
        "can_validate": True,
        "payment_schedule": [
            {
                "id": str(ms.id),
                "sequence": ms.sequence,
                "title": ms.title,
                "percent": ms.percent,
                "amount_cents": ms.amount_cents,
                "description": ms.description,
                "trigger_date": ms.trigger_date.isoformat() if ms.trigger_date else None,
                "status": ms.status if isinstance(ms.status, str) else ms.status.value,
            }
            for ms in sorted(
                document.payment_schedule or [],
                key=lambda x: x.sequence
            )
        ],
        "accepted_at": document.accepted_at,
        "refused_at": document.refused_at,
        "signature_name": document.signature_name,
    }


# ═══════════════════════════════════════════════════════════
# 🧾 FACTURE PUBLIQUE (avec échéancier du devis parent)
# ═══════════════════════════════════════════════════════════
@router.get("/invoices/public/{token}")
async def get_public_invoice(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Vue PUBLIQUE d'une facture avec échéancier interactif.
    Accessible via share_token ou client_token.
    """
    logger.info(f"🧾 GET /invoices/public/{token[:8]}...")

    # Chercher par share_token OU client_token
    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.items),
            selectinload(Document.client),
            selectinload(Document.owner),
        )
        .where(
            (Document.share_token == token) | (Document.client_token == token)
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Facture introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    if document.type != DocumentType.FACTURE:
        raise HTTPException(
            status_code=400,
            detail="Cet endpoint est réservé aux factures"
        )

    # Marquer comme vue si envoyé + première consultation
    if document.status == DocumentStatus.SENT and not document.viewed_at:
        document.status = DocumentStatus.VIEWED
        document.viewed_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(document)

    # Construire l'échéancier du devis parent
    schedule_context = await _build_public_schedule_context(db, document)

    totals = DocumentService.calculate_totals(document.items)

    await db.commit()

    return {
        # ─── Document ───
        "document": {
            "id": str(document.id),
            "type": document.type.value if hasattr(document.type, "value") else str(document.type),
            "status": document.status.value if hasattr(document.status, "value") else str(document.status),
            "number": document.number,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "due_date": document.due_date.isoformat() if document.due_date else None,
            "notes": document.notes,
            "layout_style": document.layout_style,
        },
        # ─── Client ───
        "client": {
            "name": document.client.name if document.client else None,
            "email": document.client.email if document.client else None,
            "phone": getattr(document.client, "phone", None) if document.client else None,
            "address": document.client.address if document.client else None,
        } if document.client else None,
        # ─── Émetteur (pro) ───
        "company": {
            "name": getattr(document.owner, "company_name", None) if document.owner else None,
            "email": getattr(document.owner, "email", None) if document.owner else None,
            "phone": getattr(document.owner, "phone", None) if document.owner else None,
            "address": getattr(document.owner, "address", None) if document.owner else None,
            "tax_id": getattr(document.owner, "tax_id", None) if document.owner else None,
            "payment_info": getattr(document.owner, "payment_info", None) if document.owner else None,
        } if document.owner else None,
        # ─── Items ───
        "items": [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "tax_rate": item.tax_rate,
                "total_cents": item.quantity * item.unit_price_cents,
            }
            for item in (document.items or [])
        ],
        # ─── Totaux ───
        "totals": {
            "subtotal_cents": totals["subtotal_cents"],
            "tax_total_cents": totals["tax_total_cents"],
            "grand_total_cents": totals["grand_total_cents"],
        },
        # ─── Style ───
        "primary_color": document.primary_color or "#2563EB",
        "secondary_color": document.secondary_color or "#1E40AF",
        "accent_color": document.accent_color or "#DBEAFE",
        "background_color": document.background_color or "#FFFFFF",
        "text_color": document.text_color or "#1F2937",
        "font_family": document.font_family or "Inter",
        "currency": getattr(document.owner, "currency", "XOF") if document.owner else "XOF",
        # ─── Échéancier ───
        **schedule_context,
    }


async def _build_public_schedule_context(db: AsyncSession, document: Document) -> dict:
    """
    Construit le contexte 'Suivi de paiement' pour la vue publique d'une facture.
    Remonte au devis parent et lit son échéancier.
    """
    empty = {
        "payment_schedule": None,
        "has_schedule": False,
    }

    # Uniquement pour les factures rattachées à un devis
    if document.type != DocumentType.FACTURE or not document.source_document_id:
        return empty

    # Charger le devis parent avec son échéancier
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.payment_schedule))
        .where(Document.id == document.source_document_id)
    )
    quote = result.scalar_one_or_none()

    if not quote:
        return empty

    milestones = list(quote.payment_schedule or [])

    # Pas d'affichage si pas d'échéancier ou une seule tranche (100%)
    if not milestones or len(milestones) < 2:
        return empty

    # Trier par sequence
    milestones_sorted = sorted(milestones, key=lambda m: m.sequence)

    # Calcul des totaux
    total_cents = sum(m.amount_cents or 0 for m in milestones_sorted)
    paid_cents = sum(
        m.amount_cents or 0
        for m in milestones_sorted
        if (
            (hasattr(m.status, "value") and m.status.value == "PAID")
            or (isinstance(m.status, str) and m.status == "PAID")
        )
    )

    rows = []
    for m in milestones_sorted:
        status_str = m.status.value if hasattr(m.status, "value") else str(m.status)
        rows.append({
            "sequence": m.sequence,
            "title": m.title,
            "percent": m.percent,
            "amount_cents": m.amount_cents or 0,
            "status": status_str,
            "paid_at": m.paid_at.isoformat() if m.paid_at else None,
            "trigger_date": m.trigger_date.isoformat() if m.trigger_date else None,
            "is_current": m.invoice_id == document.id,
        })

    paid_percent = int(round(paid_cents / total_cents * 100)) if total_cents else 0

    return {
        "payment_schedule": {
            "milestones": rows,
            "total_cents": total_cents,
            "paid_cents": paid_cents,
            "paid_percent": paid_percent,
            "remaining_cents": total_cents - paid_cents,
            "source_quote_number": quote.number,
        },
        "has_schedule": True,
    }


# ============================================================
# 📄 GÉNÉRATION DE FACTURES & PAIEMENT
# ============================================================

@router.post("/{document_id}/next-invoice", response_model=dict)
async def generate_next_invoice(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.invoiceService import InvoiceService

    logger.info(f"💰 POST /documents/{document_id}/next-invoice")

    quote = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not quote:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if quote.type != DocumentType.DEVIS:
        raise HTTPException(status_code=400, detail="Seuls les devis supportent cette action")

    if quote.status != DocumentStatus.ACCEPTED:
        raise HTTPException(status_code=400, detail="Le devis doit être accepté")

    stmt = (
        select(PaymentSchedule)
        .where(PaymentSchedule.document_id == quote.id)
        .order_by(PaymentSchedule.sequence.asc())
    )
    result = await db.execute(stmt)
    milestones = list(result.scalars().all())

    if not milestones:
        raise HTTPException(status_code=400, detail="Ce devis n'a pas d'échéancier")

    next_milestone = None

    for milestone in milestones:
        if milestone.status == MilestoneStatus.PENDING:
            prev_index = milestone.sequence - 2
            if prev_index >= 0:
                prev_milestone = milestones[prev_index]
                if prev_milestone.status != MilestoneStatus.PAID:
                    raise HTTPException(
                        status_code=400,
                        detail=f"La milestone '{prev_milestone.title}' doit être payée avant de facturer la suivante"
                    )
            next_milestone = milestone
            break

    if not next_milestone:
        raise HTTPException(
            status_code=400,
            detail="Toutes les milestones ont déjà été facturées"
        )

    try:
        invoice = await InvoiceService.create_from_milestone(
            db=db,
            quote=quote,
            milestone=next_milestone,
            origin="manual",
        )

        next_milestone.status = MilestoneStatus.INVOICED
        next_milestone.invoice_id = invoice.id
        next_milestone.invoiced_at = to_naive_utc(datetime.now(timezone.utc))
        db.add(next_milestone)

        await db.commit()

        logger.info(
            f"✅ Facture {invoice.number} créée pour milestone "
            f"'{next_milestone.title}' ({next_milestone.percent}%)"
        )

        return {
            "message": f"Facture {invoice.number} créée ({next_milestone.title})",
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.number,
            "milestone_title": next_milestone.title,
            "milestone_percent": next_milestone.percent,
            "milestone_amount_cents": next_milestone.amount_cents,
            "remaining_milestones": sum(
                1 for m in milestones if m.status == MilestoneStatus.PENDING
            ),
        }
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Erreur génération facture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur lors de la génération de la facture")


@router.post("/invoices/{invoice_id}/mark-paid")
async def mark_invoice_as_paid(
    invoice_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"💳 POST /invoices/{invoice_id}/mark-paid")

    invoice = await DocumentService.get_by_id(db, invoice_id, current_user.id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")

    if invoice.type != DocumentType.FACTURE:
        raise HTTPException(status_code=400, detail="Ce document n'est pas une facture")

    if invoice.status == DocumentStatus.PAID:
        return {
            "message": "Facture déjà payée",
            "already_paid": True,
        }

    now = to_naive_utc(datetime.now(timezone.utc))
    invoice.status = DocumentStatus.PAID
    invoice.paid_at = now
    db.add(invoice)

    stmt = select(PaymentSchedule).where(PaymentSchedule.invoice_id == invoice_id)
    result = await db.execute(stmt)
    milestone = result.scalar_one_or_none()

    if milestone:
        milestone.status = MilestoneStatus.PAID
        milestone.paid_at = now
        db.add(milestone)
        logger.info(f"✅ Milestone '{milestone.title}' marquée comme PAID")

    await db.commit()
    await db.refresh(invoice)

    return {
        "message": f"Facture {invoice.number} marquée comme payée",
        "invoice_number": invoice.number,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "milestone_updated": milestone is not None,
        "already_paid": False,
    }


# ============================================================
# 📄 PDF & PREVIEW pour documents sauvegardés
# ============================================================

@router.get("/{document_id}/pdf")
async def get_document_pdf(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"📄 GET /{document_id}/pdf")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    template = await _get_document_template(db, document, current_user)

    logger.info(f"📄 Template layout_style: {template.layout_style}")

    pdf_buffer = await pdf_renderer.render_pdf(
        document=document,
        template=template,
        user=current_user,
        client=client,
        db=db,
    )

    filename = f"{document.number or 'document'}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/{document_id}/preview", response_class=HTMLResponse)
async def preview_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    template = await _get_document_template(db, document, current_user)

    html_content = await pdf_renderer.render_html(
        document=document,
        template=template,
        user=current_user,
        client=client,
        db=db,
    )
    return HTMLResponse(content=html_content)


# ============================================================
# 📄 CRUD DOCUMENTS
# ============================================================

@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"🔍 GET /{document_id} - user: {current_user.id}")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        logger.warning(f"⚠️ Document {document_id} non trouvé pour user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


@router.put("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: UUID,
    document_data: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"🔄 PUT /{document_id}")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if document_data.client_id is not None:
        client = await ClientService.get_by_id(db, document_data.client_id, current_user.id)
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")

    if document_data.payment_schedule is not None:
        try:
            await PaymentScheduleService.set_schedule(
                db,
                document,
                [m.model_dump() for m in document_data.payment_schedule],
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        updated = await DocumentService.update_document(
            db=db,
            document=document,
            client_id=document_data.client_id,
            template_id=document_data.template_id,
            layout_style=document_data.layout_style,
            due_date=document_data.due_date,
            items=[item.model_dump() for item in document_data.items] if document_data.items else None,
            notes=document_data.notes,
            primary_color=document_data.primary_color,
            secondary_color=document_data.secondary_color,
            accent_color=document_data.accent_color,
            background_color=document_data.background_color,
            text_color=document_data.text_color,
            font_family=document_data.font_family,
            show_bank_details=document_data.show_bank_details,
            show_tax_id=document_data.show_tax_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    totals = DocumentService.calculate_totals(updated.items)
    return _enrich_document(updated, totals)


@router.patch("/{document_id}/status", response_model=DocumentRead)
async def update_document_status(
    document_id: UUID,
    status_data: DocumentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    try:
        updated = await DocumentService.update_status(
            db=db,
            document=document,
            new_status=status_data.status,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    totals = DocumentService.calculate_totals(updated.items)
    return _enrich_document(updated, totals)


@router.patch("/{document_id}/project", response_model=DocumentRead)
async def link_document_to_project(
    document_id: UUID,
    link_data: DocumentProjectLink,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"🔗 PATCH /documents/{document_id}/project")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if link_data.project_id:
        from app.models.projet import Project
        project_result = await db.execute(
            select(Project).where(
                Project.id == link_data.project_id,
                Project.user_id == current_user.id
            )
        )
        if not project_result.scalar_one_or_none():
            raise HTTPException(
                status_code=404,
                detail="Projet introuvable ou n'appartient pas à cet utilisateur"
            )

    document.project_id = link_data.project_id
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(f"✅ Document {document_id} associé au projet {link_data.project_id}")

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


@router.delete("/{document_id}/project", response_model=DocumentRead)
async def unlink_document_from_project(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f" DELETE /documents/{document_id}/project")

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.project_id:
        raise HTTPException(
            status_code=400,
            detail="Ce document n'est pas associé à un projet"
        )

    document.project_id = None
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(f"✅ Document {document_id} dissocié du projet")

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


@router.post("/{document_id}/convert", response_model=DocumentRead)
async def convert_to_invoice(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    try:
        invoice = await DocumentService.duplicate_as_invoice(db, document)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    totals = DocumentService.calculate_totals(invoice.items)
    return _enrich_document(invoice, totals)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await DocumentService.delete_document(db, document_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/client/{token}/preview", response_class=HTMLResponse)
async def preview_document_for_client(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Aperçu HTML d'un document pour le client (pas d'authentification requise).
    Utilisé sur la page /client/{token} pour afficher le rendu du document.
    """
    logger.info(f"👁️ GET /client/{token[:8]}.../preview (public)")

    # 1. Charger le document via le token client
    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.items),
            selectinload(Document.client),
            selectinload(Document.owner),
            selectinload(Document.payment_schedule),
        )
        .where(Document.client_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    # 2. Récupérer le template
    template = await _get_document_template(db, document, document.owner)

    # 3. Rendre le HTML (avec suivi de paiement pour les factures)
    html_content = await pdf_renderer.render_html(
        document=document,
        template=template,
        user=document.owner,
        client=document.client,
        db=db,
    )

    return HTMLResponse(content=html_content)

@router.get("/shared/{token}/preview", response_class=HTMLResponse)
async def preview_shared_document(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Aperçu HTML d'un document partagé (lien public, sans auth).
    """
    logger.info(f"👁️ GET /shared/{token[:8]}.../preview (public)")

    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.items),
            selectinload(Document.client),
            selectinload(Document.owner),
            selectinload(Document.payment_schedule),
        )
        .where(Document.share_token == token)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if not document.share_enabled:
        raise HTTPException(status_code=403, detail="Partage désactivé")

    if document.share_expires_at:
        now = to_naive_utc(datetime.now(timezone.utc))
        if now > document.share_expires_at:
            raise HTTPException(status_code=410, detail="Lien expiré")

    template = await _get_document_template(db, document, document.owner)

    html_content = await pdf_renderer.render_html(
        document=document,
        template=template,
        user=document.owner,
        client=document.client,
        db=db,
    )

    return HTMLResponse(content=html_content)
# ============================================================
# 📄 PREVIEW PNG
# ============================================================

@router.get("/{document_id}/preview.png")
async def get_document_preview_png(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Génère (ou sert depuis le cache) la preview PNG d'un document."""
    logger.info(f"🖼️ GET /{document_id}/preview.png")

    # ✅ Charger avec items + schedule (nécessaires pour le hash de cache)
    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.items),
            selectinload(Document.payment_schedule),
        )
        .where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    template = await _get_document_template(db, document, current_user)

    # ✅ Passe par le cache intelligent
    png_bytes = await pdf_renderer.get_or_render_document_png(
        db=db,
        document=document,
        template=template,
        user=current_user,
        client=client,
    )

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            # Cache navigateur court : le cache serveur fait le gros du travail
            "Cache-Control": "private, max-age=30, must-revalidate",
            "Content-Disposition": f'inline; filename="preview-{document_id}.png"',
        },
    )


# ============================================================
# 📄 LISTE ET CRÉATION
# ============================================================

@router.get("/", response_model=list[DocumentListRead])
async def list_documents(
    type: Optional[DocumentType] = Query(None),
    status: Optional[DocumentStatus] = Query(None),
    client_id: Optional[UUID] = Query(None),
    project_id: Optional[UUID] = Query(None, description="Filtrer par projet"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    documents = await DocumentService.get_all(
        db=db,
        user_id=current_user.id,
        type=type,
        status=status,
        client_id=client_id,
        project_id=project_id,
        skip=skip,
        limit=limit,
    )

    result = []
    for doc in documents:
        totals = DocumentService.calculate_totals(doc.items)

        client_data = None
        if doc.client:
            client_data = {
                "id": doc.client.id,
                "name": doc.client.name,
                "email": doc.client.email,
            }
        result.append({
            "id": doc.id,
            "type": doc.type,
            "status": doc.status,
            "number": doc.number,
            "created_at": doc.created_at,
            "due_date": doc.due_date,
            "client_id": doc.client_id,
            "template_id": doc.template_id,
            "layout_style": doc.layout_style,
            "grand_total_cents": totals["grand_total_cents"],
            "client": client_data,
            "project_id": getattr(doc, 'project_id', None)
        })
    return result


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_data: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(f"✨ POST / - Création document, layout: {document_data.layout_style}")

    from app.models.client import Client
    from app.models.projet import Project

    client_id = document_data.client_id

    if not client_id:
        if document_data.project_id:
            project_result = await db.execute(
                select(Project).where(
                    Project.id == document_data.project_id,
                    Project.user_id == current_user.id
                )
            )
            project = project_result.scalar_one_or_none()
            if project:
                client_id = project.client_id
                logger.info(f"📋 Client récupéré depuis le projet: {client_id}")

        if not client_id:
            result = await db.execute(
                select(Client)
                .where(Client.user_id == current_user.id)
                .limit(1)
            )
            first_client = result.scalar_one_or_none()

            if not first_client:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Aucun client trouvé. Veuillez créer un client avant de créer un devis."
                )

            client_id = first_client.id
            logger.info(f"📋 Premier client utilisé: {first_client.name}")
    else:
        client = await ClientService.get_by_id(db, client_id, current_user.id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client introuvable"
            )

    if document_data.project_id:
        project_result = await db.execute(
            select(Project).where(
                Project.id == document_data.project_id,
                Project.user_id == current_user.id
            )
        )
        if not project_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Projet introuvable ou n'appartient pas à cet utilisateur"
            )

    try:
        document = await DocumentService.create_document(
            db=db,
            type=document_data.type,
            user_id=current_user.id,
            client_id=client_id,
            items=[item.model_dump() for item in document_data.items],
            layout_style=document_data.layout_style,
            template_id=document_data.template_id,
            due_date=document_data.due_date,
            notes=document_data.notes,
            document_id=document_data.id,
            project_id=document_data.project_id,
        )
        if document_data.payment_schedule:
            try:
                await PaymentScheduleService.set_schedule(
                    db,
                    document,
                    [m.model_dump() for m in document_data.payment_schedule],
                )
                await db.commit()
                await db.refresh(document, ['items', 'payment_schedule'])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

    document = await DocumentService.get_by_id(db, document.id, current_user.id)
    if not document:
        raise HTTPException(status_code=500, detail="Document créé mais non récupérable")

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


# ============================================================
# 📄 HELPERS
# ============================================================

def _enrich_document(doc, totals: dict) -> dict:
    return {
        "id": doc.id,
        "type": doc.type,
        "status": doc.status,
        "number": doc.number,
        "created_at": doc.created_at,
        "due_date": doc.due_date,
        "user_id": doc.user_id,
        "client": {
            "id": str(doc.client.id) if doc.client else None,
            "name": doc.client.name if doc.client else None,
            "email": doc.client.email if doc.client else None,
            "phone": doc.client.phone if doc.client else None,
            "address": doc.client.address if doc.client else None,
        } if doc.client else None,
        "client_id": doc.client_id,
        "template_id": doc.template_id,
        "layout_style": getattr(doc, 'layout_style', 'classic'),
        "notes": doc.notes,
        "items": doc.items,
        "project_id": getattr(doc, 'project_id', None),
        "primary_color": getattr(doc, 'primary_color', '#2563EB'),
        "secondary_color": getattr(doc, 'secondary_color', '#1E40AF'),
        "accent_color": getattr(doc, 'accent_color', '#DBEAFE'),
        "background_color": getattr(doc, 'background_color', '#FFFFFF'),
        "text_color": getattr(doc, 'text_color', '#1F2937'),
        "font_family": getattr(doc, 'font_family', 'Inter'),
        "show_bank_details": getattr(doc, 'show_bank_details', True),
        "show_tax_id": getattr(doc, 'show_tax_id', True),
        "payment_schedule": [
            {
                "id": ms.id,
                "sequence": ms.sequence,
                "title": ms.title,
                "percent": ms.percent,
                "amount_cents": ms.amount_cents,
                "description": ms.description,
                "trigger_date": ms.trigger_date.isoformat() if ms.trigger_date else None,
                "status": ms.status if isinstance(ms.status, str) else ms.status.value,
                "invoice_id": ms.invoice_id,
                "invoiced_at": ms.invoiced_at.isoformat() if ms.invoiced_at else None,
                "paid_at": ms.paid_at.isoformat() if ms.paid_at else None,
            }
            for ms in sorted(
                doc.payment_schedule or [],
                key=lambda x: x.sequence
            )
        ],
        "subtotal_cents": totals["subtotal_cents"],
        "tax_total_cents": totals["tax_total_cents"],
        "grand_total_cents": totals["grand_total_cents"],
    }


async def _get_document_template(db: AsyncSession, document, user: User):
    if document.template_id:
        tmpl = await TemplateService.get_by_id(db, document.template_id, user.id)
        if tmpl:
            return tmpl

    default_tmpl = await TemplateService.get_default(db, user.id)
    if default_tmpl:
        return default_tmpl

    from app.models.document_template import DocumentTemplate
    from uuid import uuid4
    return DocumentTemplate(
        id=uuid4(),
        name=f"Template {getattr(document, 'layout_style', 'classic')}",
        user_id=user.id,
        primary_color="#2563EB",
        layout_style=getattr(document, 'layout_style', 'classic'),
        secondary_color="#1E40AF",
        accent_color="#DBEAFE",
        text_color="#1F2937",
        background_color="#FFFFFF",
        font_family="Inter",
        show_bank_details=True,
        show_tax_id=True,
        is_default=True,
    )