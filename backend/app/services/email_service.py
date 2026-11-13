import asyncio
import base64
import datetime
import email.utils
import hashlib
import hmac
import html
import logging
import smtplib
import ssl
import urllib.parse
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.services.settings_service import get_runtime_setting
from backend.app.models.notification import NotificationLog

logger = logging.getLogger("email_service")

PRODUCT_BRAND_NAME = "SD-GEN016 — Service Desk Генератора"
PRODUCT_SENDER_NAME = "SD-GEN016"
PRODUCT_SUBTITLE = "Автоматизована система контролю та моніторингу"
_EMAIL_LOGO_PATH = Path(__file__).resolve().parents[3] / "frontend" / "icons" / "email-logo.png"
_FALLBACK_LOGO_PATH = Path(__file__).resolve().parents[3] / "frontend" / "icons" / "logo.png"


@lru_cache(maxsize=1)
def _get_email_logo_bytes() -> Optional[bytes]:
    """Load and cache circular product logo bytes for inline CID email attachment."""
    for path in (_EMAIL_LOGO_PATH, _FALLBACK_LOGO_PATH):
        try:
            if path.is_file():
                return path.read_bytes()
        except Exception:
            continue
    return None


def get_public_base_url(request_base_url: Optional[str] = None) -> str:
    """Resolve external public base URL (HTTPS) for unsubscribe and reset links."""
    if request_base_url:
        return str(request_base_url).rstrip("/")
    domain = (settings.PRIMARY_DOMAIN or "").strip().strip("/")
    if domain and domain.lower() not in ("localhost", "127.0.0.1"):
        if domain.startswith(("http://", "https://")):
            return domain.rstrip("/")
        return f"https://{domain}"
    return "http://localhost:8000"


def generate_unsubscribe_token(
    email_addr: str,
    user_id: Optional[int] = None,
    action: str = "unsub",
) -> str:
    """Create a stateless HMAC-SHA256 signed token for 1-click email unsubscribe/resubscribe."""
    clean_email = (email_addr or "").strip().lower()
    uid_str = str(user_id) if user_id is not None else "0"
    payload = f"{action}|{uid_str}|{clean_email}".encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    secret = (settings.APP_SECRET_KEY or "sd_gen016_fallback_secret").encode("utf-8")
    sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{payload_b64}.{sig}"


def verify_unsubscribe_token(
    token: str,
    expected_action: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Verify HMAC-SHA256 unsubscribe/resubscribe token and extract email & user_id."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.strip().rsplit(".", 1)
        secret = (settings.APP_SECRET_KEY or "sd_gen016_fallback_secret").encode("utf-8")
        expected_sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        action, uid_str, email_addr = raw.split("|", 2)
        if expected_action and action != expected_action:
            return None
        uid = int(uid_str) if uid_str.isdigit() and int(uid_str) > 0 else None
        clean_email = email_addr.strip().lower()
        if "@" not in clean_email:
            return None
        return {"action": action, "user_id": uid, "email": clean_email}
    except Exception:
        return None


def build_unsubscribe_url(
    email_addr: str,
    user_id: Optional[int] = None,
    base_url: Optional[str] = None,
) -> str:
    tok = generate_unsubscribe_token(email_addr=email_addr, user_id=user_id, action="unsub")
    base = get_public_base_url(base_url)
    return f"{base}/api/v1/email/unsubscribe?token={urllib.parse.quote(tok, safe='')}"


def _format_from_header(from_addr: Optional[str], fallback_user: Optional[str]) -> str:
    """Format RFC 5322 From header with product display name when only raw address is configured."""
    candidate = (from_addr or fallback_user or "").strip()
    if not candidate:
        return ""
    disp, addr = email.utils.parseaddr(candidate)
    if not addr:
        return candidate
    if disp:
        return email.utils.formataddr((disp, addr))
    return email.utils.formataddr((PRODUCT_SENDER_NAME, addr))


def _wrap_html_template(
    title: str,
    content_html: str,
    action_button_html: str = "",
    subtitle: Optional[str] = None,
    unsubscribe_url: Optional[str] = None,
    embed_logo: bool = True,
) -> str:
    """Wraps body content in a modern, responsive product-branded email template."""
    logo_html = ""
    if embed_logo and _get_email_logo_bytes():
        logo_html = (
            '<div style="margin: 0 auto 12px auto; text-align: center;">'
            '<img src="cid:sdgen-logo" alt="SD-GEN016" width="58" height="58" '
            'style="display: inline-block; width: 58px; height: 58px; border-radius: 50%; '
            'border: 2px solid rgba(56, 189, 248, 0.55); background: #0f172a;">'
            "</div>"
        )

    unsub_html = ""
    if unsubscribe_url:
        safe_url = html.escape(unsubscribe_url, quote=True)
        unsub_html = (
            '<p style="margin: 10px 0 0 0; font-size: 11px; line-height: 1.4; color: #94a3b8;">'
            'Отримувати менше листів? '
            f'<a href="{safe_url}" style="color: #94a3b8; text-decoration: underline;">Відписатися від розсилки</a>'
            "</p>"
        )

    sub_text = subtitle or PRODUCT_SUBTITLE
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: #f1f5f9;
      color: #1e293b;
    }}
    .email-container {{
      max-width: 600px;
      margin: 24px auto;
      background: #ffffff;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
      border: 1px solid #e2e8f0;
    }}
    .email-header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #ffffff;
      padding: 24px 32px;
      text-align: center;
    }}
    .email-header h1 {{
      margin: 0 0 6px 0;
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.01em;
      color: #f8fafc;
    }}
    .email-header p {{
      margin: 0;
      font-size: 13px;
      color: #94a3b8;
    }}
    .email-body {{
      padding: 32px;
      line-height: 1.6;
      font-size: 15px;
    }}
    .info-box {{
      background: #f8fafc;
      border-left: 4px solid #3b82f6;
      padding: 16px;
      border-radius: 6px;
      margin: 20px 0;
    }}
    .warning-box {{
      background: #fffbeb;
      border-left: 4px solid #f59e0b;
      padding: 16px;
      border-radius: 6px;
      margin: 20px 0;
      color: #92400e;
    }}
    .alert-box {{
      background: #fef2f2;
      border-left: 4px solid #ef4444;
      padding: 16px;
      border-radius: 6px;
      margin: 20px 0;
      color: #991b1b;
    }}
    .success-box {{
      background: #f0fdf4;
      border-left: 4px solid #22c55e;
      padding: 16px;
      border-radius: 6px;
      margin: 20px 0;
      color: #166534;
    }}
    .btn-container {{
      text-align: center;
      margin: 28px 0;
    }}
    .btn {{
      display: inline-block;
      background-color: #2563eb;
      color: #ffffff !important;
      text-decoration: none;
      font-weight: 600;
      font-size: 15px;
      padding: 12px 28px;
      border-radius: 8px;
      box-shadow: 0 2px 6px rgba(37, 99, 235, 0.35);
    }}
    .email-footer {{
      background: #f8fafc;
      border-top: 1px solid #e2e8f0;
      padding: 18px 32px;
      text-align: center;
      font-size: 12px;
      color: #64748b;
    }}
    .token-code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 20px;
      font-weight: bold;
      letter-spacing: 2px;
      background: #e2e8f0;
      padding: 8px 16px;
      border-radius: 6px;
      display: inline-block;
      margin: 8px 0;
      color: #0f172a;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="email-header">
      {logo_html}
      <h1>⚡ {html.escape(PRODUCT_BRAND_NAME)}</h1>
      <p>{html.escape(sub_text)}</p>
    </div>
    <div class="email-body">
      {content_html}
      {action_button_html}
    </div>
    <div class="email-footer">
      <p style="margin: 0 0 4px 0;">Це автоматичне системне сповіщення. Будь ласка, не відповідайте на цей лист.</p>
      <p style="margin: 0;">© {datetime.datetime.now().year} {html.escape(PRODUCT_BRAND_NAME)}.</p>
      {unsub_html}
    </div>
  </div>
