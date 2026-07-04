from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import Response
from app.services.pdfRenderer import pdf_renderer
from uuid import UUID
from typing import Optional
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.document import DocumentType, DocumentStatus
from app.services.documentService import DocumentService
from app.services.templateService import TemplateService
from app.schemas.document import (
    DocumentCreate,
    DocumentRead,
    DocumentUpdate,
    DocumentStatusUpdate,
    DocumentListRead,
    DocumentProjectLink,
    DocumentPreviewRequest,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.document import Document

import logging

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


# ============================================================
# 📄 LIVE PREVIEW (pas de sauvegarde DB) - DOIT ÊTRE EN PREMIER
# ============================================================

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
    )
    return HTMLResponse(content=html_content)


@router.post("/preview/pdf")
async def preview_document_pdf(
    preview_data: DocumentPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Génère un PDF sans sauvegarder en DB (Playwright)."""
    logger.info(f"📄 POST /preview/pdf - layout_style: {preview_data.layout_style}")
    
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
    )

    # ✅ CORRECTION : Utiliser render_pdf_from_html au lieu de render_preview_html
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
# 📄 PDF & PREVIEW pour documents sauvegardés
# ============================================================

@router.get("/{document_id}/pdf")
async def get_document_pdf(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Générer le PDF d'un document sauvegardé."""
    logger.info(f"📄 GET /{document_id}/pdf - layout_style: {getattr(document_id, 'layout_style', 'unknown')}")
    
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    from app.services.clientService import ClientService
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
    """Aperçu HTML d'un document sauvegardé."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    from app.services.clientService import ClientService
    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    template = await _get_document_template(db, document, current_user)

    html_content = pdf_renderer.render_html(
        document=document,
        template=template,
        user=current_user,
        client=client,
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
    """Récupérer les détails d'un document."""
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
    """Mise à jour complète d'un document."""
    logger.info(f"🔄 PUT /{document_id}")
    
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if document_data.client_id is not None:
        from app.services.clientService import ClientService
        client = await ClientService.get_by_id(db, document_data.client_id, current_user.id)
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")

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
            # ✅ NOUVEAU : Passer les champs de style
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
    """Changer le statut d'un document."""
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


# app/api/v1/document.py

@router.patch("/{document_id}/project", response_model=DocumentRead)
async def link_document_to_project(
    document_id: UUID,
    link_data: DocumentProjectLink,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Associer un document à un projet (ou retirer l'association)."""
    logger.info(f"🔗 PATCH /documents/{document_id}/project")
    
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    
    # Vérifier que le projet (si fourni) appartient à l'utilisateur
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
    
    # Mettre à jour le project_id
    document.project_id = link_data.project_id
    db.add(document)
    await db.commit()
    await db.refresh(document)
    
    logger.info(f"✅ Document {document_id} associé au projet {link_data.project_id}")
    
    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


@router.post("/{document_id}/convert", response_model=DocumentRead)
async def convert_to_invoice(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Convertir un devis en facture."""
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
    """Supprimer un document."""
    try:
        await DocumentService.delete_document(db, document_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

# ============================================================
# 📄 LISTE ET CRÉATION
# ============================================================
@router.get("/{document_id}/preview.png")
async def get_document_preview_png(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Génère une image PNG de preview d'un document sauvegardé."""
    logger.info(f"🖼️ GET /{document_id}/preview.png")
    
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    from app.services.clientService import ClientService
    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    template = await _get_document_template(db, document, current_user)
    
    logger.info(f"🖼️ Template layout_style: {template.layout_style}")

    # Générer le HTML
    html_content = pdf_renderer.render_html(
        document=document,
        template=template,
        user=current_user,
        client=client,
    )

    # Générer le PNG
    png_bytes = await pdf_renderer.render_png_from_html(html_content)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",  # Cache 1 heure
            "Content-Disposition": f'inline; filename="preview-{document_id}.png"'
        }
    )

    
@router.get("/", response_model=list[DocumentListRead])
async def list_documents(
    type: Optional[DocumentType] = Query(None),
    status: Optional[DocumentStatus] = Query(None),
    client_id: Optional[UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste les documents."""
    documents = await DocumentService.get_all(
        db=db,
        user_id=current_user.id,
        type=type,
        status=status,
        client_id=client_id,
        skip=skip,
        limit=limit,
    )

    result = []
    for doc in documents:
        totals = DocumentService.calculate_totals(doc.items)
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
        })
    return result


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_data: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Créer un nouveau devis ou facture."""
    logger.info(f"✨ POST / - Création document, layout: {document_data.layout_style}")
    
    from app.services.clientService import ClientService
    from app.models.client import Client
    from app.models.projet import Project
    
    # Déterminer le client
    client_id = document_data.client_id
    
    if not client_id:
        # Si un projet est fourni, utiliser le client du projet
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
        
        # Sinon, prendre le premier client de l'utilisateur
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
        # Vérifier que le client appartient à l'utilisateur
        client = await ClientService.get_by_id(db, client_id, current_user.id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client introuvable"
            )
    
    # ✅ Vérifier que le projet (si fourni) appartient à l'utilisateur
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
            # ✅ NOUVEAU : Passer le project_id
            project_id=document_data.project_id,
        )
        logger.info(f"✅ Document créé: {document.id}")
    except ValueError as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


# ============================================================
# 📄 HELPERS
# ============================================================

def _enrich_document(doc, totals: dict) -> dict:
    """Ajoute les totaux calculés au document."""
    return {
        "id": doc.id,
        "type": doc.type,
        "status": doc.status,
        "number": doc.number,
        "created_at": doc.created_at,
        "due_date": doc.due_date,
        "user_id": doc.user_id,
        "client_id": doc.client_id,
        "template_id": doc.template_id,
        "layout_style": getattr(doc, 'layout_style', 'classic'),
        "notes": doc.notes,
        "items": doc.items,
        # ✅ NOUVEAU : Retourner les couleurs
        "primary_color": getattr(doc, 'primary_color', '#2563EB'),
        "secondary_color": getattr(doc, 'secondary_color', '#1E40AF'),
        "accent_color": getattr(doc, 'accent_color', '#DBEAFE'),
        "background_color": getattr(doc, 'background_color', '#FFFFFF'),
        "text_color": getattr(doc, 'text_color', '#1F2937'),
        "font_family": getattr(doc, 'font_family', 'Inter'),
        "show_bank_details": getattr(doc, 'show_bank_details', True),
        "show_tax_id": getattr(doc, 'show_tax_id', True),
        # Totaux
        "subtotal_cents": totals["subtotal_cents"],
        "tax_total_cents": totals["tax_total_cents"],
        "grand_total_cents": totals["grand_total_cents"],
    }


async def _get_document_template(db: AsyncSession, document, user: User):
    """Récupère le template du document."""
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