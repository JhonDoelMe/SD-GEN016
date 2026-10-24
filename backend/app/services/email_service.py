import asyncio
import datetime
import email.utils
import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.settings_service import get_runtime_setting
from backend.app.models.notification import NotificationLog

logger = logging.getLogger("email_service")


def _wrap_html_template(title: str, content_html: str, action_button_html: str = "") -> str:
    """Wraps body content in a modern, responsive email template."""
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
      <h1>⚡ Service Desk Бензинового Генератора</h1>
      <p>MAXI-UA LLC • Автоматизована система моніторингу</p>
    </div>
    <div class="email-body">
      {content_html}
      {action_button_html}
    </div>
    <div class="email-footer">
      <p>Це автоматичне системне сповіщення. Будь ласка, не відповідайте на цей лист.</p>
      <p>© {datetime.datetime.now().year} MAXI-UA LLC. Всі права захищено.</p>
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
    timeout: float = 12.0
) -> None:
    """
    Synchronous SMTP delivery supporting STARTTLS (e.g. Gmail 587) and SSL (e.g. Ukr.net 465).
    Raises smtplib or socket exceptions on failure.
    """
    if not host:
        raise ValueError("SMTP host is not specified")

    to_list = [to_addr] if isinstance(to_addr, str) else list(to_addr)
    to_str = ", ".join(to_list)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr or user
    msg["To"] = to_str
    msg["Date"] = email.utils.formatdate(localtime=True)

    plain_content = text_body or _strip_html(html_body)
    msg.set_content(plain_content)
    msg.add_alternative(html_body, subtype="html")

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
            try:
                ssl_ctx = ssl.create_default_context()
                server.starttls(context=ssl_ctx)
                server.ehlo()
            except Exception as tls_err:
                logger.debug(f"STARTTLS negotiation note: {tls_err}")
            if user and password:
                server.login(user, password)
            server.send_message(msg)


