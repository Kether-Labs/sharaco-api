import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from io import BytesIO
from playwright.async_api import async_playwright
from sqlmodel import select
from app.core.currency import get_currency_symbol
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document, DocumentItem
from app.models.document_template import DocumentTemplate
from app.models.client import Client
from app.models.user import User
import logging
from datetime import datetime, timezone
from uuid import uuid4
from app.models.document import DocumentType, DocumentStatus
from app.models.payment_schedule import PaymentSchedule, MilestoneStatus

logger = logging.getLogger(__name__)


class PDFRenderer:
    """Moteur de rendu HTML/PDF pour les devis et factures."""

    TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

    QUOTE_LAYOUT_MAP = {
        "classic": "classic.html",
        "modern": "modern.html",
        "minimal": "minimal.html",
        "bold": "bold.html",
        "elegant": "elegant.html",
        "premium": "premium.html",
        "bento": "bento.html",
        "studio": "studio.html",
    }

    INVOICE_TEMPLATE = "facture.html"
    DEFAULT_CURRENCY = "FCFA"

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATES_DIR)),
            autoescape=True,
            cache_size=100,
        )
        self._preview_cache: dict[str, bytes] = {}

    def _get_layout_file(self, layout_style: str, doc_type: DocumentType) -> str:
        if doc_type == DocumentType.FACTURE:
            return self.INVOICE_TEMPLATE
        return self.QUOTE_LAYOUT_MAP.get(layout_style, "classic.html")

    @staticmethod
    def _calculate_totals(items: list[DocumentItem]) -> dict:
        subtotal_cents = 0
        tax_total_cents = 0

        for item in items:
            line_subtotal = item.quantity * item.unit_price_cents
            line_tax = int(line_subtotal * item.tax_rate / 100)
            subtotal_cents += line_subtotal
            tax_total_cents += line_tax

        grand_total_cents = subtotal_cents + tax_total_cents

        return {
            "subtotal_cents": subtotal_cents,
            "tax_total_cents": tax_total_cents,
            "grand_total_cents": grand_total_cents,
        }

    # ✅ MODIF 1 : ajout de `self` et typage `db`
    async def _build_invoice_schedule_context(self, db: AsyncSession, document: Document) -> dict:
        """
        Construit le contexte 'Suivi de paiement' pour une FACTURE :
        remonte au devis parent, lit son échéancier, calcule la progression
        et identifie la tranche correspondant à cette facture.
        """
        empty = {
            "payment_schedule": [],
            "current_milestone": None,
            "current_amount_cents": None,
            "paid_percent": 0,
            "paid_amount_cents": 0,
            "total_schedule_cents": 0,
            "source_quote_number": None,
            "has_schedule": False,
        }

        if document.type != DocumentType.FACTURE or not document.source_document_id:
            return empty

        quote = await db.get(Document, document.source_document_id)
        if not quote:
            return empty

        result = await db.execute(
            select(PaymentSchedule)
            .where(PaymentSchedule.document_id == quote.id)
            .order_by(PaymentSchedule.sequence.asc())
        )
        milestones = list(result.scalars().all())

        if not milestones or len(milestones) < 2:
            return empty

        rows = []
        for m in milestones:
            rows.append({
                "sequence": m.sequence,
                "title": m.title,
                "percent": m.percent,
                "amount_cents": m.amount_cents or 0,
                "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                "paid_at": m.paid_at,
                "is_current": m.invoice_id == document.id,
            })

        current = next((r for r in rows if r["is_current"]), None)
        total_cents = sum(r["amount_cents"] for r in rows)
        paid_cents = sum(r["amount_cents"] for r in rows if r["status"] == "PAID")
        paid_percent = int(round(paid_cents / total_cents * 100)) if total_cents else 0

        return {
            "payment_schedule": rows,
            "current_milestone": current,
            "current_amount_cents": current["amount_cents"] if current else None,
            "paid_percent": paid_percent,
            "paid_amount_cents": paid_cents,
            "total_schedule_cents": total_cents,
            "source_quote_number": quote.number,
            "has_schedule": True,
        }

    async def _get_source_quote_number(self, db: AsyncSession, document: Document) -> str | None:
        if document.type != DocumentType.FACTURE or not document.source_document_id:
            return None
        
        try:
            stmt = select(Document).where(Document.id == document.source_document_id)
            result = await db.execute(stmt)
            source = result.scalar_one_or_none()
            return source.number if source else None
        except Exception as e:
            logger.warning(f"Impossible de charger le devis source: {e}")
            return None

    def _build_context(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
        source_quote_number: str | None = None,
    ) -> dict:
        totals = self._calculate_totals(document.items)

        context = {
            "document": document,
            "template": template,
            "user": user,
            "client": client,
            "items": document.items,
            "totals": totals,
            "currency": get_currency_symbol(user.currency or "XOF"),
            "source_quote_number": source_quote_number,
        }
        return context

    # ✅ MODIF 2 : appeler _build_invoice_schedule_context et merger
    async def render_html(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
        db: AsyncSession = None,
    ) -> str:
        """
        Rend le HTML d'un document (devis ou facture).
        Nécessite une session DB pour charger les relations (devis source, échéancier).
        """
        try:
            layout_file = self._get_layout_file(template.layout_style, document.type)
            tmpl = self.env.get_template(layout_file)
            
            source_quote_number = await self._get_source_quote_number(db, document)
            
            context = self._build_context(
                document, template, user, client, currency, source_quote_number
            )
            
            # ✅ NOUVEAU : fusionner le suivi de paiement pour les factures
            if db:
                schedule_context = await self._build_invoice_schedule_context(db, document)
                context.update(schedule_context)
            
            return tmpl.render(**context)
        except Exception as e:
            logger.error(f"Erreur lors du rendu HTML: {e}", exc_info=True)
            raise

    # ✅ MODIF 3 : render_html_preview reste inchangé (pas de DB, pas de suivi)
    def render_html_preview(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> str:
        """
        Rend le HTML pour le preview en temps réel (pas de DB).
        Le suivi de paiement sera masqué (has_schedule = False par défaut).
        """
        try:
            layout_file = self._get_layout_file(template.layout_style, document.type)
            tmpl = self.env.get_template(layout_file)
            context = self._build_context(document, template, user, client, currency)
            return tmpl.render(**context)
        except Exception as e:
            logger.error(f"Erreur lors du rendu HTML preview: {e}", exc_info=True)
            raise

    def _get_mock_user(self) -> User:
        return User(
            id=uuid4(),
            email="demo@exemple.com",
            company_name="Entreprise Démo SARL",
            address="123 Avenue de la République\n75001 Paris, France",
            phone="+33 1 23 45 67 89",
            tax_id="FR12345678901",
            vat_number="FR12345678901",
            payment_info="IBAN: FR76 1234 5678 9012 3456 7890 123\nBIC: BNPAFRPP\nBanque: BNP Paribas",
        )

    def render_preview_html(
        self,
        template: DocumentTemplate,
        user: User = None,
        currency: str = None,
        doc_type: DocumentType = DocumentType.DEVIS,
    ) -> str:
        if user is None:
            user = self._get_mock_user()

        fake_doc = Document(
            id=uuid4(),
            type=doc_type,
            status=DocumentStatus.DRAFT if doc_type == DocumentType.DEVIS else DocumentStatus.SENT,
            number="DEV-2026-001" if doc_type == DocumentType.DEVIS else "FACT-2026-001",
            created_at=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            user_id=user.id,
            client_id=uuid4(),
            template_id=None,
        )

        fake_client = Client(
            id=uuid4(),
            name="Client Exemple SARL",
            email="contact@client-exemple.com",
            address="456 Boulevard Saint-Germain\n75007 Paris, France",
            phone="+33 1 98 76 54 32",
            user_id=user.id,
        )

        fake_items = [
            DocumentItem(
                id=uuid4(),
                description="Développement site web vitrine",
                quantity=1,
                unit_price_cents=50000000,
                tax_rate=19.25,
                document_id=fake_doc.id,
            ),
            DocumentItem(
                id=uuid4(),
                description="Hébergement annuel (12 mois)",
                quantity=1,
                unit_price_cents=5000000,
                tax_rate=19.25,
                document_id=fake_doc.id,
            ),
            DocumentItem(
                id=uuid4(),
                description="Maintenance mensuelle (x3)",
                quantity=3,
                unit_price_cents=3000000,
                tax_rate=19.25,
                document_id=fake_doc.id,
            ),
        ]
        fake_doc.items = fake_items

        return self.render_html_preview(fake_doc, template, user, fake_client, currency)

    async def _generate_screenshot(self, html_string: str) -> bytes:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
                )
                page = await browser.new_page(viewport={"width": 794, "height": 1123})
                await page.set_content(html_string, wait_until="domcontentloaded")
                await page.wait_for_timeout(800)
                screenshot = await page.screenshot(full_page=True, type="png")
                await browser.close()
                return screenshot
        except Exception as e:
            logger.error(f"Erreur Playwright: {e}", exc_info=True)
            raise

    async def render_template_preview_png(
        self,
        layout_style: str,
        currency: str = "FCFA",
    ) -> bytes:
        if layout_style in self._preview_cache:
            logger.info(f"Preview {layout_style} servi depuis le cache")
            return self._preview_cache[layout_style]

        try:
            mock_template = DocumentTemplate(
                id=uuid4(),
                name=f"Template {layout_style}",
                layout_style=layout_style,
                primary_color="#0ea5e9" if layout_style == "modern" else "#1a1a1a",
                secondary_color="#64748b",
                footer_text="Aperçu du template - Document généré automatiquement",
                show_tax_id=True,
                show_bank_details=True,
            )

            html_string = self.render_preview_html(
                template=mock_template,
                user=None,
                currency=currency,
                doc_type=DocumentType.DEVIS,
            )

            screenshot = await self._generate_screenshot(html_string)
            self._preview_cache[layout_style] = screenshot
            logger.info(f"Preview {layout_style} généré et mis en cache")
            return screenshot

        except Exception as e:
            logger.error(f"Erreur génération preview PNG: {e}", exc_info=True)
            raise
    
    async def render_png_from_html(self, html_string: str) -> bytes:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                page = await browser.new_page(viewport={"width": 794, "height": 1123})
                await page.set_content(html_string, wait_until="domcontentloaded")
                await page.wait_for_timeout(500)
                screenshot = await page.screenshot(full_page=True, type="png")
                await browser.close()
                return screenshot
        except Exception as e:
            logger.error(f"Erreur génération PNG depuis HTML: {e}", exc_info=True)
            raise

    async def render_pdf_from_html(self, html_string: str) -> BytesIO:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                page = await browser.new_page()
                await page.set_content(html_string, wait_until="domcontentloaded")
                await page.wait_for_timeout(500)
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "15mm", "right": "20mm", "bottom": "15mm", "left": "20mm"}
                )
                await browser.close()
                pdf_buffer = BytesIO(pdf_bytes)
                pdf_buffer.seek(0)
                return pdf_buffer
        except Exception as e:
            logger.error(f"Erreur génération PDF depuis HTML: {e}", exc_info=True)
            raise

    async def render_pdf(
        self,
        db: AsyncSession,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> BytesIO:
        try:
            html_string = await self.render_html(db, document, template, user, client, currency)

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                page = await browser.new_page()
                await page.set_content(html_string, wait_until="domcontentloaded")
                await page.wait_for_timeout(500)
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
                )
                await browser.close()
                pdf_buffer = BytesIO(pdf_bytes)
                pdf_buffer.seek(0)
                return pdf_buffer
        except Exception as e:
            logger.error(f"Erreur génération PDF: {e}", exc_info=True)
            raise


pdf_renderer = PDFRenderer()