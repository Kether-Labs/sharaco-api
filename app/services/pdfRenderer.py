import os
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from io import BytesIO
from app.models.document import Document
from app.models.document_template import DocumentTemplate
from app.models.client import Client
from app.models.user import User
from app.services.documentService import DocumentService


class PDFRenderer:
    """Moteur de rendu HTML/PDF pour les devis et factures."""

    # Dossier des templates HTML
    TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

    # Layout disponibles
    LAYOUT_MAP = {
        "classic": "classic.html",
        "modern": "modern.html",
        "minimal": "minimal.html",
    }

    DEFAULT_CURRENCY = "FCFA"

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(self.TEMPLATES_DIR),
            autoescape=True,
        )

    def _get_layout_file(self, layout_style: str) -> str:
        """Retourne le fichier HTML correspondant au layout."""
        return self.LAYOUT_MAP.get(layout_style, "classic.html")

    def _build_context(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> dict:
        """Construit le contexte de variables pour le template Jinja2."""
        totals = DocumentService.calculate_totals(document.items)

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
        """Rend le HTML complet (pour aperçu dans le navigateur)."""
        layout_file = self._get_layout_file(template.layout_style)
        tmpl = self.env.get_template(layout_file)
        context = self._build_context(document, template, user, client, currency)
        return tmpl.render(**context)

    def render_pdf(
        self,
        document: Document,
        template: DocumentTemplate,
        user: User,
        client: Client,
        currency: str = None,
    ) -> BytesIO:
        """Rend le PDF binaire (pour téléchargement)."""
        html_string = self.render_html(document, template, user, client, currency)
        pdf_buffer = BytesIO()
        HTML(string=html_string).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        return pdf_buffer

    def render_preview_html(
        self,
        template: DocumentTemplate,
        user: User,
        currency: str = None,
    ) -> str:
        """Rend un aperçu HTML avec des FAUSSES données (pour la customisation du template)."""
        from datetime import datetime, timezone
        from app.models.document import DocumentType, DocumentStatus, DocumentItem
        from app.models.client import Client
        from uuid import uuid4

        # Faux document pour l'aperçu
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

        # Faux client
        fake_client = Client(
            id=uuid4(),
            name="Client Exemple",
            email="client@exemple.com",
            address="123 Rue Exemple, Douala",
            phone="+237 6XX XXX XXX",
            user_id=user.id,
        )

        # Faux items
        fake_items = [
            DocumentItem(
                id=uuid4(),
                description="Developpement site web vitrine",
                quantity=1,
                unit_price_cents=500000,
                tax_rate=19,
                document_id=fake_doc.id,
            ),
            DocumentItem(
                id=uuid4(),
                description="Hebergement annuel",
                quantity=1,
                unit_price_cents=50000,
                tax_rate=19,
                document_id=fake_doc.id,
            ),
            DocumentItem(
                id=uuid4(),
                description="Maintenance mensuelle (x3)",
                quantity=3,
                unit_price_cents=30000,
                tax_rate=19,
                document_id=fake_doc.id,
            ),
        ]
        fake_doc.items = fake_items

        return self.render_html(fake_doc, template, user, fake_client, currency)


# Instance globale
pdf_renderer = PDFRenderer()
