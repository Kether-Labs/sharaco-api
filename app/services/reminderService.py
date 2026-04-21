import os
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.reminder import ReminderConfig, ReminderLog, ReminderStatus, DocumentView
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.client import Client
from app.services.emailService import EmailService
from app.services.pdfRenderer import pdf_renderer
from app.services.templateService import TemplateService
from app.core.config import settings
from uuid import UUID
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ReminderService:
    TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "emails")

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(self.TEMPLATES_DIR),
            autoescape=True,
        )

    # === CONFIG ===

    @staticmethod
    async def get_or_create_config(db: AsyncSession, user_id: UUID) -> ReminderConfig:
        """Récupère ou crée la config de relances pour un utilisateur."""
        statement = select(ReminderConfig).where(ReminderConfig.user_id == user_id)
        result = await db.execute(statement)
        config = result.scalar_one_or_none()

        if not config:
            config = ReminderConfig(user_id=user_id)
            db.add(config)
            await db.commit()
            await db.refresh(config)

        return config

    @staticmethod
    async def update_config(db: AsyncSession, config: ReminderConfig, **kwargs) -> ReminderConfig:
        """Met à jour la config de relances."""
        from datetime import datetime, timezone
        for key, value in kwargs.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = datetime.now(timezone.utc)
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    # === SEND DOCUMENT ===

    async def send_document(
        self,
        db: AsyncSession,
        document: Document,
        user: User,
        client: Client,
    ) -> dict:
        """Envoie un document par email au client et change le statut en SENT."""
        # Récupérer le template de design
        template = await self._get_template(db, document, user)

        # Générer le PDF
        pdf_buffer = pdf_renderer.render_pdf(document, template, user, client)
        pdf_bytes = pdf_buffer.read()

        # Générer le lien public
        document_link = f"{settings.FRONTEND_URL}/view/{document.id}"

        # Préparer le contenu email
        totals = self._calculate_totals_simple(document)
        html_content = self._render_email(
            document=document,
            user=user,
            client=client,
            totals=totals,
            document_link=document_link,
            is_reminder=False,
        )

        subject = f"{document.type.value} {document.number} - {user.company_name or 'Sharaco'}"

        # Envoyer
        result = await EmailService.send_document_email(
            to_email=client.email,
            to_name=client.name,
            from_name=user.company_name or "Sharaco",
            subject=subject,
            html_content=html_content,
            pdf_bytes=pdf_bytes,
            pdf_filename=f"{document.number or 'document'}.pdf",
        )

        # Mettre à jour le document
        document.status = DocumentStatus.SENT
        document.sent_at = datetime.now(timezone.utc)
        db.add(document)
        await db.commit()

        return result

    # === SEND REMINDER ===

    async def send_reminder(
        self,
        db: AsyncSession,
        document: Document,
        user: User,
        client: Client,
        reminder_level: int,
    ) -> ReminderLog:
        """Envoie une relance pour un document."""
        config = await self.get_or_create_config(db, user.id)

        # Vérifier si on doit envoyer la relance
        if not config.is_active:
            raise ValueError("Les relances automatiques sont désactivées")

        if config.stop_on_payment and document.status == DocumentStatus.PAID:
            raise ValueError("Le document est déjà payé")

        if config.stop_on_view and document.status == DocumentStatus.VIEWED:
            raise ValueError("Le document a déjà été consulté")

        # Vérifier le niveau de relance
        level_enabled = getattr(config, f"reminder_{reminder_level}_enabled", False)
        if not level_enabled:
            raise ValueError(f"Relance niveau {reminder_level} désactivée")

        # Vérifier qu'on n'a pas déjà envoyé ce niveau
        existing = await self._get_reminder_log(db, document.id, reminder_level)
        if existing and existing.status == ReminderStatus.SENT:
            raise ValueError(f"Relance niveau {reminder_level} déjà envoyée")

        # Créer le log
        log = ReminderLog(
            document_id=document.id,
            reminder_level=reminder_level,
            status=ReminderStatus.PENDING,
        )
        db.add(log)
        await db.flush()

        try:
            # Préparer l'email
            document_link = f"{settings.FRONTEND_URL}/view/{document.id}"
            totals = self._calculate_totals_simple(document)

            # Sujet personnalisé
            subject_template = getattr(config, f"reminder_{reminder_level}_subject", "")
            subject = subject_template.format(
                number=document.number,
                company=user.company_name or "Sharaco"
            )

            html_content = self._render_email(
                document=document,
                user=user,
                client=client,
                totals=totals,
                document_link=document_link,
                is_reminder=True,
            )

            # Envoyer
            await EmailService.send_reminder_email(
                to_email=client.email,
                to_name=client.name,
                from_name=user.company_name or "Sharaco",
                subject=subject,
                html_content=html_content,
                document_link=document_link,
            )

            # Mettre à jour le log
            log.status = ReminderStatus.SENT
            log.sent_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(f"Relance niveau {reminder_level} envoyée pour {document.number}")
            return log

        except Exception as e:
            log.status = ReminderStatus.FAILED
            log.error_message = str(e)
            await db.commit()
            logger.error(f"Erreur relance {document.number}: {str(e)}")
            raise

    # === TRACKING ===

    @staticmethod
    async def track_view(
        db: AsyncSession,
        document_id: UUID,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[Document]:
        """Enregistre une visualisation du document par le client."""
        statement = select(Document).where(Document.id == document_id)
        result = await db.execute(statement)
        document = result.scalar_one_or_none()

        if not document:
            return None

        # Enregistrer la vue
        view = DocumentView(
            document_id=document_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(view)

        # Première vue ? Mettre à jour le statut
        if document.viewed_at is None:
            document.viewed_at = datetime.now(timezone.utc)
            if document.status == DocumentStatus.SENT:
                document.status = DocumentStatus.VIEWED

        db.add(document)
        await db.commit()
        return document

    # === HISTORY ===

    @staticmethod
    async def get_reminder_history(db: AsyncSession, document_id: UUID) -> list[ReminderLog]:
        """Récupère l'historique des relances d'un document."""
        statement = (
            select(ReminderLog)
            .where(ReminderLog.document_id == document_id)
            .order_by(ReminderLog.reminder_level)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    # === HELPERS ===

    @staticmethod
    async def _get_template(db, document, user):
        """Récupère le template de design du document."""
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

    @staticmethod
    async def _get_reminder_log(db: AsyncSession, document_id: UUID, level: int) -> Optional[ReminderLog]:
        statement = select(ReminderLog).where(
            ReminderLog.document_id == document_id,
            ReminderLog.reminder_level == level,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    def _calculate_totals_simple(self, document: Document) -> dict:
        subtotal = sum(i.quantity * i.unit_price_cents for i in document.items)
        tax = sum(int(i.quantity * i.unit_price_cents * i.tax_rate / 100) for i in document.items)
        return {
            "subtotal": f"{subtotal / 100:.2f}",
            "tax": f"{tax / 100:.2f}",
            "grand_total": f"{(subtotal + tax) / 100:.2f} FCFA",
        }

    def _render_email(self, document, user, client, totals, document_link, is_reminder):
        tmpl = self.env.get_template("document_email.html")
        return tmpl.render(
            company_name=user.company_name or "Sharaco",
            company_address=user.address or "",
            primary_color="#2563EB",
            client_name=client.name,
            doc_type=document.type.value,
            doc_number=document.number or "",
            grand_total=totals["grand_total"],
            due_date=document.due_date.strftime("%d/%m/%Y") if document.due_date else "",
            sent_date=document.sent_at.strftime("%d/%m/%Y") if document.sent_at else "",
            document_link=document_link,
            is_reminder=is_reminder,
        )


reminder_service = ReminderService()