</body>
</html>
"""


def _strip_html(html_str: str) -> str:
    """Simple plain-text converter for email fallback."""
    import re
    clean = re.sub(r"<style[\s\S]*?</style>", "", html_str, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html.unescape(clean)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    return "\n".join(lines)


def send_smtp_message_sync(
    host: str,
    port: int,
    user: str,
    password: str,
    use_ssl: bool,
    from_addr: str,
    to_addr: Union[str, List[str]],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 12.0,
    extra_headers: Optional[Dict[str, str]] = None,
) -> None:
    """
    Synchronous SMTP delivery supporting STARTTLS (e.g. Gmail 587) and SSL (e.g. Ukr.net 465).
    Raises smtplib or socket exceptions on failure.
    """
    if not host:
        raise ValueError("SMTP host is not specified")

    to_list = [to_addr] if isinstance(to_addr, str) else list(to_addr)
    to_str = ", ".join(to_list)

    formatted_from = _format_from_header(from_addr, user)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formatted_from
    msg["To"] = to_str
    msg["Date"] = email.utils.formatdate(localtime=True)

    # Deliverability & Anti-Spam Headers (RFC 5322 & RFC 3834)
    _, clean_email = email.utils.parseaddr(formatted_from or from_addr or user)
    domain_part = clean_email.split("@")[-1].strip() if "@" in clean_email else None
    msg["Message-ID"] = email.utils.make_msgid(domain=domain_part or None)
    msg["Reply-To"] = formatted_from
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"

    if extra_headers:
        for hdr_k, hdr_v in extra_headers.items():
            if hdr_k and hdr_v and hdr_k not in msg:
                msg[hdr_k] = hdr_v

    plain_content = text_body or _strip_html(html_body)
    msg.set_content(plain_content)
    msg.add_alternative(html_body, subtype="html")

    # Attach inline brand logo (cid:sdgen-logo) when referenced in HTML
    if "cid:sdgen-logo" in html_body:
        logo_bytes = _get_email_logo_bytes()
        if logo_bytes:
            payload = msg.get_payload()
            if isinstance(payload, list) and len(payload) >= 2:
                payload[1].add_related(
                    logo_bytes,
                    maintype="image",
                    subtype="png",
                    cid="<sdgen-logo>",
                    filename="sdgen-logo.png",
                )

    if attachments:
        for att in attachments:
            content = att.get("content")
            filename = att.get("filename", "attachment.bin")
            maintype = att.get("maintype", "application")
            subtype = att.get("subtype", "octet-stream")
            if content:
                msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    if use_ssl:
        ssl_ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ssl_ctx, timeout=timeout) as server:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.ehlo()
            # Fail-closed security rule: STARTTLS is mandatory to prevent cleartext password transmission
            if not server.has_extn("starttls"):
                raise smtplib.SMTPNotSupportedError(
                    f"Сервер {host}:{port} не підтримує обов'язковий протокол шифрування STARTTLS. "
                    "Передавання облікових даних без захищеного TLS-з'єднання заборонено."
                )
            ssl_ctx = ssl.create_default_context()
            try:
                server.starttls(context=ssl_ctx)
                server.ehlo()
            except Exception as tls_err:
                logger.error(
                    f"STARTTLS negotiation failed for {host}:{port}: {tls_err}. "
                    "Aborting delivery to prevent cleartext credential transmission."
                )
                raise smtplib.SMTPException(
                    f"Помилка встановлення захищеного з'єднання STARTTLS з сервером {host}:{port} ({tls_err}). "
                    "Автентифікацію скасовано задля безпеки облікових даних."
                ) from tls_err

            if user and password:
                server.login(user, password)
            server.send_message(msg)


def get_smtp_diagnostic_hint(error_msg: str, host: str = "") -> str:
    """
    Повертає зрозумілу прикладну інструкцію для адміністратора українською мовою
    на основі коду або тексту помилки SMTP-сервера.
    """
    err_lower = (error_msg or "").lower()
    host_lower = (host or "").lower()

    if "535" in err_lower or "authentication" in err_lower or "badcredentials" in err_lower or "username and password not accepted" in err_lower:
        if "gmail" in host_lower or "google" in host_lower:
            return (
                "Google відхилив авторизацію (535 Authentication failed).\n"
                "Звичайний пароль від пошти НЕ працює для безпеки Google. Необхідно:\n"
                "1. Увімкнути 2-етапну перевірку в налаштуваннях Google-акаунта;\n"
                "2. Перейти за посиланням myaccount.google.com/apppasswords;\n"
                "3. Створити «Пароль додатка» (App Password) з назвою 'ServiceDesk' (отримаєте 16 літер);\n"
                "4. Скопіювати цей 16-значний пароль без пробілів у поле «Пароль додатку Google» та зберегти."
            )
        elif "ukr.net" in host_lower:
            return (
                "Ukr.net відхилив авторизацію (535 Authentication failed).\n"
                "Ukr.net вимагає окремий пароль для поштових програм. Необхідно:\n"
                "1. Увійти у вашу пошту на ukr.net;\n"
                "2. Відкрити «Налаштування» -> «Керування доступом IMAP/SMTP»;\n"
                "3. Увімкнути перемикач «Доступ для зовнішніх поштових програм»;\n"
                "4. Натиснути «Створити пароль програми», скопіювати згенерований пароль та вставити у налаштування."
            )
        return "Помилка автентифікації SMTP (535). Перевірте правильність логіна та пароля додатку для цього поштового сервера."

    if "timed out" in err_lower or "timeout" in err_lower:
        return f"Сервер {host} не відповів протягом 12 секунд (Timeout). Перевірте наявність інтернет-з'єднання на сервері або спробуйте інший порт."

    if "connection refused" in err_lower or "111" in err_lower or "10061" in err_lower:
        return f"Сервер {host} відхилив з'єднання. Перевірте правильність порту: 587 (з вимкненим прямим SSL, STARTTLS) або 465 (з увімкненим прямим SSL)."

    if "ssl" in err_lower or "wrong version" in err_lower or "certificate" in err_lower or "handshake" in err_lower:
        return "Невідповідність протоколу шифрування. Для порту 587 вимкніть галочку SSL (буде використано STARTTLS). Для порту 465 обов'язково увімкніть галочку прямого SSL."

    if "getaddrinfo failed" in err_lower or "not known" in err_lower or "name or service not known" in err_lower:
        return f"Не вдалося знайти хост '{host}' через DNS. Перевірте правильність написання адреси сервера (наприклад: smtp.gmail.com або smtp.ukr.net)."

    if "starttls" in err_lower or "не підтримує обов'язковий протокол шифрування" in err_lower:
        return f"Сервер {host} не підтримує або відхилив захищене з'єднання STARTTLS. Перевірте порт (587 для STARTTLS, 465 для прямого SSL) та дійсність SSL/TLS-сертифіката."

    return "Перевірте параметри налаштувань пошти, адресу хоста, порт, логін та наявність доступу до інтернету."


async def send_email_with_failover(
    to_addr: Union[str, List[str]],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    db: Optional[AsyncSession] = None,
    force_provider: Optional[str] = None,  # None | "primary" | "fallback"
    config_override: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    log_to_db: bool = True,
) -> Dict[str, Any]:
    """
    Sends email with automatic failover:
    Tries Primary SMTP (e.g. Gmail App Password).
    If Primary fails or times out, immediately falls back to Fallback SMTP (e.g. Ukr.net).
    Supports on-the-fly config overrides for testing without altering persisted DB values.
    Logs success or failover to NotificationLog if db session is provided.
    """
    smtp_enabled = bool(
        config_override.get("smtp_enabled")
        if config_override and "smtp_enabled" in config_override
        else get_runtime_setting("smtp_enabled", False)
    )
    if not smtp_enabled:
        logger.info(f"[EMAIL] Skipping send to {to_addr}: SMTP is disabled in settings.")
        return {
            "status": "skipped",
            "message": "Надсилання email вимкнено в системних налаштуваннях",
            "hint": "Увімкніть галочку «Увімкнути систему сповіщень на Email» у налаштуваннях."
        }

    p_host = str((config_override and config_override.get("smtp_primary_host")) or get_runtime_setting("smtp_primary_host", "smtp.gmail.com")).strip()
    p_port = int((config_override and config_override.get("smtp_primary_port")) or get_runtime_setting("smtp_primary_port", 587))
    p_user = str((config_override and config_override.get("smtp_primary_user")) if config_override and "smtp_primary_user" in config_override else get_runtime_setting("smtp_primary_user", "")).strip()
    raw_p_pass = (config_override and config_override.get("smtp_primary_password"))
    p_pass = raw_p_pass if raw_p_pass and raw_p_pass != "********" else str(get_runtime_setting("smtp_primary_password", "")).strip()
    p_ssl = bool((config_override and config_override.get("smtp_primary_ssl")) if config_override and "smtp_primary_ssl" in config_override else get_runtime_setting("smtp_primary_ssl", False))
    p_from = str((config_override and config_override.get("smtp_primary_from")) if config_override and "smtp_primary_from" in config_override else get_runtime_setting("smtp_primary_from", "")).strip() or p_user

    fb_enabled = bool((config_override and config_override.get("smtp_fallback_enabled")) if config_override and "smtp_fallback_enabled" in config_override else get_runtime_setting("smtp_fallback_enabled", False))
    fb_host = str((config_override and config_override.get("smtp_fallback_host")) or get_runtime_setting("smtp_fallback_host", "smtp.ukr.net")).strip()
    fb_port = int((config_override and config_override.get("smtp_fallback_port")) or get_runtime_setting("smtp_fallback_port", 465))
    fb_user = str((config_override and config_override.get("smtp_fallback_user")) if config_override and "smtp_fallback_user" in config_override else get_runtime_setting("smtp_fallback_user", "")).strip()
    raw_fb_pass = (config_override and config_override.get("smtp_fallback_password"))
    fb_pass = raw_fb_pass if raw_fb_pass and raw_fb_pass != "********" else str(get_runtime_setting("smtp_fallback_password", "")).strip()
    fb_ssl = bool((config_override and config_override.get("smtp_fallback_ssl")) if config_override and "smtp_fallback_ssl" in config_override else get_runtime_setting("smtp_fallback_ssl", True))
    fb_from = str((config_override and config_override.get("smtp_fallback_from")) if config_override and "smtp_fallback_from" in config_override else get_runtime_setting("smtp_fallback_from", "")).strip() or fb_user

    primary_error: Optional[str] = None
    to_list = [to_addr] if isinstance(to_addr, str) else list(to_addr)

    # Validation guards for forced test modes
    if force_provider == "primary" and (not p_user or not p_pass):
        err = "Основний SMTP не налаштовано: відсутній логін або пароль додатку Google."
        return {
            "status": "error",
            "provider": "primary",
            "host": p_host,
            "port": p_port,
            "recipient": to_addr,
            "error": err,
            "hint": get_smtp_diagnostic_hint("535", host=p_host)
        }

    if force_provider == "fallback" and (not fb_user or not fb_pass):
        err = "Резервний SMTP не налаштовано: відсутній логін або пароль додатку для Ukr.net."
        return {
            "status": "error",
            "provider": "fallback",
            "host": fb_host,
            "port": fb_port,
            "recipient": to_addr,
            "error": err,
            "hint": get_smtp_diagnostic_hint("535", host=fb_host)
        }

    # 1. Attempt Primary SMTP (unless explicitly forced to fallback)
    if force_provider != "fallback":
        try:
            smtp_kwargs: Dict[str, Any] = {
                "host": p_host,
                "port": p_port,
                "user": p_user,
                "password": p_pass,
                "use_ssl": p_ssl,
                "from_addr": p_from,
                "to_addr": to_addr,
                "subject": subject,
                "html_body": html_body,
                "text_body": text_body,
                "attachments": attachments,
                "timeout": 12.0,
            }
            if extra_headers:
                smtp_kwargs["extra_headers"] = extra_headers
            await asyncio.to_thread(send_smtp_message_sync, **smtp_kwargs)
            logger.info(f"[EMAIL] Successfully sent email to {to_addr} via Primary SMTP ({p_host})")
            if db and log_to_db:
                try:
                    db.add(NotificationLog(
                        event_type="EMAIL_SENT",
                        title=subject[:200],
                        body=f"Відправлено на {to_addr} через Primary SMTP ({p_host})",
                        recipients_count=len(to_list),
                        success_count=len(to_list),
                        failure_count=0
                    ))
                    await db.commit()
                except Exception:
                    pass
            return {
                "status": "ok",
                "provider": "primary",
                "host": p_host,
                "port": p_port,
                "recipient": to_addr,
                "message": f"Лист успішно надіслано на {to_addr} через Основний SMTP ({p_host}:{p_port})!"
            }
        except Exception as exc:
            primary_error = str(exc)
            logger.warning(f"[EMAIL] Primary SMTP ({p_host}) failed: {exc}")

    # If force_provider was "primary", don't attempt fallback
    if force_provider == "primary":
        return {
            "status": "error",
            "provider": "primary",
            "host": p_host,
            "port": p_port,
            "recipient": to_addr,
            "error": primary_error or "Unknown error",
            "hint": get_smtp_diagnostic_hint(primary_error or "", host=p_host)
        }

    # 2. Attempt Fallback SMTP if enabled and configured
    if fb_enabled and fb_host and fb_user:
        try:
            logger.info(f"[EMAIL] Triggering automatic failover to Secondary SMTP ({fb_host})...")
            fb_kwargs: Dict[str, Any] = {
                "host": fb_host,
                "port": fb_port,
                "user": fb_user,
                "password": fb_pass,
                "use_ssl": fb_ssl,
                "from_addr": fb_from,
                "to_addr": to_addr,
                "subject": subject,
                "html_body": html_body,
                "text_body": text_body,
                "attachments": attachments,
                "timeout": 12.0,
            }
            if extra_headers:
                fb_kwargs["extra_headers"] = extra_headers
            await asyncio.to_thread(send_smtp_message_sync, **fb_kwargs)
            logger.info(f"[EMAIL] Successfully delivered email via Fallback SMTP ({fb_host})")
            warning_msg = f"Основний SMTP ({p_host}) не відповів ({primary_error}). Лист успішно надіслано через резервний SMTP ({fb_host})."
            if db and log_to_db:
                try:
                    db.add(NotificationLog(
                        event_type="EMAIL_FAILOVER",
                        title=subject[:200],
                        body=warning_msg,
                        recipients_count=len(to_list),
                        success_count=len(to_list),
                        failure_count=0
                    ))
                    await db.commit()
                except Exception:
                    pass
            return {
                "status": "ok",
                "provider": "fallback",
                "host": fb_host,
                "port": fb_port,
                "recipient": to_addr,
                "warning": warning_msg,
                "message": f"Лист успішно надіслано через Резервний SMTP ({fb_host}:{fb_port})!"
            }
        except Exception as fb_exc:
            logger.error(f"[EMAIL] Fallback SMTP ({fb_host}) also failed: {fb_exc}")
            combined_err = f"Основний ({p_host}): {primary_error}; Резервний ({fb_host}): {fb_exc}"
            if db and log_to_db:
                try:
                    db.add(NotificationLog(
                        event_type="EMAIL_FAILED",
                        title=subject[:200],
                        body=combined_err,
                        recipients_count=len(to_list),
                        success_count=0,
                        failure_count=len(to_list)
                    ))
                    await db.commit()
                except Exception:
                    pass
            return {
                "status": "error",
                "provider": "failover",
                "host": f"{p_host} / {fb_host}",
                "recipient": to_addr,
                "error": combined_err,
                "hint": get_smtp_diagnostic_hint(str(fb_exc), host=fb_host)
            }

    # If fallback is not configured
    error_msg = f"Помилка відправки через Primary SMTP ({p_host}): {primary_error}"
    if db and log_to_db:
        try:
            db.add(NotificationLog(
                event_type="EMAIL_FAILED",
                title=subject[:200],
                body=error_msg,
                recipients_count=len(to_list),
                success_count=0,
                failure_count=len(to_list)
            ))
            await db.commit()
        except Exception:
            pass
    return {
        "status": "error",
        "provider": "primary",
        "host": p_host,
        "port": p_port,
        "recipient": to_addr,
        "error": error_msg,
        "hint": get_smtp_diagnostic_hint(primary_error or "", host=p_host)
    }


# ---------------------------------------------------------------------------
# Recipient Resolution & Personalized Dispatch
# ---------------------------------------------------------------------------

RecipientItem = Tuple[str, Optional[int]]


async def resolve_facility_email_recipients(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    include_weekly_recipients: bool = True,
) -> List[RecipientItem]:
    """
    Resolve active opted-in email recipients for operational alerts of a facility:
    - All active superadmins with email & email_notifications_enabled=True
    - All active admins & operators with email & email_notifications_enabled=True
      assigned to this facility (or global admins with facility_id=None)
    - Additional recipients configured in `email_weekly_recipients` (deduplicated)
    """
    from backend.app.models.user import User

    q = (
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.is_active == True,  # noqa: E712
            User.email.isnot(None),
            User.email != "",
        )
    )
    res = await db.execute(q)
    users = res.scalars().all()

    seen_emails = set()
    recipients: List[RecipientItem] = []

    for u in users:
        if not bool(getattr(u, "email_notifications_enabled", True)):
            continue
        clean_email = (u.email or "").strip()
        if "@" not in clean_email:
            continue
        role_names = {r.name.lower() for r in (u.roles or [])}
        is_super = bool(u.is_superadmin) or ("superadmin" in role_names)
        is_admin = is_super or ("admin" in role_names)
        is_operator = "operator" in role_names

        eligible = False
        if is_super:
            eligible = True
        elif is_admin and (facility_id is None or u.facility_id is None or u.facility_id == facility_id):
            eligible = True
        elif is_operator and (facility_id is None or u.facility_id is None or u.facility_id == facility_id):
            eligible = True

        if eligible and clean_email.lower() not in seen_emails:
            seen_emails.add(clean_email.lower())
            recipients.append((clean_email, u.id))

    if include_weekly_recipients:
        raw_rec = str(get_runtime_setting("email_weekly_recipients", "") or "").strip()
        if raw_rec:
            # Check if any explicitly opted-out user shares that email
            opted_out_emails = {
                (u.email or "").strip().lower()
                for u in users
                if not bool(getattr(u, "email_notifications_enabled", True)) and u.email
            }
            for item in raw_rec.replace(";", ",").split(","):
                addr = item.strip()
                if "@" in addr and addr.lower() not in seen_emails and addr.lower() not in opted_out_emails:
                    seen_emails.add(addr.lower())
                    recipients.append((addr, None))

    return recipients


async def _send_personalized_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    subject: str,
    template_title: str,
    content_html: str,
    action_button_html: str = "",
    subtitle: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    db: Optional[AsyncSession] = None,
    allow_unsubscribe: bool = True,
) -> Dict[str, Any]:
    """
    Sends email with individualized 1-click unsubscribe links and RFC 8058 headers
    to each recipient without duplicating clutter in logs.
    """
    if not get_runtime_setting("smtp_enabled", False):
        return {"status": "skipped", "message": "SMTP вимкнено"}

    norm: List[RecipientItem] = []
    if isinstance(recipients, str):
        for r in recipients.replace(";", ",").split(","):
            clean = r.strip()
            if "@" in clean:
                norm.append((clean, None))
    else:
        for item in recipients:
            if isinstance(item, tuple):
                addr, uid = item
                if addr and "@" in addr.strip():
                    norm.append((addr.strip(), uid))
            elif isinstance(item, str) and "@" in item.strip():
                norm.append((item.strip(), None))

    if not norm:
        return {"status": "skipped", "message": "Немає отримувачів із заповненим email"}

    sent_results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for idx, (addr, uid) in enumerate(norm):
        unsub_url = build_unsubscribe_url(addr, user_id=uid) if allow_unsubscribe else None
        headers = (
            {
                "List-Unsubscribe": f"<{unsub_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
            if unsub_url
            else None
        )
        html_body = _wrap_html_template(
            title=template_title,
            content_html=content_html,
            action_button_html=action_button_html,
            subtitle=subtitle,
            unsubscribe_url=unsub_url,
        )
        res = await send_email_with_failover(
            to_addr=addr,
            subject=subject,
            html_body=html_body,
            attachments=attachments,
            db=db,
            extra_headers=headers,
            log_to_db=(idx == 0),
        )
        sent_results.append(res)
        if res.get("status") == "error":
            errors.append(f"{addr}: {res.get('error')}")

    ok_res = next((r for r in sent_results if r.get("status") == "ok"), None)
    if ok_res:
        return {**ok_res, "recipients_count": len(norm), "errors": errors}
    return sent_results[-1]


def _dashboard_action_button(tab: str = "tab-dashboard", label: str = "Відкрити SD-GEN016") -> str:
    url = f"{get_public_base_url()}/?tab={urllib.parse.quote(tab)}"
    return (
        '<div class="btn-container">'
        f'<a href="{html.escape(url, quote=True)}" class="btn">{html.escape(label)}</a>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# High-Level Email Notification Helpers
# ---------------------------------------------------------------------------

async def send_password_reset_email(
    to_addr: str,
    user_name: str,
    reset_token: str,
    base_url: str = "http://localhost:8000",
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Sends a one-time password reset link with a 20-minute validity."""
    clean_base = base_url.rstrip("/")
    reset_url = f"{clean_base}/?reset_token={reset_token}"
    subject = f"Відновлення пароля — {PRODUCT_BRAND_NAME}"

    content = f"""
    <p>Вітаємо, <strong>{html.escape(user_name)}</strong>!</p>
    <p>Отримано запит на відновлення пароля для вашого облікового запису в системі моніторингу генераторів.</p>
    <p>Для встановлення нового пароля натисніть кнопку нижче або використайте одноразовий код:</p>
    <div style="text-align: center; margin: 16px 0;">
      <span class="token-code">{html.escape(reset_token)}</span>
    </div>
    <div class="info-box">
      <strong>⏱ Увага:</strong> Це посилання дійсне протягом <strong>20 хвилин</strong>.
      Якщо ви не надсилали запит на відновлення пароля, просто проігноруйте цей лист — ваш поточний пароль залишиться незмінним.
    </div>
    """

    button = f"""
    <div class="btn-container">
      <a href="{html.escape(reset_url, quote=True)}" class="btn">Встановити новий пароль</a>
    </div>
    """

    html_body = _wrap_html_template("Відновлення пароля", content, button)
    return await send_email_with_failover(
        to_addr=to_addr,
        subject=subject,
        html_body=html_body,
        db=db
    )


