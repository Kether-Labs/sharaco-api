# app/api/v1/project.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import Optional
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.client import Client
from app.services.projetService import ProjectService
from app.schemas.projet import (
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    ProjectListRead,
    ProjectAttachmentCreate,
    ProjectAttachmentRead,
)

from app.schemas.document import (
    DocumentRead,

)

from app.models.document import Document, DocumentItem
from app.services.documentService import DocumentService
import logging

router = APIRouter(tags=["projects"])
logger = logging.getLogger(__name__)


@router.get("/{project_id}/documents", response_model=list[DocumentRead])
async def get_project_documents(
    project_id: UUID,
    type: Optional[str] = Query(None, description="Filtrer par type (DEVIS, FACTURE)"),
    status: Optional[str] = Query(None, description="Filtrer par statut"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupère tous les documents liés à un projet."""
    logger.info(f"📄 GET /projects/{project_id}/documents")
    
    # Vérifier que le projet appartient à l'utilisateur
    project = await ProjectService.get_by_id(db, project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    
    # Récupérer les documents du projet
    from app.models.document import Document, DocumentType, DocumentStatus
    
    query = select(Document).where(
        Document.project_id == project_id,
        Document.user_id == current_user.id
    )
    
    if type:
        try:
            doc_type = DocumentType(type)
            query = query.where(Document.type == doc_type)
        except ValueError:
            pass
    
    if status:
        try:
            doc_status = DocumentStatus(status)
            query = query.where(Document.status == doc_status)
        except ValueError:
            pass
    
    query = query.order_by(Document.created_at.desc())
    
    result = await db.execute(query)
    documents = result.scalars().all()
    
    # Construire la réponse avec les totaux
    response = []
    for doc in documents:
        # Charger les items
        items_result = await db.execute(
            select(DocumentItem).where(DocumentItem.document_id == doc.id)
        )
        items = items_result.scalars().all()
        
        # Calculer les totaux
        totals = DocumentService.calculate_totals(items)
        
        response.append({
            "id": doc.id,
            "type": doc.type,
            "status": doc.status,
            "number": doc.number,
            "created_at": doc.created_at,
            "due_date": doc.due_date,
            "user_id": doc.user_id,
            "client_id": doc.client_id,
            "template_id": doc.template_id,
            "layout_style": doc.layout_style,
            "notes": doc.notes,
            "items": items,
            "subtotal_cents": totals["subtotal_cents"],
            "tax_total_cents": totals["tax_total_cents"],
            "grand_total_cents": totals["grand_total_cents"],
        })
    
    return response

@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Créer un nouveau projet."""
    logger.info(f"✨ POST /projects - Création projet: {project_data.name}")
    
    try:
        project = await ProjectService.create_project(
            db=db,
            user_id=current_user.id,
            client_id=project_data.client_id,
            name=project_data.name,
            description=project_data.description,
            status=project_data.status,
            budget_cents=project_data.budget_cents,
            start_date=project_data.start_date,
            end_date=project_data.end_date,
        )
    except ValueError as e:
        logger.error(f"❌ Erreur création: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    
    stats = await ProjectService.get_project_stats(db, project.id, current_user.id)
    
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "budget_cents": project.budget_cents,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "user_id": project.user_id,
        "client_id": project.client_id,
        "documents_count": stats["documents_count"],
        "attachments": [],
    }


@router.get("/", response_model=list[ProjectListRead])
async def list_projects(
    status: Optional[str] = Query(None, description="Filtrer par statut"),
    client_id: Optional[UUID] = Query(None, description="Filtrer par client"),
    search: Optional[str] = Query(None, description="Rechercher par nom"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste les projets avec filtres."""
    projects = await ProjectService.get_all(
        db=db,
        user_id=current_user.id,
        status=status,
        client_id=client_id,
        search=search,
        skip=skip,
        limit=limit,
    )
    
    result = []
    for project in projects:
        # Récupérer le nom du client
        client_result = await db.execute(
            select(Client).where(Client.id == project.client_id)
        )
        client = client_result.scalar_one_or_none()
        
        # Statistiques
        stats = await ProjectService.get_project_stats(db, project.id, current_user.id)
        
        result.append({
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "budget_cents": project.budget_cents,
            "start_date": project.start_date,
            "end_date": project.end_date,
            "created_at": project.created_at,
            "client_id": project.client_id,
            "client_name": client.name if client else None,
            "documents_count": stats["documents_count"],
            "total_invoiced_cents": stats["total_invoiced_cents"],
        })
    
    return result


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupérer les détails d'un projet."""
    logger.info(f"🔍 GET /projects/{project_id}")
    
    project = await ProjectService.get_by_id(db, project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    
    stats = await ProjectService.get_project_stats(db, project.id, current_user.id)
    
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "budget_cents": project.budget_cents,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "user_id": project.user_id,
        "client_id": project.client_id,
        "documents_count": stats["documents_count"],
        "attachments": [
            {
                "id": att.id,
                "name": att.name,
                "file_url": att.file_url,
                "file_type": att.file_type,
                "uploaded_at": att.uploaded_at,
                "project_id": att.project_id,
                "user_id": att.user_id,
            }
            for att in project.attachments
        ] if project.attachments else [],
    }


@router.put("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID,
    project_data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mise à jour d'un projet."""
    logger.info(f"🔄 PUT /projects/{project_id}")
    
    project = await ProjectService.get_by_id(db, project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    
    try:
        updated = await ProjectService.update_project(
            db=db,
            project=project,
            name=project_data.name,
            description=project_data.description,
            status=project_data.status,
            budget_cents=project_data.budget_cents,
            start_date=project_data.start_date,
            end_date=project_data.end_date,
            client_id=project_data.client_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    stats = await ProjectService.get_project_stats(db, updated.id, current_user.id)
    
    return {
        "id": updated.id,
        "name": updated.name,
        "description": updated.description,
        "status": updated.status,
        "budget_cents": updated.budget_cents,
        "start_date": updated.start_date,
        "end_date": updated.end_date,
        "created_at": updated.created_at,
        "updated_at": updated.updated_at,
        "user_id": updated.user_id,
        "client_id": updated.client_id,
        "documents_count": stats["documents_count"],
        "attachments": [
            {
                "id": att.id,
                "name": att.name,
                "file_url": att.file_url,
                "file_type": att.file_type,
                "uploaded_at": att.uploaded_at,
                "project_id": att.project_id,
                "user_id": att.user_id,
            }
            for att in updated.attachments
        ] if updated.attachments else [],
    }


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Supprimer un projet."""
    logger.info(f"🗑️ DELETE /projects/{project_id}")
    
    project = await ProjectService.get_by_id(db, project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    
    await ProjectService.delete_project(db, project)


@router.post("/{project_id}/attachments", response_model=ProjectAttachmentRead, status_code=status.HTTP_201_CREATED)
async def add_attachment(
    project_id: UUID,
    attachment_data: ProjectAttachmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ajouter un attachment à un projet."""
    logger.info(f"📎 POST /projects/{project_id}/attachments")
    
    try:
        attachment = await ProjectService.add_attachment(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            name=attachment_data.name,
            file_url=attachment_data.file_url,
            file_type=attachment_data.file_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return attachment


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Supprimer un attachment."""
    logger.info(f"🗑️ DELETE /projects/attachments/{attachment_id}")
    
    try:
        await ProjectService.delete_attachment(db, attachment_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))