async def send_email_with_failover(
    to_addr: Union[str, List[str]],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    db: Optional[AsyncSession] = None,
    force_provider: Optional[str] = None  # None | "primary" | "fallback"
) -> Dict[str, Any]:
    """
    Sends email with automatic failover:
    Tries Primary SMTP (e.g. Gmail App Password).
    If Primary fails or times out, immediately falls back to Fallback SMTP (e.g. Ukr.net).
    Logs success or failover to NotificationLog if db session is provided.
    """
    smtp_enabled = bool(get_runtime_setting("smtp_enabled", False))
    if not smtp_enabled:
        logger.info(f"[EMAIL] Skipping send to {to_addr}: SMTP is disabled in settings.")
        return {"status": "skipped", "message": "Надсилання email вимкнено в системних налаштуваннях"}

    p_host = str(get_runtime_setting("smtp_primary_host", "smtp.gmail.com")).strip()
    p_port = int(get_runtime_setting("smtp_primary_port", 587))
    p_user = str(get_runtime_setting("smtp_primary_user", "")).strip()
    p_pass = str(get_runtime_setting("smtp_primary_password", "")).strip()
    p_ssl = bool(get_runtime_setting("smtp_primary_ssl", False))
    p_from = str(get_runtime_setting("smtp_primary_from", "")).strip() or p_user

    fb_enabled = bool(get_runtime_setting("smtp_fallback_enabled", False))
    fb_host = str(get_runtime_setting("smtp_fallback_host", "smtp.ukr.net")).strip()
    fb_port = int(get_runtime_setting("smtp_fallback_port", 465))
    fb_user = str(get_runtime_setting("smtp_fallback_user", "")).strip()
    fb_pass = str(get_runtime_setting("smtp_fallback_password", "")).strip()
    fb_ssl = bool(get_runtime_setting("smtp_fallback_ssl", True))
    fb_from = str(get_runtime_setting("smtp_fallback_from", "")).strip() or fb_user

    primary_error: Optional[str] = None
    to_list = [to_addr] if isinstance(to_addr, str) else list(to_addr)

    # 1. Attempt Primary SMTP (unless explicitly forced to fallback)
    if force_provider != "fallback":
        try:
            await asyncio.to_thread(
                send_smtp_message_sync,
                host=p_host,
                port=p_port,
                user=p_user,
                password=p_pass,
                use_ssl=p_ssl,
                from_addr=p_from,
                to_addr=to_addr,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                attachments=attachments,
                timeout=12.0
            )
            logger.info(f"[EMAIL] Successfully sent email to {to_addr} via Primary SMTP ({p_host})")
            if db:
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
            return {"status": "ok", "provider": "primary", "host": p_host}
        except Exception as exc:
            primary_error = str(exc)
            logger.warning(f"[EMAIL] Primary SMTP ({p_host}) failed: {exc}")

    # If force_provider was "primary", don't attempt fallback
    if force_provider == "primary":
        return {"status": "error", "provider": "primary", "error": primary_error or "Unknown error"}

    # 2. Attempt Fallback SMTP if enabled and configured
    if fb_enabled and fb_host and fb_user:
        try:
            logger.info(f"[EMAIL] Triggering automatic failover to Secondary SMTP ({fb_host})...")
            await asyncio.to_thread(
                send_smtp_message_sync,
                host=fb_host,
                port=fb_port,
                user=fb_user,
                password=fb_pass,
                use_ssl=fb_ssl,
                from_addr=fb_from,
                to_addr=to_addr,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                attachments=attachments,
                timeout=12.0
            )
            logger.info(f"[EMAIL] Successfully delivered email via Fallback SMTP ({fb_host})")
            warning_msg = f"Основний SMTP ({p_host}) не відповів ({primary_error}). Лист успішно надіслано через резервний SMTP ({fb_host})."
            if db:
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
                "warning": warning_msg
            }
        except Exception as fb_exc:
            logger.error(f"[EMAIL] Fallback SMTP ({fb_host}) also failed: {fb_exc}")
            combined_err = f"Основний ({p_host}): {primary_error}; Резервний ({fb_host}): {fb_exc}"
            if db:
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
            return {"status": "error", "error": combined_err}

    # If fallback is not configured
    error_msg = f"Помилка відправки через Primary SMTP ({p_host}): {primary_error}"
    if db:
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
    return {"status": "error", "error": error_msg}


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
    subject = "Відновлення пароля — Service Desk Бензинового Генератора"

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
      <a href="{reset_url}" class="btn">Встановити новий пароль</a>
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
    subject = "Безпека: Пароль до вашого облікового запису успішно змінено"
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
    recipients: Union[str, List[str]],
    generator_name: str,
    reason: str,
    elapsed_hours: float,
    fuel_level: float,
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Sends an urgent email notification when an operational safety fuse triggers."""
    subject = f"🚨 Аварійна зупинка генератора — {generator_name}"
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

    html_body = _wrap_html_template("Аварійна зупинка генератора", content)
    return await send_email_with_failover(
        to_addr=recipients,
        subject=subject,
        html_body=html_body,
        db=db
    )


async def send_weekly_digest_email(
    recipients: Union[str, List[str]],
    excel_bytes: bytes,
    period_label: str,
    summary_text: str = "",
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Sends weekly generator operation digest with attached 5-sheet Excel workbook."""
    subject = f"📊 Щотижневий звіт роботи генераторів — {period_label}"

    content = f"""
    <p>Доброго дня!</p>
    <p>Надсилаємо щотижневий зведений звіт експлуатації бензинових генераторів та обліку палива за період <strong>{html.escape(period_label)}</strong>.</p>
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

    html_body = _wrap_html_template(f"Звіт {period_label}", content)
    return await send_email_with_failover(
        to_addr=recipients,
        subject=subject,
        html_body=html_body,
        attachments=attachments,
        db=db
    )
