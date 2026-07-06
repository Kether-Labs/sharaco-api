# app/services/emailService.py
import asyncio
import resend
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Initialisation de Resend
if settings.RESEND_API_KEY:
    resend.api_key = settings.RESEND_API_KEY

# Configuration Jinja2 pour les templates
EMAIL_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"
email_env = Environment(
    loader=FileSystemLoader(str(EMAIL_TEMPLATES_DIR)),
    autoescape=True,
)


class EmailService:
    
    @staticmethod
    async def _send_email(
        to_email: str,
        subject: str,
        html_content: str,
    ) -> dict:
        """Envoie un email via Resend (de manière asynchrone)."""
        try:
            params = resend.Emails.SendParams(
                from_=settings.RESEND_FROM_EMAIL,
                to=[to_email],
                subject=subject,
                html=html_content,
                # Optionnel : activer le tracking d'ouverture (nécessite un domaine vérifié)
                # headers={"X-Entity-Ref-ID": "unique_id"} 
            )
            
            # Exécution dans un thread pour ne pas bloquer l'event loop FastAPI
            response = await asyncio.to_thread(resend.Emails.send, params)
            
            logger.info(f"✅ Email envoyé à {to_email} | ID: {response.id}")
            return {"success": True, "id": response.id}
            
        except Exception as e:
            logger.error(f"❌ Erreur envoi Resend: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @staticmethod
    async def send_devis(
        to_email: str,
        client_name: str,
        document_number: str,
        total_amount: str,
        preview_url: str,
        user_name: str,
        user_company: str,
        custom_message: str = "",
    ) -> dict:
        """Envoie un devis."""
        template = email_env.get_template("devis.html")
        html = template.render(
            to_name=client_name,
            document_number=document_number,
            total_amount=total_amount,
            preview_url=preview_url,
            user_name=user_name,
            user_company=user_company,
            custom_message=custom_message,
        )
        
        return await EmailService._send_email(
            to_email=to_email,
            subject=f"Devis {document_number} de {user_company}",
            html_content=html,
        )

    @staticmethod
    async def send_facture(
        to_email: str,
        client_name: str,
        document_number: str,
        total_amount: str,
        preview_url: str,
        user_name: str,
        user_company: str,
        custom_message: str = "",
    ) -> dict:
        """Envoie une facture."""
        template = email_env.get_template("facture.html")
        html = template.render(
            to_name=client_name,
            document_number=document_number,
            total_amount=total_amount,
            preview_url=preview_url,
            user_name=user_name,
            user_company=user_company,
            custom_message=custom_message,
        )
        
        return await EmailService._send_email(
            to_email=to_email,
            subject=f"Facture {document_number} de {user_company}",
            html_content=html,
        )