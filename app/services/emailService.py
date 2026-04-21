import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service d'envoi d'emails.
    Supporte 2 modes (configuré via EMAIL_PROVIDER dans .env) :
      - "smtp"  : Envoi via SMTP classique (GRATUIT — Gmail, OVH, Infomaniak, etc.)
      - "resend": Envoi via l'API Resend
    """

    # ============================================================
    # EMAIL AVEC PIÈCE JOINTE (envoi de devis/facture)
    # ============================================================

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
        """Envoie un email avec ou sans pièce jointe PDF."""
        provider = getattr(settings, "EMAIL_PROVIDER", "smtp")

        if provider == "resend":
            return await EmailService._send_via_resend(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                pdf_bytes=pdf_bytes,
                pdf_filename=pdf_filename,
                from_name=from_name,
            )
        else:
            return await EmailService._send_via_smtp(
                to_email=to_email,
                to_name=to_name,
                from_name=from_name,
                subject=subject,
                html_content=html_content,
                pdf_bytes=pdf_bytes,
                pdf_filename=pdf_filename,
            )

    # ============================================================
    # EMAIL DE RELANCE (sans pièce jointe, avec lien)
    # ============================================================

    @staticmethod
    async def send_reminder_email(
        to_email: str,
        to_name: str,
        from_name: str,
        subject: str,
        html_content: str,
        document_link: str,
    ) -> dict:
        """Envoie un email de relance avec un lien vers le devis."""
        provider = getattr(settings, "EMAIL_PROVIDER", "smtp")

        if provider == "resend":
            return await EmailService._send_via_resend(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                from_name=from_name,
            )
        else:
            return await EmailService._send_via_smtp(
                to_email=to_email,
                to_name=to_name,
                from_name=from_name,
                subject=subject,
                html_content=html_content,
            )

    # ============================================================
    # SMTP (GRATUIT)
    # ============================================================

    @staticmethod
    async def _send_via_smtp(
        to_email: str,
        to_name: str,
        from_name: str,
        subject: str,
        html_content: str,
        pdf_bytes: Optional[bytes] = None,
        pdf_filename: Optional[str] = None,
    ) -> dict:
        """
        Envoie un email via SMTP classique.
        Configure dans .env :
          SMTP_HOST=smtp.gmail.com
          SMTP_PORT=587
          SMTP_USER=tonemail@gmail.com
          SMTP_PASSWORD=mot_de_passe_app
          SMTP_FROM_NAME=Sharaco
        """
        smtp_host = getattr(settings, "SMTP_HOST", "smtp.gmail.com")
        smtp_port = getattr(settings, "SMTP_PORT", 587)
        smtp_user = getattr(settings, "SMTP_USER", "")
        smtp_password = getattr(settings, "SMTP_PASSWORD", "")
        from_email = smtp_user  # L'email d'envoi = ton compte SMTP

        # Construire le message MIME
        msg = MIMEMultipart()
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
        msg["Subject"] = subject

        # Corps HTML
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # Pièce jointe PDF
        if pdf_bytes and pdf_filename:
            part = MIMEBase("application", "pdf")
            part.set_payload(pdf_bytes)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={pdf_filename}",
            )
            msg.attach(part)

        try:
            # Connexion SMTP
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_password)

            # Envoi
            server.sendmail(from_email, [to_email], msg.as_string())
            server.quit()

            logger.info(f"Email SMTP envoyé à {to_email}")
            return {"status": "sent", "provider": "smtp", "to": to_email}

        except smtplib.SMTPAuthenticationError:
            logger.error(f"Erreur auth SMTP — vérifie SMTP_USER et SMTP_PASSWORD")
            raise Exception("Erreur d'authentification SMTP — vérifie tes identifiants")
        except smtplib.SMTPException as e:
            logger.error(f"Erreur SMTP : {str(e)}")
            raise Exception(f"Erreur SMTP : {str(e)}")
        except Exception as e:
            logger.error(f"Erreur envoi email SMTP à {to_email}: {str(e)}")
            raise

    # ============================================================
    # RESEND (API)
    # ============================================================

    @staticmethod
    async def _send_via_resend(
        to_email: str,
        subject: str,
        html_content: str,
        from_name: str = "Sharaco",
        pdf_bytes: Optional[bytes] = None,
        pdf_filename: Optional[str] = None,
    ) -> dict:
        """
        Envoie un email via l'API Resend.
        Configure dans .env :
          RESEND_API_KEY=re_xxxxxxxx
        """
        import resend as resend_lib

        resend_lib.api_key = settings.RESEND_API_KEY

        # Domaine Resend — à remplacer par ton domaine vérifié
        from_domain = getattr(settings, "RESEND_FROM_DOMAIN", "onboarding@resend.dev")

        params = {
            "from": f"{from_name} <{from_domain}>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }

        # Pièce jointe PDF
        if pdf_bytes and pdf_filename:
            import base64
            params["attachments"] = [
                {
                    "filename": pdf_filename,
                    "content": base64.b64encode(pdf_bytes).decode("utf-8"),
                }
            ]

        try:
            response = resend_lib.Emails.send(params)
            logger.info(f"Email Resend envoyé à {to_email} — ID: {response.get('id', 'unknown')}")
            return response
        except Exception as e:
            logger.error(f"Erreur Resend à {to_email}: {str(e)}")
            raise