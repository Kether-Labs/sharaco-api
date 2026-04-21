import resend
from app.core.config import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Service d'envoi d'emails via l'API Resend."""

    @staticmethod
    def _get_client():
        """Initialise le client Resend avec la clé API."""
        resend.api_key = settings.RESEND_API_KEY

    @staticmethod
    async def send_document_email(
        to_email: str,
        to_name: str,
        from_name: str,
        subject: str,
        html_content: str,
        pdf_bytes: Optional[bytes] = None,
        pdf_filename: Optional[str] = None,
    ) -> dict:
        """
        Envoie un email avec ou sans pièce jointe PDF.
        Retourne la réponse de l'API Resend.
        """
        EmailService._get_client()

        params = {
            "from": f"{from_name} <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }

        # Ajouter le PDF en pièce jointe si fourni
        if pdf_bytes and pdf_filename:
            import base64
            params["attachments"] = [
                {
                    "filename": pdf_filename,
                    "content": base64.b64encode(pdf_bytes).decode("utf-8"),
                }
            ]

        try:
            response = resend.Emails.send(params)
            logger.info(f"Email envoyé à {to_email} — ID: {response.get('id', 'unknown')}")
            return response
        except Exception as e:
            logger.error(f"Erreur envoi email à {to_email}: {str(e)}")
            raise

    @staticmethod
    async def send_reminder_email(
        to_email: str,
        to_name: str,
        from_name: str,
        subject: str,
        html_content: str,
        document_link: str,
    ) -> dict:
        """
        Envoie un email de relance avec un lien vers le devis.
        Pas de pièce jointe PDF — le client clique sur le lien.
        """
        EmailService._get_client()

        params = {
            "from": f"{from_name} <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }

        try:
            response = resend.Emails.send(params)
            logger.info(f"Relance envoyée à {to_email} — ID: {response.get('id', 'unknown')}")
            return response
        except Exception as e:
            logger.error(f"Erreur relance à {to_email}: {str(e)}")
            raise
