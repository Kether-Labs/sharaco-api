from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.templateService import TemplateService
from app.schemas.document_template import DocumentTemplateCreate, DocumentTemplateRead, DocumentTemplateUpdate

router = APIRouter(tags=["templates"])


@router.post("/", response_model=DocumentTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    template_data: DocumentTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Créer un nouveau modèle de design pour les devis/factures."""
    template = await TemplateService.create_template(
        db=db,
        name=template_data.name,
        user_id=current_user.id,
        primary_color=template_data.primary_color,
        secondary_color=template_data.secondary_color,
        accent_color=template_data.accent_color,
        text_color=template_data.text_color,
        background_color=template_data.background_color,
        logo_url=template_data.logo_url,
        font_family=template_data.font_family,
        header_text=template_data.header_text,
        footer_text=template_data.footer_text,
        show_bank_details=template_data.show_bank_details,
        show_tax_id=template_data.show_tax_id,
        layout_style=template_data.layout_style,
        is_default=template_data.is_default,
    )
    return template


@router.get("/", response_model=list[DocumentTemplateRead])
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste tous les modèles de design de l'utilisateur."""
    templates = await TemplateService.get_all(db=db, user_id=current_user.id)
    return templates


@router.get("/default", response_model=DocumentTemplateRead)
async def get_default_template(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupère le modèle de design par défaut."""
    template = await TemplateService.get_default(db=db, user_id=current_user.id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun modèle par défaut trouvé",
        )
    return template


@router.get("/{template_id}", response_model=DocumentTemplateRead)
async def get_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupérer les détails d'un modèle de design."""
    template = await TemplateService.get_by_id(db, template_id, current_user.id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modèle introuvable",
        )
    return template


@router.put("/{template_id}", response_model=DocumentTemplateRead)
async def update_template(
    template_id: UUID,
    template_data: DocumentTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifier un modèle de design existant."""
    template = await TemplateService.get_by_id(db, template_id, current_user.id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modèle introuvable",
        )

    updated = await TemplateService.update_template(
        db=db,
        template=template,
        **template_data.model_dump(exclude_unset=True),
    )
    return updated


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Supprimer un modèle de design."""
    template = await TemplateService.get_by_id(db, template_id, current_user.id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modèle introuvable",
        )

    await TemplateService.delete_template(db, template)