async def send_password_changed_email(
    to_addr: str,
    user_name: str,
    ip_address: Optional[str] = None,
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Sends a security alert email after password change."""
    subject = f"Безпека: Пароль змінено — {PRODUCT_SENDER_NAME}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <p>Вітаємо, <strong>{html.escape(user_name)}</strong>!</p>
    <div class="success-box">
      <strong>✅ Пароль оновлено:</strong> Пароль до вашого облікового запису було успішно змінено <strong>{now_str}</strong>.
    </div>
    <p>Деталі операції:</p>
    <ul>
      <li><strong>IP-адреса:</strong> {html.escape(ip_address or "Не визначено")}</li>
      <li><strong>Час:</strong> {now_str}</li>
    </ul>
    <div class="alert-box">
      <strong>🚨 Важливо:</strong> Якщо ви НЕ змінювали свій пароль, негайно зверніться до головного системного адміністратора для блокування несанкціонованого доступу.
    </div>
    """

    html_body = _wrap_html_template("Пароль змінено", content)
    return await send_email_with_failover(
        to_addr=to_addr,
        subject=subject,
        html_body=html_body,
        db=db
    )


async def send_safety_stop_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    reason: str,
    elapsed_hours: float,
    fuel_level: float,
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Sends an urgent email notification when an operational safety fuse triggers."""
    subject = f"🛑 Аварійна зупинка генератора — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="alert-box">
      <strong>🚨 Спрацював автоматичний запобіжник безпеки!</strong><br>
      Генератор <strong>{html.escape(generator_name)}</strong> було автоматично вимкнено для збереження обладнання.
    </div>
    <p><strong>Причина зупинки:</strong> {html.escape(reason)}</p>
    <div class="info-box">
      <ul style="margin: 0; padding-left: 20px;">
        <li><strong>Час спрацювання:</strong> {now_str}</li>
        <li><strong>Тривалість поточної сесії:</strong> {elapsed_hours:.2f} год</li>
        <li><strong>Залишок палива в баку:</strong> {fuel_level:.1f} л</li>
      </ul>
    </div>
    <p>Будь ласка, перевірте фізичний стан генератора та за потреби виконайте дозаправку або планове ТО.</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Аварійна зупинка генератора",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-dashboard", "Перевірити стан генератора"),
        db=db,
    )


async def send_schedule_auto_stop_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    schedule_msg: str,
    elapsed_hours: float,
    fuel_level: float,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends notification email when generator is automatically stopped at end of shift schedule."""
    subject = f"⏱️ Автостоп за графіком — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="warning-box">
      <strong>🕒 Завершення робочого графіка:</strong><br>
      Генератор <strong>{html.escape(generator_name)}</strong> було автоматично зупинено по завершенню зміни.
    </div>
    <p><strong>Деталі розкладу:</strong> {html.escape(schedule_msg)}</p>
    <div class="info-box">
      <ul style="margin: 0; padding-left: 20px;">
        <li><strong>Час зупинки:</strong> {now_str}</li>
        <li><strong>Відпрацьовано за сеанс:</strong> {elapsed_hours:.2f} год</li>
        <li><strong>Залишок палива в баку:</strong> {fuel_level:.1f} л</li>
      </ul>
    </div>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Автоматична зупинка за графіком",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-runs", "Журнал циклів"),
        db=db,
    )


