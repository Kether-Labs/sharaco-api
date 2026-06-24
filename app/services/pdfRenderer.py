import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from io import BytesIO
from playwright.async_api import async_playwright
from app.models.document import Document, DocumentItem
from app.models.document_template import DocumentTemplate
from app.models.client import Client
from app.models.user import User
import logging
from datetime import datetime, timezone
from uuid import uuid4
from app.models.document import DocumentType, DocumentStatus

logger = logging.getLogger(__name__)


class PDFRenderer:
    """Moteur de rendu HTML/PDF pour les devis et factures."""

    TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

    LAYOUT_MAP = {
        "classic": "classic.html",
        "modern": "modern.html",
        "minimal": "minimal.html",
        "bold": "bold.html",
        "elegant": "elegant.html",
    }

    DEFAULT_CURRENCY = "FCFA"

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATES_DIR)),
            autoescape=True,
            cache_size=100,
        )
        # Cache pour les previews (clé = layout_id)
        self._preview_cache: dict[str, bytes] = {}

    def _get_layout_file(self, layout_style: str) -> str:
        return self.LAYOUT_MAP.get(layout_style, "classic.html")

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

    def _build_context(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> dict:
        totals = self._calculate_totals(document.items)

        return {
            "document": document,
            "template": template,
            "user": user,
            "client": client,
            "items": document.items,
            "totals": totals,
            "currency": currency or self.DEFAULT_CURRENCY,
        }

    def render_html(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> str:
        try:
            layout_file = self._get_layout_file(template.layout_style)
            tmpl = self.env.get_template(layout_file)
            context = self._build_context(document, template, user, client, currency)
            return tmpl.render(**context)
        except Exception as e:
            logger.error(f"Erreur lors du rendu HTML: {e}", exc_info=True)
            raise

    def _get_mock_user(self) -> User:
        """Crée un utilisateur mock pour les previews publiques."""
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
    ) -> str:
        """Rend un aperçu HTML avec des FAUSSES données."""
        # Utiliser le user fourni ou le mock
        if user is None:
            user = self._get_mock_user()

        fake_doc = Document(
            id=uuid4(),
            type=DocumentType.DEVIS,
            status=DocumentStatus.DRAFT,
            number="DEV-2026-001",
            created_at=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            user_id=user.id,
            client_id=uuid4(),
            template_id=template.id,
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

        return self.render_html(fake_doc, template, user, fake_client, currency)

    async def _generate_screenshot(self, html_string: str) -> bytes:
        """Génère un screenshot PNG à partir du HTML."""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                    ]
                )

                page = await browser.new_page(
                    viewport={"width": 794, "height": 1123}
                )

                await page.set_content(
                    html_string,
                    wait_until="domcontentloaded",
                )

                await page.wait_for_timeout(800)

                screenshot = await page.screenshot(
                    full_page=True,
                    type="png",
                )

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
        """Génère une image PNG d'aperçu du template (PUBLIC - sans user)."""
        
        # Vérifier le cache (clé = layout_id uniquement)
        if layout_style in self._preview_cache:
            logger.info(f"Preview {layout_style} servi depuis le cache")
            return self._preview_cache[layout_style]

        try:
            # Créer un template mock
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

            # Générer le HTML (user optionnel, sera mocké)
            html_string = self.render_preview_html(
                template=mock_template,
                user=None,  # Pas de user, sera mocké
                currency=currency,
            )

            # Générer le PNG
            screenshot = await self._generate_screenshot(html_string)

            # Stocker dans le cache
            self._preview_cache[layout_style] = screenshot
            logger.info(f"Preview {layout_style} généré et mis en cache")

            return screenshot

        except Exception as e:
            logger.error(f"Erreur génération preview PNG: {e}", exc_info=True)
            raise

    async def render_pdf(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> BytesIO:
        try:
            html_string = self.render_html(document, template, user, client, currency)

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


# Instance globale
pdf_renderer = PDFRenderer()