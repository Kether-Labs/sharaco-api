from typing import List, Optional
from uuid import UUID
from datetime import datetime
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document
from app.services.emailService import EmailService
import logging


logger = logging.getLogger(__name__)

class NotificationService:
    
    @staticmethod
    async def notify_document_accepted(document_id: UUID, db: AsyncSession):
        """Notifie l'utilisateur que son devis a été accepté."""
        result = await db.execute(
            select(Document)
            .options(selectinload(Document.owner), selectinload(Document.client))
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        
        if not document or not document.owner:
            return
        
        # Ici tu peux :
        # 1. Envoyer un email à l'utilisateur
        # 2. Créer une notification in-app
        # 3. Envoyer une notification push
        
        logger.info(
            f"🔔 Notification : Le devis {document.number} a été accepté par "
            f"{document.client.name if document.client else 'le client'}"
        )
        
        # Exemple : Envoyer un email à l'utilisateur
        await EmailService.send_notification(
            to_email=document.owner.email,
            subject=f"✅ Devis {document.number} accepté !",
            template="document_accepted.html",
            context={
                "document_number": document.number,
                "client_name": document.client.name if document.client else "Client",
                "signature_name": document.signature_name,
                "amount": f"{DocumentService.calculate_totals(document.items)['grand_total_cents'] / 100:.2f} €",
            }
        )