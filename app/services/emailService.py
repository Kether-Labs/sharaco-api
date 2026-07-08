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

# Templates Jinja2
EMAIL_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"
email_env = Environment(
    loader=FileSystemLoader(str(EMAIL_TEMPLATES_DIR)),
    autoescape=True,
)


class EmailService:
    
    @staticmethod
    async def _send_via_resend(
        to_email: str,
        subject: str,
        html_content: str,
    ) -> dict:
        """Envoie via Resend API."""
        try:
            from_email = settings.RESEND_FROM_EMAIL or "Sharaco <onboarding@resend.dev>"
            
            logger.info(f"📧 Envoi Resend → {to_email} | From: {from_email}")
            
            email_data = {
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            }
            
            response = await asyncio.to_thread(resend.Emails.send, email_data)
            
            email_id = response.get("id") if isinstance(response, dict) else response.id
            logger.info(f"✅ Email Resend envoyé | ID: {email_id}")
            return {"success": True, "id": email_id, "provider": "resend"}
            
        except Exception as e:
            logger.error(f"❌ Erreur Resend: {e}", exc_info=True)
            return {"success": False, "error": str(e), "provider": "resend"}
    
    @staticmethod
    async def _send_via_smtp(
        to_email: str,
        subject: str,
        html_content: str,
    ) -> dict:
        """Envoie via SMTP classique."""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart()
            msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(html_content, "html", "utf-8"))
            
            def _send_sync():
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                    server.ehlo()
                    if settings.SMTP_USE_TLS:
                        server.starttls()
                        server.ehlo()
                    
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    
                    server.sendmail(settings.SMTP_USER, [to_email], msg.as_string())
            
            await asyncio.to_thread(_send_sync)
            logger.info(f"✅ Email SMTP envoyé à {to_email}")
            return {"success": True, "provider": "smtp"}
            
        except Exception as e:
            logger.error(f"❌ Erreur SMTP: {e}", exc_info=True)
            return {"success": False, "error": str(e), "provider": "smtp"}
    
    @staticmethod
    async def _send_email(
        to_email: str,
        subject: str,
        html_content: str,
    ) -> dict:
        """Dispatch vers le bon provider selon la config."""
        if settings.EMAIL_PROVIDER == "resend":
            if not settings.RESEND_API_KEY:
                logger.error("❌ RESEND_API_KEY non configuré")
                return {"success": False, "error": "Resend API key missing"}
            return await EmailService._send_via_resend(to_email, subject, html_content)
        
        elif settings.EMAIL_PROVIDER == "smtp":
            if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
                logger.error("❌ SMTP credentials non configurés")
                return {"success": False, "error": "SMTP credentials missing"}
            return await EmailService._send_via_smtp(to_email, subject, html_content)
        
        else:
            logger.error(f"❌ Provider inconnu: {settings.EMAIL_PROVIDER}")
            return {"success": False, "error": f"Unknown provider: {settings.EMAIL_PROVIDER}"}

    async def send_devis(
    to_email: str,
    client_name: str,
    document_number: str,
    total_amount: str,
    client_url: str,  # ✅ Renommé de preview_url à client_url
    due_date: str = None,  # ✅ Ajout pour cohérence
    user_name: str = "",
    user_company: str = "",
    custom_message: str = "",
    ) -> dict:
   
        template = email_env.get_template("devis.html")
        html = template.render(
            to_name=client_name,
            document_number=document_number,
            total_amount=total_amount,
            client_url=client_url,  # ✅ Lien privé
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
    client_url: str,  # ✅ Renommé
    due_date: str = None,  # ✅ Ajout
    user_name: str = "",
    user_company: str = "",
    custom_message: str = "",
    ) -> dict:
        """Envoie une facture avec le lien PRIVÉ client."""
        template = email_env.get_template("facture.html")
        html = template.render(
            to_name=client_name,
            document_number=document_number,
            total_amount=total_amount,
            client_url=client_url,  # ✅ Lien privé
            due_date=due_date,
            user_name=user_name,
            user_company=user_company,
            custom_message=custom_message,
        )
        
        return await EmailService._send_email(
            to_email=to_email,
            subject=f"Facture {document_number} de {user_company}",
            html_content=html,
        )