async def send_outside_work_hours_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    schedule_msg: str,
    context_text: str,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends email alert when generator is running or attempted to run outside work hours."""
    subject = f"🕒 Робота поза робочим часом — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="warning-box">
      <strong>🕒 Порушення робочого графіка генератора!</strong><br>
      Зафіксовано активність генератора <strong>{html.escape(generator_name)}</strong> поза межами встановленого часу роботи.
    </div>
    <p><strong>Подія:</strong> {html.escape(context_text)}</p>
    <div class="info-box">
      <ul style="margin: 0; padding-left: 20px;">
        <li><strong>Час фіксації:</strong> {now_str}</li>
        <li><strong>Статус графіка:</strong> {html.escape(schedule_msg)}</li>
      </ul>
    </div>
    <p>Перевірте необхідність роботи обладнання у позаробочий час або налаштування автостопу.</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Робота поза робочим часом",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-dashboard", "Перевірити генератор"),
        db=db,
    )


async def send_empty_tank_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    fuel_level_l: float,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends urgent email when generator fuel tank reaches 0 L (empty tank)."""
    subject = f"⛽ ПОРОЖНІЙ БАК (0 л) — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="alert-box">
      <strong>⛽ Критично: паливо в баку закінчилося!</strong><br>
      У баку генератора <strong>{html.escape(generator_name)}</strong> зафіксовано нульовий залишок палива (<strong>{max(0.0, fuel_level_l):.1f} л</strong>).
    </div>
    <div class="info-box">
      <ul style="margin: 0; padding-left: 20px;">
        <li><strong>Час фіксації:</strong> {now_str}</li>
        <li><strong>Поточний рівень:</strong> {max(0.0, fuel_level_l):.1f} л</li>
      </ul>
    </div>
    <p>Робота генератора насухо може призвести до пошкодження паливної системи. Необхідна негайна дозаправка!</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Порожній бак генератора",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-fuel", "Перейти до обліку палива"),
        db=db,
    )


