from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.reminderService import reminder_service
from app.services.documentService import DocumentService
from app.services.clientService import ClientService
from app.services.pdfRenderer import pdf_renderer
from app.services.templateService import TemplateService
from app.schemas.reminder import ReminderConfigCreate, ReminderConfigRead, ReminderConfigUpdate, ReminderLogRead

router = APIRouter(tags=["reminders"])


# ============================================================
# CONFIGURATION DES RELANCES
# ============================================================

@router.get("/config", response_model=ReminderConfigRead)
async def get_reminder_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupérer la configuration des relances automatiques."""
    config = await reminder_service.get_or_create_config(db, current_user.id)
    return config


@router.put("/config", response_model=ReminderConfigRead)
async def update_reminder_config(
    config_data: ReminderConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifier la configuration des relances."""
    config = await reminder_service.get_or_create_config(db, current_user.id)
    updated = await reminder_service.update_config(
        db=db,
        config=config,
        **config_data.model_dump(exclude_unset=True),
    )
    return updated


# ============================================================
# ENVOI DE DOCUMENT PAR EMAIL
# ============================================================

@router.post("/documents/{document_id}/send")
async def send_document_email(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Envoyer un devis/facture par email au client. Change le statut en SENT."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    if document.status.value not in ("DRAFT", "SENT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce document ne peut pas être envoyé",
        )

    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client or not client.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le client n'a pas d'adresse email",
        )

    try:
        result = await reminder_service.send_document(
            db=db,
            document=document,
            user=current_user,
            client=client,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'envoi : {str(e)}",
        )

    return {"message": "Document envoyé avec succès", "email_id": result.get("id")}


# ============================================================
# RELANCES MANUELLES
# ============================================================

@router.post("/documents/{document_id}/remind/{level}")
async def send_reminder(
    document_id: UUID,
    level: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Envoyer manuellement une relance (niveau 1, 2 ou 3)."""
    if level not in (1, 2, 3):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le niveau de relance doit être 1, 2 ou 3",
        )

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    if document.status == DocumentStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de relancer un brouillon",
        )

    client = await ClientService.get_by_id(db, document.client_id, current_user.id)
    if not client or not client.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le client n'a pas d'adresse email",
        )

    try:
        log = await reminder_service.send_reminder(
            db=db,
            document=document,
            user=current_user,
            client=client,
            reminder_level=level,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la relance : {str(e)}",
        )

    return {"message": f"Relance niveau {level} envoyée", "log_id": str(log.id)}


# ============================================================
# HISTORIQUE DES RELANCES
# ============================================================

@router.get("/documents/{document_id}/history", response_model=list[ReminderLogRead])
async def get_reminder_history(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Historique des relances pour un document."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    logs = await reminder_service.get_reminder_history(db, document_id)
    return logs


# ============================================================
# TRACKING D'OUVERTURE (pixel + page publique)
# ============================================================

@router.get("/track/{document_id}.png")
async def track_pixel(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Pixel de tracking 1x1 — enregistre l'ouverture du document."""
    ip_address = request.client.host if request else None
    user_agent = request.headers.get("user-agent") if request else None

    await reminder_service.track_view(db, document_id, ip_address, user_agent)

    # Retourner un pixel transparent 1x1 PNG
    pixel = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001"
        "08060000001f15c4890000000a49444154789c62000100"
        "00510001270624c80000000049454e44ae426082"
    )
    return Response(content=pixel, media_type="image/png")


@router.get("/public/{document_id}", response_class=HTMLResponse)
async def public_document_view(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """Vue publique du document pour le client (lien dans l'email)."""
    from app.services.documentService import DocumentService as DS
    from sqlmodel import select
    from app.models.document import Document

    # Récupérer le document sans vérification d'appartenance
    statement = select(Document).where(Document.id == document_id)
    result = await db.execute(statement)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    # Tracker la vue
    ip_address = request.client.host if request else None
    user_agent = request.headers.get("user-agent") if request else None
    await reminder_service.track_view(db, document_id, ip_address, user_agent)

    # Récupérer le user et le client
    from app.services.userService import UserService
    user = await UserService.get_by_id(db, str(document.user_id))
    client = await ClientService.get_by_id(db, document.client_id, document.user_id)

    if not user or not client:
        raise HTTPException(status_code=404, detail="Données introuvables")

    # Récupérer le template
    template = await _get_doc_template(db, document, user)

    # Rendre le HTML
    html = pdf_renderer.render_html(document, template, user, client)

    # Injecter le pixel de tracking dans le HTML
    tracking_pixel = f'<img src="/api/v1/reminders/track/{document_id}.png" width="1" height="1" style="display:none;">'
    html = html.replace("</body>", f"{tracking_pixel}</body>")

    return HTMLResponse(content=html)


async def _get_doc_template(db, document, user):
    """Helper pour récupérer le template de design."""
    if document.template_id:
        tmpl = await TemplateService.get_by_id(db, document.template_id, user.id)
        if tmpl:
            return tmpl
    default = await TemplateService.get_default(db, user.id)
    if default:
        return default
    from app.models.document_template import DocumentTemplate
    return DocumentTemplate(
        name="Par defaut", user_id=user.id, primary_color="#2563EB",
        secondary_color="#1E40AF", accent_color="#DBEAFE",
        text_color="#1F2937", background_color="#FFFFFF",
        font_family="Inter", layout_style="classic",
        show_bank_details=True, show_tax_id=True, is_default=True,
    )
