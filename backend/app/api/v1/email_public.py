import html
from typing import Optional
from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.api.deps import get_client_ip
from backend.app.models.user import User
from backend.app.services.audit_service import log_audit
from backend.app.services.email_service import (
    PRODUCT_BRAND_NAME,
    generate_unsubscribe_token,
    verify_unsubscribe_token,
)
from backend.app.services.settings_service import get_runtime_setting, update_system_settings

router = APIRouter(prefix="/email", tags=["Email Розсилка"])


def _render_subscription_page(
    title: str,
    badge_text: str,
    badge_color: str,
    heading: str,
    message_html: str,
    extra_form_html: str = "",
) -> str:
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)} — {html.escape(PRODUCT_BRAND_NAME)}</title>
  <style>
    body {{
      margin: 0;
      padding: 24px 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
    }}
    .card {{
      width: 100%;
      max-width: 480px;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 16px;
      padding: 28px 24px;
      box-shadow: 0 20px 45px rgba(0, 0, 0, 0.35);
      text-align: center;
      box-sizing: border-box;
    }}
    .logo {{
      width: 64px;
      height: 64px;
      border-radius: 50%;
      border: 2px solid rgba(56, 189, 248, 0.45);
      margin-bottom: 12px;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 12px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 12px;
      background: {badge_color};
      color: #ffffff;
    }}
    h1 {{
      margin: 0 0 10px 0;
      font-size: 20px;
      line-height: 1.3;
    }}
    p {{
      margin: 0 0 16px 0;
      font-size: 14px;
      line-height: 1.55;
      color: #cbd5e1;
    }}
    .actions {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 20px;
    }}
    .btn {{
      display: inline-block;
      width: 100%;
      padding: 11px 18px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;
      border: none;
      cursor: pointer;
      box-sizing: border-box;
    }}
    .btn-primary {{
      background: #2563eb;
      color: #ffffff;
    }}
    .btn-secondary {{
      background: transparent;
      border: 1px solid #475569;
      color: #cbd5e1;
    }}
    .meta {{
      margin-top: 18px;
      font-size: 11px;
      color: #64748b;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/frontend/icons/email-logo.png" alt="SD-GEN016" class="logo" width="64" height="64">
    <div><span class="badge">{html.escape(badge_text)}</span></div>
    <h1>{html.escape(heading)}</h1>
    <p>{message_html}</p>
    <div class="actions">
      {extra_form_html}
      <a href="/" class="btn btn-secondary">Перейти до панелі SD-GEN016</a>
    </div>
    <div class="meta">{html.escape(PRODUCT_BRAND_NAME)}</div>
  </div>
</body>
</html>"""


async def _set_email_subscription_state(
    db: AsyncSession,
    email_addr: str,
    user_id: Optional[int],
    enabled: bool,
    request: Request,
) -> Optional[User]:
    clean_email = (email_addr or "").strip().lower()
    target_user: Optional[User] = None

    if user_id:
        target_user = await db.get(User, user_id)
        if target_user and target_user.email and target_user.email.strip().lower() != clean_email:
            target_user = None

    if target_user is None and clean_email:
        res = await db.execute(
            select(User).where(func.lower(User.email) == clean_email)
        )
        target_user = res.scalars().first()

    if target_user:
        target_user.email_notifications_enabled = enabled
    elif not enabled and clean_email:
        # Remove standalone external email from weekly recipients if unsubscribed
        raw_rec = str(get_runtime_setting("email_weekly_recipients", "") or "").strip()
        if raw_rec:
            items = [x.strip() for x in raw_rec.replace(";", ",").split(",") if x.strip()]
            filtered = [x for x in items if x.lower() != clean_email]
            if len(filtered) != len(items):
                await update_system_settings(db, {"email_weekly_recipients": ", ".join(filtered)})

    await log_audit(
        db=db,
        action="EMAIL_RESUBSCRIBED" if enabled else "EMAIL_UNSUBSCRIBED",
        entity_type="User",
        entity_id=str(target_user.id) if target_user else clean_email[:64],
        user_id=target_user.id if target_user else None,
        details={"email": clean_email, "enabled": enabled},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return target_user


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_via_link(
    request: Request,
    token: str = Query(..., min_length=8, max_length=512),
    db: AsyncSession = Depends(get_db),
):
    parsed = verify_unsubscribe_token(token, expected_action="unsub")
    if not parsed:
        return HTMLResponse(
            content=_render_subscription_page(
                title="Недійсне посилання",
                badge_text="Помилка посилання",
                badge_color="#dc2626",
                heading="Посилання для відписки недійсне",
                message_html="Посилання пошкоджене або має невірний цифровий підпис. Ви можете змінити налаштування розсилки у профілі користувача в системі.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await _set_email_subscription_state(
        db=db,
        email_addr=parsed["email"],
        user_id=parsed.get("user_id"),
        enabled=False,
        request=request,
    )

    resub_token = generate_unsubscribe_token(
        email_addr=parsed["email"],
        user_id=parsed.get("user_id"),
        action="resub",
    )
    resub_form = (
        '<form method="POST" action="/api/v1/email/resubscribe">'
        f'<input type="hidden" name="token" value="{html.escape(resub_token, quote=True)}">'
        '<button type="submit" class="btn btn-primary">Повернути підписку на розсилку</button>'
        "</form>"
    )
    return HTMLResponse(
        content=_render_subscription_page(
            title="Відписка від розсилки",
            badge_text="Виконано",
            badge_color="#475569",
            heading="Ви відписалися від email-розсилки",
            message_html=(
                f"Адресу <strong>{html.escape(parsed['email'])}</strong> виключено з автоматичних "
                "оперативних і щотижневих email-сповіщень.<br>Критичні листи безпеки (скидання пароля) продовжать працювати за вашим запитом."
            ),
            extra_form_html=resub_form,
        ),
        status_code=status.HTTP_200_OK,
    )


@router.post("/unsubscribe")
async def unsubscribe_one_click(
    request: Request,
    token: Optional[str] = Query(default=None),
    token_form: Optional[str] = Form(default=None, alias="token"),
    db: AsyncSession = Depends(get_db),
):
    """Supports RFC 8058 One-Click Unsubscribe POST requests from Gmail / Apple Mail."""
    effective_token = token or token_form or ""
    parsed = verify_unsubscribe_token(effective_token, expected_action="unsub")
    if not parsed:
        return JSONResponse({"detail": "Недійсний токен відписки"}, status_code=status.HTTP_400_BAD_REQUEST)

    await _set_email_subscription_state(
        db=db,
        email_addr=parsed["email"],
        user_id=parsed.get("user_id"),
        enabled=False,
        request=request,
    )
    return {"status": "unsubscribed", "email": parsed["email"]}


@router.post("/resubscribe", response_class=HTMLResponse)
async def resubscribe_via_form(
    request: Request,
    token: str = Form(..., min_length=8, max_length=512),
    db: AsyncSession = Depends(get_db),
):
    parsed = verify_unsubscribe_token(token, expected_action="resub")
    if not parsed:
        return HTMLResponse(
            content=_render_subscription_page(
                title="Помилка відновлення",
                badge_text="Помилка",
                badge_color="#dc2626",
                heading="Не вдалося відновити підписку",
                message_html="Токен недійсний. Ви можете увімкнути email-сповіщення у профілі облікового запису після входу в систему.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await _set_email_subscription_state(
        db=db,
        email_addr=parsed["email"],
        user_id=parsed.get("user_id"),
        enabled=True,
        request=request,
    )
    return HTMLResponse(
        content=_render_subscription_page(
            title="Підписку відновлено",
            badge_text="Активно",
            badge_color="#16a34a",
            heading="Email-сповіщення знову увімкнено!",
            message_html=f"Адреса <strong>{html.escape(parsed['email'])}</strong> знову отримуватиме системні сповіщення та звіти.",
        ),
        status_code=status.HTTP_200_OK,
    )
