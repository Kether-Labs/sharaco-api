# app/api/v1/activity.py

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, union_all, literal_column
from datetime import datetime, timezone, timedelta
from uuid import UUID
from app.services.documentService import DocumentService
from app.models.document import DocumentType
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


# app/api/v1/activity.py

@router.get("/", response_model=List[dict])
async def get_activity_feed(
    limit: int = Query(50, ge=1, le=100),
    type_filter: Optional[str] = Query(None, description="Filtrer par type: PROJECT, DOCUMENT"),
    action_filter: Optional[str] = Query(None, description="Filtrer par action"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupère l'historique d'activité récent."""
    logger.info(f"📊 GET /activity (limit={limit})")
    
    activities = []
    
    # ═══════════════════════════════════════════════
    # 1. Projets (inchangé)
    # ═══════════════════════════════════════════════
    if not type_filter or type_filter == "PROJECT":
        projects_query = await db.execute(
            select(Project)
            .where(Project.user_id == current_user.id)
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
        projects = projects_query.scalars().all()
        
        for project in projects:
            action = "CREATED" if project.created_at == project.updated_at else "UPDATED"
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
    
    # ═══════════════════════════════════════════════
    # 2. Documents avec gestion du PAID
    # ═══════════════════════════════════════════════
    if not type_filter or type_filter == "DOCUMENT":
        documents_query = await db.execute(
            select(Document)
            .options(selectinload(Document.client),selectinload(Document.items),)
            .where(Document.user_id == current_user.id)
            .order_by(Document.created_at.desc())
            .limit(limit * 2)  # ✅ On prend plus car on va générer plusieurs activités par doc
        )
        documents = documents_query.scalars().all()
        
        for doc in documents:
            client_name = doc.client.name if doc.client else "client"
            
            # ═══ Activité principale selon le statut actuel ═══
            if doc.status == DocumentStatus.PAID and doc.type == DocumentType.FACTURE:
                # ✅ NOUVEAU : Facture payée = événement majeur
                action = "PAID"
                icon = "banknote"  # ou "wallet", "credit-card"
                color = "emerald"
                subtitle = f"Facture payée par {client_name}"
                timestamp = doc.paid_at  or doc.created_at
            elif doc.status == DocumentStatus.ACCEPTED:
                action = "ACCEPTED"
                icon = "check-circle"
                color = "emerald"
                subtitle = f"Devis accepté par {client_name}"
                timestamp = doc.accepted_at or doc.created_at
            elif doc.status == DocumentStatus.REFUSED:
                action = "REFUSED"
                icon = "x-circle"
                color = "rose"
                subtitle = f"Devis refusé par {client_name}"
                timestamp = doc.refused_at or doc.created_at
            elif doc.status == DocumentStatus.SENT:
                action = "SENT"
                icon = "send"
                color = "amber"
                subtitle = f"Envoyé à {client_name}"
                timestamp = doc.sent_at or doc.created_at
            elif doc.status == DocumentStatus.VIEWED:
                action = "VIEWED"
                icon = "eye"
                color = "sky"
                subtitle = f"Consulté par {client_name}"
                timestamp = doc.viewed_at or doc.created_at
            else:
                action = "CREATED"
                icon = "file"
                color = "slate"
                subtitle = f"{doc.type.value} créé"
                timestamp = doc.created_at
            
            if action_filter and action != action_filter:
                continue
            
            activities.append({
                "id": str(doc.id),
                "type": "DOCUMENT",
                "action": action,
                "title": doc.number or f"{doc.type.value} {str(doc.id)[:8]}",
                "subtitle": subtitle,
                "icon": icon,
                "color": color,
                "link": f"/dashboard/quotes/{doc.id}" if doc.type == DocumentType.DEVIS else f"/dashboard/invoices/{doc.id}",
                "timestamp": timestamp.isoformat(),
                "metadata": {
                    "status": doc.status.value if hasattr(doc.status, 'value') else doc.status,
                    "document_type": doc.type.value if hasattr(doc.type, 'value') else doc.type,
                    "client_name": client_name,
                    "amount_cents": DocumentService.calculate_totals(doc.items)["grand_total_cents"] if doc.items else 0,
                }
            })
            
            # ═══ Activité secondaire : si facture payée ET issue d'un devis ═══
            # On ajoute un événement historique "le devis correspondant a été signé"
            # (utile pour remonter dans le temps)
            if (
                doc.type == DocumentType.FACTURE 
                and doc.status == DocumentStatus.PAID
                and doc.source_document_id
                and doc.accepted_at  # ou utiliser la date de création de la facture comme proxy
            ):
                # Pas d'ajout ici pour ne pas dupliquer — déjà couvert par l'activité du devis
                pass
    
    # ═══════════════════════════════════════════════
    # 3. Trier par timestamp (plus récent en premier)
    # ═══════════════════════════════════════════════
    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    
    # ═══════════════════════════════════════════════
    # 4. Limiter le résultat
    # ═══════════════════════════════════════════════
    return activities[:limit]