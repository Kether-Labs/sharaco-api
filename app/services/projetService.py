# app/services/projectService.py
from sqlmodel import select, func, col
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.projet import Project, ProjectAttachment, ProjectStatus
from app.models.document import Document, DocumentType,DocumentItem
from app.models.client import Client
from uuid import UUID
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ProjectService:
    
    @staticmethod
    async def create_project(
        db: AsyncSession,
        user_id: UUID,
        client_id: UUID,
        name: str,
        description: Optional[str] = None,
        status: str = "DRAFT",
        budget_cents: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Project:
        """Crée un nouveau projet."""
        # Vérifier que le client appartient à l'utilisateur
        client = await db.execute(
            select(Client).where(
                Client.id == client_id,
                Client.user_id == user_id
            )
        )
        if not client.scalar_one_or_none():
            raise ValueError("Client introuvable ou n'appartient pas à cet utilisateur")
        
        project = Project(
            name=name,
            description=description,
            status=status,
            budget_cents=budget_cents,
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            client_id=client_id,
        )
        db.add(project)
        await db.flush()
        result = await db.execute(
        select(Project)
        .options(
            selectinload(Project.attachments),
            selectinload(Project.documents)
        )
        .where(Project.id == project.id)
    )
        project_with_relations = result.scalar_one()
    
        logger.info(f"✅ Projet créé: {project.id} - {project.name}")
        return project_with_relations
    
    @staticmethod
    async def get_by_id(db: AsyncSession, project_id: UUID, user_id: UUID) -> Optional[Project]:
        """Récupère un projet avec ses relations."""
        result = await db.execute(
            select(Project)
            .options(
                selectinload(Project.attachments),
                selectinload(Project.documents)
            )
            .where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_all(
        db: AsyncSession,
        user_id: UUID,
        status: Optional[str] = None,
        client_id: Optional[UUID] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Project]:
        """Liste les projets avec filtres."""
        query = select(Project).where(Project.user_id == user_id)
        
        if status:
            query = query.where(Project.status == status)
        if client_id:
            query = query.where(Project.client_id == client_id)
        if search:
            query = query.where(Project.name.ilike(f"%{search}%"))
        
        query = query.order_by(Project.created_at.desc()).offset(skip).limit(limit)
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def update_project(
        db: AsyncSession,
        project: Project,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        budget_cents: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        client_id: Optional[UUID] = None,
    ) -> Project:
        """Met à jour un projet."""
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if status is not None:
            project.status = status
        if budget_cents is not None:
            project.budget_cents = budget_cents
        if start_date is not None:
            project.start_date = start_date
        if end_date is not None:
            project.end_date = end_date
        if client_id is not None:
            # Vérifier que le nouveau client appartient à l'utilisateur
            client = await db.execute(
                select(Client).where(
                    Client.id == client_id,
                    Client.user_id == project.user_id
                )
            )
            if not client.scalar_one_or_none():
                raise ValueError("Client introuvable ou n'appartient pas à cet utilisateur")
            project.client_id = client_id
        
        db.add(project)
        await db.flush()
        await db.refresh(project)
        
        logger.info(f"✅ Projet mis à jour: {project.id}")
        return project
    
    @staticmethod
    async def delete_project(db: AsyncSession, project: Project) -> None:
        """Supprime un projet et ses attachments."""
        # Supprimer les attachments
        for attachment in project.attachments:
            await db.delete(attachment)
        await db.flush()
        
        # Supprimer le projet
        await db.delete(project)
        await db.commit()
        
        logger.info(f"✅ Projet supprimé: {project.id}")
    
    @staticmethod
    async def get_project_stats(db: AsyncSession, project_id: UUID, user_id: UUID) -> dict:
        """Calcule les statistiques d'un projet."""
        # Nombre de documents
        docs_count = await db.execute(
            select(func.count(Document.id)).where(
                Document.project_id == project_id,
                Document.user_id == user_id
            )
        )
        documents_count = docs_count.scalar() or 0
        
        # ✅ Version optimisée : jointure Document + DocumentItem
        total_result = await db.execute(
            select(
                func.sum(
                    DocumentItem.quantity * DocumentItem.unit_price_cents + 
                    (DocumentItem.quantity * DocumentItem.unit_price_cents * DocumentItem.tax_rate / 100)
                )
            )
            .join(Document, DocumentItem.document_id == Document.id)
            .where(
                Document.project_id == project_id,
                Document.user_id == user_id,
                Document.type == DocumentType.FACTURE,
                Document.status.in_(["PAID", "SENT", "VIEWED"])
            )
        )
        total_invoiced_cents = total_result.scalar() or 0
        
        return {
            "documents_count": documents_count,
            "total_invoiced_cents": int(total_invoiced_cents),
        }
    
    
    @staticmethod
    async def add_attachment(
        db: AsyncSession,
        project_id: UUID,
        user_id: UUID,
        name: str,
        file_url: str,
        file_type: str = "OTHER",
    ) -> ProjectAttachment:
        """Ajoute un attachment à un projet."""
        # Vérifier que le projet appartient à l'utilisateur
        project = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        if not project.scalar_one_or_none():
            raise ValueError("Projet introuvable")
        
        attachment = ProjectAttachment(
            name=name,
            file_url=file_url,
            file_type=file_type,
            project_id=project_id,
            user_id=user_id,
        )
        db.add(attachment)
        await db.flush()
        await db.refresh(attachment)
        
        logger.info(f"✅ Attachment ajouté: {attachment.id} au projet {project_id}")
        return attachment
    
    @staticmethod
    async def delete_attachment(db: AsyncSession, attachment_id: UUID, user_id: UUID) -> None:
        """Supprime un attachment."""
        result = await db.execute(
            select(ProjectAttachment).where(
                ProjectAttachment.id == attachment_id,
                ProjectAttachment.user_id == user_id
            )
        )
        attachment = result.scalar_one_or_none()
        
        if not attachment:
            raise ValueError("Attachment introuvable")
        
        await db.delete(attachment)
        await db.commit()
        
        logger.info(f"✅ Attachment supprimé: {attachment_id}")