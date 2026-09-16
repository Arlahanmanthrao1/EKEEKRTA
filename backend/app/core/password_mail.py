import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


def recovery_email_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def send_password_reset_email(recipient: str, display_name: str, reset_url: str) -> None:
    """Deliver a password-reset link through the operator-configured SMTP service."""
    message = EmailMessage()
    message["Subject"] = "Reset your EKEEKRTA password"
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message.set_content(
        f"Hello {display_name},\n\n"
        "A password reset was requested for your EKEEKRTA account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        f"This link expires in {settings.password_reset_expire_minutes} minutes and can be used once. "
        "If you did not request this, you can ignore this email.\n"
    )
    password = settings.smtp_password.get_secret_value()
    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context) as server:
            if settings.smtp_username:
                server.login(settings.smtp_username, password)
            server.send_message(message)
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_security == "starttls":
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, password)
        server.send_message(message)