async def send_low_fuel_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    fuel_level_l: float,
    threshold_l: float,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends warning email when tank fuel drops below threshold."""
    subject = f"⚠️ Критичний рівень палива — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="warning-box">
      <strong>⚠️ Низький рівень палива в баку!</strong><br>
      Залишок палива генератора <strong>{html.escape(generator_name)}</strong> впав нижче встановленого порогу.
    </div>
    <div class="info-box">
      <ul style="margin: 0; padding-left: 20px;">
        <li><strong>Час фіксації:</strong> {now_str}</li>
        <li><strong>Поточний рівень:</strong> {max(0.0, fuel_level_l):.1f} л</li>
        <li><strong>Поріг попередження:</strong> {threshold_l:.1f} л</li>
      </ul>
    </div>
    <p>Будь ласка, заплануйте дозаправку зі складу або каністр.</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Низький рівень палива",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-fuel", "Відкрити паливо"),
        db=db,
    )


async def send_fuel_discrepancy_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    shortage_l: float,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends warning email when calculated fuel consumption exceeds recorded tank level."""
    subject = f"⚠️ Розбіжність паливного балансу — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="warning-box">
      <strong>⚠️ Виявлено розбіжність паливного балансу!</strong><br>
      Для генератора <strong>{html.escape(generator_name)}</strong> розрахункова витрата палива перевищила обліковий залишок у баку на <strong>{shortage_l:.1f} л</strong>.
    </div>
    <p>Час фіксації: <strong>{now_str}</strong>. Перевірте невнесені дозаправки або фактичний рівень палива в баку.</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Розбіжність паливного балансу",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-fuel", "Перевірити паливо"),
        db=db,
    )


