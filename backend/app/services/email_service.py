import smtplib
from email.mime.text import MIMEText
from app.config import settings

async def send_otp_email(to_email: str, otp_code: str) -> bool:
    if not settings.smtp_user or not settings.smtp_pass:
        # Dev mode: log OTP instead of sending
        print(f"[DEV MFA] OTP for {to_email}: {otp_code}")
        return True

    msg = MIMEText(
        f"Your Penguin CRM verification code is: {otp_code}\n\n"
        f"This code expires in 5 minutes.\n\n"
        f"If you didn't request this code, please ignore this email."
    )
    msg["Subject"] = "Penguin CRM — Login Verification Code"
    msg["From"] = settings.mfa_from_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False
