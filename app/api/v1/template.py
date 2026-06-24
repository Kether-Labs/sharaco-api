from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.document_template import DocumentTemplate
from app.services.templateService import TemplateService
from app.services.pdfRenderer import pdf_renderer
from app.schemas.document_template import DocumentTemplateCreate, DocumentTemplateRead, DocumentTemplateUpdate
from fastapi.responses import Response
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["templates"])


# ============================================================
# LAYOUTS SYSTÈME (fichiers HTML du serveur)
# ⚠️ DOIVENT ÊTRE AVANT /{template_id} sinon FastAPI matche "layouts" comme UUID
# ============================================================

@router.get("/layouts")
async def get_available_layouts(
    current_user: User = Depends(get_current_user),
):
    """Liste les layouts HTML disponibles sur le serveur."""
    return [
        {
            "id": "classic",
            "name": "Classique",
            "description": "Layout traditionnel avec en-tête coloré et tableau structuré",
            "preview_url": "/api/v1/templates/layouts/classic/preview",
        },
        {
            "id": "modern",
            "name": "Moderne",
            "description": "Design épuré avec accents colorés et typographie contemporaine",
            "preview_url": "/api/v1/templates/layouts/modern/preview",
        },
        {
            "id": "minimal",
            "name": "Minimaliste",
            "description": "Style sobre et économe, idéal pour les prestations simples",
            "preview_url": "/api/v1/templates/layouts/minimal/preview",
        },

        {
            "id": "bold",
            "name": "Audacieux",
            "description": "Design énergique avec des éléments graphiques audacieux",
            "preview_url": "/api/v1/templates/layouts/bold/preview",
        },
        {
            "id": "elegant",
            "name": "Élégant",
            "description": "Style raffiné et sophistiqué, parfait pour les clients exigeants",
            "preview_url": "/api/v1/templates/layouts/elegant/preview",
        },
    ]



@router.get("/{layout_id}/preview.png")
async def get_layout_preview_png(
    layout_id: str,
):
    """Génère une image PNG de preview d'un layout (PUBLIC)."""
    
    valid_layouts = ["modern", "classic", "minimal","bold", "elegant"]
    if layout_id not in valid_layouts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Layout '{layout_id}' non trouvé. Options: {', '.join(valid_layouts)}"
        )

    try:
        png_bytes = await pdf_renderer.render_template_preview_png(
            layout_style=layout_id,
        )

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",  # 24h
                "Content-Disposition": f'inline; filename="preview-{layout_id}.png"'
            }
        )
    except Exception as e:
        logger.error(f"Erreur preview layout {layout_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur de génération: {str(e)}"
        )
    

@router.get("/layouts/{layout_id}/preview", response_class=HTMLResponse)
async def preview_layout(
    layout_id: str,
    current_user: User = Depends(get_current_user),
):
    """Aperçu HTML d'un layout avec les couleurs par défaut (sans template en DB)."""
    if layout_id not in pdf_renderer.LAYOUT_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Layout '{layout_id}' introuvable",
        )

    # Créer un template temporaire avec les valeurs par défaut
    temp_template = DocumentTemplate(
        id=uuid4(),
        name="Aperçu",
        user_id=current_user.id,
        layout_style=layout_id,
    )

    html_content = pdf_renderer.render_preview_html(
        template=temp_template,
        user=current_user,
    )
    return HTMLResponse(content=html_content)


# ============================================================
# TEMPLATES UTILISATEUR (enregistrés en DB)
# ============================================================

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


@router.get("/{template_id}/preview", response_class=HTMLResponse)
async def preview_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aperçu HTML d'un template avec de fausses données (pour la customisation)."""
    template = await TemplateService.get_by_id(db, template_id, current_user.id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modèle introuvable",
        )

    html_content = pdf_renderer.render_preview_html(
        template=template,
        user=current_user,
    )
    return HTMLResponse(content=html_content)


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