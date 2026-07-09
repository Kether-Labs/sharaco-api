# app/api/v1/activity.py

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, union_all, literal_column
from datetime import datetime, timezone, timedelta
from uuid import UUID
from typing import Optional, List
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.document import Document, DocumentStatus
from app.models.projet import Project
from app.models.client import Client
from sqlalchemy.orm import selectinload
import logging

router = APIRouter(tags=["activity"])
logger = logging.getLogger(__name__)


class ActivityItem:
    """Représente un élément d'activité."""
    def __init__(
        self,
        id: UUID,
        type: str,  # "PROJECT", "DOCUMENT"
        action: str,  # "CREATED", "UPDATED", "SENT", "ACCEPTED", "REFUSED"
        title: str,
        subtitle: Optional[str] = None,
        icon: str = "file",
        color: str = "slate",
        link: Optional[str] = None,
        timestamp: datetime = None,
        metadata: dict = None,
    ):
        self.id = id
        self.type = type
        self.action = action
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.color = color
        self.link = link
        self.timestamp = timestamp
        self.metadata = metadata or {}


@router.get("/", response_model=List[dict])
async def get_activity_feed(
    limit: int = Query(50, ge=1, le=100),
    type_filter: Optional[str] = Query(None, description="Filtrer par type: PROJECT, DOCUMENT"),
    action_filter: Optional[str] = Query(None, description="Filtrer par action: CREATED, UPDATED, SENT, ACCEPTED, REFUSED"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupère l'historique d'activité récent."""
    logger.info(f"📊 GET /activity (limit={limit})")
    
    activities = []
    
    # ✅ 1. Récupérer les projets
    if not type_filter or type_filter == "PROJECT":
        projects_query = await db.execute(
            select(Project)
            .where(Project.user_id == current_user.id)
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
        projects = projects_query.scalars().all()
        
        for project in projects:
            # Déterminer l'action
            if project.created_at == project.updated_at:
                action = "CREATED"
            else:
                action = "UPDATED"
            
            # Filtrer si nécessaire
            if action_filter and action != action_filter:
                continue
            
            activities.append({
                "id": str(project.id),
                "type": "PROJECT",
                "action": action,
                "title": project.name,
                "subtitle": f"Projet {action.lower()}",
                "icon": "folder",
                "color": "blue",
                "link": f"/dashboard/projects/{project.id}",
                "timestamp": project.updated_at.isoformat(),
                "metadata": {
                    "status": project.status,
                    "client_id": str(project.client_id),
                }
            })
    
    # ✅ 2. Récupérer les documents
    if not type_filter or type_filter == "DOCUMENT":
        documents_query = await db.execute(
            select(Document)
            .options(selectinload(Document.client))
            .where(Document.user_id == current_user.id)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        documents = documents_query.scalars().all()
        
        for doc in documents:
            # Déterminer l'action et l'icône selon le statut
            if doc.status == DocumentStatus.ACCEPTED:
                action = "ACCEPTED"
                icon = "check-circle"
                color = "emerald"
                subtitle = f"Devis accepté par {doc.client.name if doc.client else 'client'}"
            elif doc.status == DocumentStatus.REFUSED:
                action = "REFUSED"
                icon = "x-circle"
                color = "rose"
                subtitle = f"Devis refusé par {doc.client.name if doc.client else 'client'}"
            elif doc.status == DocumentStatus.SENT:
                action = "SENT"
                icon = "send"
                color = "amber"
                subtitle = f"Envoyé à {doc.client.name if doc.client else 'client'}"
            elif doc.status == DocumentStatus.VIEWED:
                action = "VIEWED"
                icon = "eye"
                color = "sky"
                subtitle = f"Consulté par {doc.client.name if doc.client else 'client'}"
            else:
                action = "CREATED"
                icon = "file"
                color = "slate"
                subtitle = f"{doc.type} créé"
            
            # Filtrer si nécessaire
            if action_filter and action != action_filter:
                continue
            
            # Utiliser le timestamp le plus pertinent
            timestamp = doc.viewed_at or doc.sent_at or doc.created_at
            
            activities.append({
                "id": str(doc.id),
                "type": "DOCUMENT",
                "action": action,
                "title": doc.number or f"{doc.type} {str(doc.id)[:8]}",
                "subtitle": subtitle,
                "icon": icon,
                "color": color,
                "link": f"/dashboard/quotes/{doc.id}",
                "timestamp": timestamp.isoformat(),
                "metadata": {
                    "status": doc.status,
                    "document_type": doc.type,
                    "client_name": doc.client.name if doc.client else None,
                }
            })
    
    # ✅ 3. Trier par timestamp (plus récent en premier)
    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    
    # ✅ 4. Limiter le résultat
    return activities[:limit]