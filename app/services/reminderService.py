# app/services/reminderService.py
import os
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from typing import Optional
from uuid import UUID
import logging

from app.models.reminder import ReminderConfig, ReminderLog, ReminderStatus, DocumentView
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.invoice_reminder import InvoiceReminder, InvoiceReminderType
from app.models.user import User
from app.models.client import Client
from app.services.emailService import EmailService
from app.services.pdfRenderer import pdf_renderer
from app.services.templateService import TemplateService
from app.services.documentService import DocumentService
from app.core.config import settings
from app.utils.datetime import to_naive_utc

logger = logging.getLogger(__name__)


class ReminderService:
    TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "emails")

    # ✅ Déplacé dans la classe pour cohérence
    CHECKS = [
        (3, InvoiceReminderType.DUE_3_DAYS),
        (1, InvoiceReminderType.DUE_1_DAY),
    ]

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(self.TEMPLATES_DIR),
            autoescape=True,
        )

    # ═══════════════════════════════════════════════════════════════
    # ✅ V1 : Alertes de prévention avant échéance (J-3, J-1)
    # ═══════════════════════════════════════════════════════════════
    @staticmethod
    async def check_due_invoices(db: AsyncSession) -> dict:
        """
        Vérifie les factures envoyées dont l'échéance arrive (J-3, J-1)
        et envoie un email de prévention (une seule fois par type).
        """
        now = to_naive_utc(datetime.now(timezone.utc))
        today = now.date()

        min_date = datetime.combine(today, datetime.min.time())
        max_date = datetime.combine(today + timedelta(days=3), datetime.max.time())

        # Factures envoyées, non payées, échéance dans les 3 prochains jours
        stmt = (
            select(Document)
            .options(
                selectinload(Document.client),
                selectinload(Document.items),
                selectinload(Document.owner),  # ✅ Pour user_company
            )
            .where(
                Document.type == DocumentType.FACTURE,
                Document.status.in_([DocumentStatus.SENT, DocumentStatus.VIEWED]),
                Document.due_date != None,
                Document.due_date >= min_date,
                Document.due_date <= max_date,
            )
        )
        result = await db.execute(stmt)
        invoices = list(result.scalars().all())

        sent_count = 0
        skipped_count = 0
        details = []

        for invoice in invoices:
            days_left = (invoice.due_date.date() - today).days

            # Déterminer le type de rappel correspondant
            reminder_type = next(
                (rtype for days, rtype in ReminderService.CHECKS if days == days_left),
                None,
            )
            if not reminder_type:
                continue

            # Déjà alerté pour ce type ? → skip
            already = await db.execute(
                select(InvoiceReminder.id).where(
                    InvoiceReminder.invoice_id == invoice.id,
                    InvoiceReminder.reminder_type == reminder_type.value,
                )
            )
            if already.scalar_one_or_none():
                skipped_count += 1
                continue

            email = invoice.client.email if invoice.client else None
            if not email:
                logger.warning(f"⚠️ Facture {invoice.number} : client sans email")
                skipped_count += 1
                continue

            # ✅ Générer le lien privé client (optionnel, pour accès direct)
            client_url = None
            try:
                if not invoice.client_token:
                    invoice.client_token = Document.generate_share_token()
                    invoice.client_token_email = email
                    invoice.share_enabled = True
                    db.add(invoice)
                base_url = settings.FRONTEND_URL or "http://localhost:3000"
                client_url = f"{base_url}/client/{invoice.client_token}"
            except Exception as e:
                logger.warning(f"⚠️ Impossible de générer client_url: {e}")

            totals = DocumentService.calculate_totals(invoice.items)
            total_amount = f"{totals['grand_total_cents'] / 100:,.2f}"
            
            user_company = (
                invoice.owner.company_name 
                if invoice.owner and invoice.owner.company_name 
                else "Sharaco"
            )

            # Envoyer l'email de prévention
            try:
                send_result = await EmailService.send_invoice_reminder(
                    to_email=email,
                    client_name=invoice.client.name or "Client",
                    document_number=invoice.number or str(invoice.id),
                    total_amount=total_amount,
                    due_date=invoice.due_date.strftime("%d/%m/%Y"),
                    days_left=days_left,
                    client_url=client_url,
                    user_company=user_company,
                )

                if send_result.get("success"):
                    # Logger le rappel (anti-doublon)
                    db.add(InvoiceReminder(
                        invoice_id=invoice.id,
                        reminder_type=reminder_type.value,
                        recipient_email=email,
                    ))
                    sent_count += 1
                    details.append({
                        "invoice": invoice.number,
                        "type": reminder_type.value,
                        "days_left": days_left,
                        "email": email,
                    })
                    logger.info(
                        f"⏰ Rappel {reminder_type.value} envoyé pour {invoice.number} (J-{days_left})"
                    )
                else:
                    logger.error(f"❌ Échec envoi rappel {invoice.number}: {send_result.get('error')}")
                    skipped_count += 1

            except Exception as e:
                logger.error(f"❌ Erreur rappel {invoice.number}: {e}", exc_info=True)
                skipped_count += 1

        await db.commit()

        return {
            "checked": len(invoices),
            "sent": sent_count,
            "skipped": skipped_count,
            "details": details,
        }

    # ═══════════════════════════════════════════════════════════════
    # === CONFIG === (V2 - relances automatiques après retard)
    # ═══════════════════════════════════════════════════════════════
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
        for key, value in kwargs.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    # ═══════════════════════════════════════════════════════════════
    # === SEND DOCUMENT === (utilisé par l'envoi manuel)
    # ═══════════════════════════════════════════════════════════════
    async def send_document(
        self,
        db: AsyncSession,
        document: Document,
        user: User,
        client: Client,
    ) -> dict:
        """Envoie un document par email au client et change le statut en SENT."""
        template = await self._get_template(db, document, user)

        # ✅ await ajouté : render_pdf est async
        pdf_buffer = await pdf_renderer.render_pdf(
            db=db, document=document, template=template, user=user, client=client
        )
        pdf_bytes = pdf_buffer.read()

        base_url = settings.FRONTEND_URL or "http://localhost:3000"
        document_link = f"{base_url}/view/{document.id}"

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

        # ✅ Utilise la bonne méthode EmailService selon le type
        if document.type == DocumentType.DEVIS:
            result = await EmailService.send_devis(
                to_email=client.email,
                client_name=client.name,
                document_number=document.number or "",
                total_amount=totals["grand_total"],
                client_url=document_link,
                due_date=document.due_date.strftime("%d/%m/%Y") if document.due_date else None,
                user_name=getattr(user, 'full_name', '') or user.email,
                user_company=user.company_name or "Sharaco",
            )
        else:
            result = await EmailService.send_facture(
                to_email=client.email,
                client_name=client.name,
                document_number=document.number or "",
                total_amount=totals["grand_total"],
                client_url=document_link,
                due_date=document.due_date.strftime("%d/%m/%Y") if document.due_date else None,
                user_name=getattr(user, 'full_name', '') or user.email,
                user_company=user.company_name or "Sharaco",
            )

        # Mettre à jour le document
        if result.get("success"):
            document.status = DocumentStatus.SENT
            document.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(document)
            await db.commit()

        return result

    # ═══════════════════════════════════════════════════════════════
    # === SEND REMINDER (V2 - relances automatiques après retard)
    # ═══════════════════════════════════════════════════════════════
    async def send_reminder(
        self,
        db: AsyncSession,
        document: Document,
        user: User,
        client: Client,
        reminder_level: int,
    ) -> ReminderLog:
        """Envoie une relance pour un document (V2 - à activer plus tard)."""
        config = await self.get_or_create_config(db, user.id)

        if not config.is_active:
            raise ValueError("Les relances automatiques sont désactivées")

        if config.stop_on_payment and document.status == DocumentStatus.PAID:
            raise ValueError("Le document est déjà payé")

        if config.stop_on_view and document.status == DocumentStatus.VIEWED:
            raise ValueError("Le document a déjà été consulté")

        level_enabled = getattr(config, f"reminder_{reminder_level}_enabled", False)
        if not level_enabled:
            raise ValueError(f"Relance niveau {reminder_level} désactivée")

        existing = await self._get_reminder_log(db, document.id, reminder_level)
        if existing and existing.status == ReminderStatus.SENT:
            raise ValueError(f"Relance niveau {reminder_level} déjà envoyée")

        log = ReminderLog(
            document_id=document.id,
            reminder_level=reminder_level,
            status=ReminderStatus.PENDING,
        )
        db.add(log)
        await db.flush()

        try:
            base_url = settings.FRONTEND_URL or "http://localhost:3000"
            document_link = f"{base_url}/view/{document.id}"
            totals = self._calculate_totals_simple(document)

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

            # ✅ Utilise send_notification au lieu de send_reminder_email (inexistant)
            result = await EmailService.send_notification(
                to_email=client.email,
                subject=subject,
                template="document_email.html",
                context={
                    "to_name": client.name,
                    "document_number": document.number or "",
                    "total_amount": totals["grand_total"],
                    "document_link": document_link,
                    "user_company": user.company_name or "Sharaco",
                    "is_reminder": True,
                },
            )

            if result.get("success"):
                log.status = ReminderStatus.SENT
                log.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                log.status = ReminderStatus.FAILED
                log.error_message = result.get("error", "Unknown error")
            
            await db.commit()
            logger.info(f"Relance niveau {reminder_level} envoyée pour {document.number}")
            return log

        except Exception as e:
            log.status = ReminderStatus.FAILED
            log.error_message = str(e)
            await db.commit()
            logger.error(f"Erreur relance {document.number}: {str(e)}")
            raise

    # ═══════════════════════════════════════════════════════════════
    # === TRACKING ===
    # ═══════════════════════════════════════════════════════════════
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

        view = DocumentView(
            document_id=document_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(view)

        if document.viewed_at is None:
            document.viewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if document.status == DocumentStatus.SENT:
                document.status = DocumentStatus.VIEWED

        db.add(document)
        await db.commit()
        return document

    # ═══════════════════════════════════════════════════════════════
    # === HISTORY ===
    # ═══════════════════════════════════════════════════════════════
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

    # ═══════════════════════════════════════════════════════════════
    # === HELPERS ===
    # ═══════════════════════════════════════════════════════════════
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
            name="Par défaut", user_id=user.id, primary_color="#2563EB",
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
            "grand_total": f"{(subtotal + tax) / 100:,.2f} FCFA",
        }

    def _render_email(self, document, user, client, totals, document_link, is_reminder):
        try:
            tmpl = self.env.get_template("document_email.html")
            return tmpl.render(
                company_name=user.company_name or "Sharaco",
                company_address=user.address or "",
                primary_color="#2563EB",
                client_name=client.name,
                doc_type=document.type.value if hasattr(document.type, 'value') else document.type,
                doc_number=document.number or "",
                grand_total=totals["grand_total"],
                due_date=document.due_date.strftime("%d/%m/%Y") if document.due_date else "",
                sent_date=document.sent_at.strftime("%d/%m/%Y") if document.sent_at else "",
                document_link=document_link,
                is_reminder=is_reminder,
            )
        except Exception as e:
            logger.warning(f"⚠️ Template document_email.html introuvable: {e}")
            # Fallback simple
            return f"""
            <html><body>
            <h2>{document.type.value} {document.number}</h2>
            <p>Bonjour {client.name},</p>
            <p>Montant : {totals['grand_total']}</p>
            <p><a href="{document_link}">Voir le document</a></p>
            </body></html>
            """


reminder_service = ReminderService()