async def send_critical_fault_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    fault_title: str,
    fault_description: str,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends urgent email notification on CRITICAL fault report."""
    subject = f"🚨 Критична несправність — {generator_name}"
    now_str = datetime.datetime.now().strftime("%d.%m.%Y о %H:%M")

    content = f"""
    <div class="alert-box">
      <strong>🚨 Зареєстровано критичну несправність!</strong><br>
      Генератор <strong>{html.escape(generator_name)}</strong> переведено в аварійний статус.
    </div>
    <div class="info-box">
      <p style="margin: 0 0 6px 0;"><strong>Заголовок:</strong> {html.escape(fault_title)}</p>
      <p style="margin: 0 0 6px 0;"><strong>Опис:</strong> {html.escape(fault_description)}</p>
      <p style="margin: 0;"><strong>Час реєстрації:</strong> {now_str}</p>
    </div>
    <p>Необхідна термінова діагностика та усунення несправності перед подальшим запуском.</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Критична несправність генератора",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-faults", "Відкрити журнал несправностей"),
        db=db,
    )


async def send_maintenance_due_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    generator_name: str,
    is_overdue: bool,
    hours_delta: float,
    effective_hours: float,
    next_due_hours: float,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """Sends email reminder when generator maintenance is approaching or overdue."""
    if is_overdue:
        subject = f"🔧 УВАГА: Прострочено ТО — {generator_name}"
        box_cls = "alert-box"
        lead = f"Регламентне ТО прострочено на <strong>{hours_delta:.1f} мотогодин</strong>!"
    else:
        subject = f"🔧 Наближається планове ТО — {generator_name}"
        box_cls = "warning-box"
        lead = f"До планового ТО залишилося <strong>{hours_delta:.1f} мотогодин</strong>."

    content = f"""
    <div class="{box_cls}">
      <strong>🔧 Регламент технічного обслуговування — {html.escape(generator_name)}</strong><br>
      {lead}
    </div>
    <div class="info-box">
      <ul style="margin: 0; padding-left: 20px;">
        <li><strong>Поточне напрацювання:</strong> {effective_hours:.1f} год</li>
        <li><strong>План наступного ТО:</strong> {next_due_hours:.1f} год</li>
      </ul>
    </div>
    <p>Підготуйте витратні матеріали (мастило, фільтри) та внесіть запис про проведення ТО після виконання робіт.</p>
    """

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title="Планове технічне обслуговування",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-maintenance", "Журнал ТО"),
        db=db,
    )


async def send_weekly_digest_email(
    recipients: Union[str, List[str], List[RecipientItem]],
    excel_bytes: bytes,
    period_label: str,
    summary_text: str = "",
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Sends weekly generator operation digest with attached 5-sheet Excel workbook."""
    subject = f"📊 Щотижневий звіт роботи генераторів — {period_label}"

    content = f"""
    <p>Доброго дня!</p>
    <p>Надсилаємо щотижневий зведений звіт експлуатації генераторів та обліку палива за період <strong>{html.escape(period_label)}</strong>.</p>
    <div class="info-box">
      <strong>📎 До листа додано файл звіту:</strong><br>
      Повна книга Excel (5 листів): зведення, сесії запусків, журнал ТО, рух палива та системні коригування.
    </div>
    {f'<p>{html.escape(summary_text)}</p>' if summary_text else ''}
    """

    attachments = [{
        "filename": f"Звіт_генератори_{period_label.replace(' ', '_')}.xlsx",
        "content": excel_bytes,
        "maintype": "application",
        "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }]

    return await _send_personalized_email(
        recipients=recipients,
        subject=subject,
        template_title=f"Щотижневий звіт ({period_label})",
        content_html=content,
        action_button_html=_dashboard_action_button("tab-reports", "Відкрити звіти"),
        attachments=attachments,
        db=db,
    )
