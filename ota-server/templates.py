"""HTML templates for the standalone OTA landing page and admin dashboard."""

from __future__ import annotations

import html
import io
from typing import Any

try:
    import segno
except ImportError:  # pragma: no cover - installed in production container
    segno = None


def _build_qr_svg(url: str) -> str:
    if segno is None:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
            'width="112" height="112"><rect width="100" height="100" fill="#fff"/>'
            '<text x="50" y="54" text-anchor="middle" font-size="12" fill="#0f172a">QR</text></svg>'
        )
    qr = segno.make(url, error="M")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=4, border=2, xmldecl=False, dark="#0f172a", light="#ffffff")
    return buf.getvalue().decode("utf-8")


def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 МБ"
    return f"{num_bytes / (1024 * 1024):.2f} МБ"


def render_landing_page(manifest: dict[str, Any]) -> str:
    """Render the public, shareable APK download landing page."""
    app_name = html.escape(str(manifest.get("app_name") or "SD-GEN016"))
    app_id = html.escape(str(manifest.get("app_id") or "ua.pp.sdgen.app"))
    landing_url = str(manifest.get("landing_url") or "https://sdgen.pp.ua/ota/")
    download_url = html.escape(str(manifest.get("download_url") or "/ota/download/latest.apk"))
    has_release = bool(manifest.get("has_release"))
    version_name = html.escape(str(manifest.get("version_name") or "—"))
    version_code = int(manifest.get("version_code") or 0)
    size_str = _format_size(int(manifest.get("file_size") or 0))
    sha256 = html.escape(str(manifest.get("sha256") or "—"))
    published_raw = str(manifest.get("published_at") or "")
    published_display = html.escape(published_raw[:19].replace("T", " ") + " UTC" if published_raw else "—")
    changelog_raw = str(manifest.get("changelog") or "").strip()
    changelog_html = (
        html.escape(changelog_raw).replace("\n", "<br>")
        if changelog_raw
        else "Стабільна релізна збірка для Android."
    )
    qr_svg = _build_qr_svg(landing_url)

    action_block = (
        f"""
        <a class="btn-primary" href="{download_url}">
          Завантажити APK (v{version_name})
        </a>
        <div class="meta-grid">
          <div class="meta-item"><span>Версія</span><strong>v{version_name} (build {version_code})</strong></div>
          <div class="meta-item"><span>Розмір</span><strong>{size_str}</strong></div>
          <div class="meta-item"><span>Опубліковано</span><strong>{published_display}</strong></div>
          <div class="meta-item"><span>Пакет</span><strong>{app_id}</strong></div>
        </div>
        <div class="changelog">
          <div class="section-label">Що нового</div>
          <p>{changelog_html}</p>
        </div>
        <div class="hash-box">
          <span>SHA-256:</span>
          <code>{sha256}</code>
        </div>
        """
        if has_release
        else """
        <div class="empty-box">
          Релізи APK ще не опубліковані на сервері. Завантажте першу збірку через панель адміністратора або скрипт релізу.
        </div>
        """
    )

    escaped_landing = html.escape(landing_url)
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Cache-Control" content="no-store">
  <title>{app_name} — Встановлення та оновлення Android APK</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b1120;
      --card: #111827;
      --border: #1f2937;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --surface: #0f172a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: radial-gradient(circle at top, #172554 0%, var(--bg) 55%);
      color: var(--text);
      display: flex;
      justify-content: center;
      padding: 24px 16px 40px;
    }}
    .card {{
      width: 100%;
      max-width: 540px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 28px 24px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(59, 130, 246, 0.18);
      color: #93c5fd;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 12px 0 6px; font-size: 26px; }}
    .subtitle {{ margin: 0 0 22px; color: var(--muted); font-size: 14px; line-height: 1.5; }}
    .btn-primary {{
      display: block;
      width: 100%;
      text-align: center;
      text-decoration: none;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      font-size: 16px;
      padding: 15px 18px;
      border-radius: 12px;
      transition: background 0.15s ease;
    }}
    .btn-primary:hover {{ background: var(--accent-hover); }}
    .meta-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 18px;
    }}
    .meta-item {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
    }}
    .meta-item span {{ display: block; font-size: 11px; color: var(--muted); margin-bottom: 3px; }}
    .meta-item strong {{ font-size: 13px; word-break: break-word; }}
    .changelog, .steps, .qr-wrap {{
      margin-top: 18px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
    }}
    .section-label {{ font-size: 12px; font-weight: 700; color: #93c5fd; text-transform: uppercase; margin-bottom: 8px; }}
    .changelog p {{ margin: 0; font-size: 14px; line-height: 1.55; color: #e2e8f0; }}
    .hash-box {{
      margin-top: 14px;
      font-size: 11px;
      color: var(--muted);
      word-break: break-all;
      background: #090d16;
      padding: 8px 10px;
      border-radius: 8px;
    }}
    .hash-box code {{ color: #cbd5e1; font-family: ui-monospace, monospace; }}
    .qr-wrap {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .qr-box {{
      background: #fff;
      padding: 6px;
      border-radius: 10px;
      flex-shrink: 0;
      line-height: 0;
    }}
    .qr-box svg {{ width: 112px; height: 112px; }}
    .share-row {{ display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }}
    .btn-ghost {{
      border: 1px solid var(--border);
      background: #1e293b;
      color: var(--text);
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 13px;
      cursor: pointer;
      text-decoration: none;
    }}
    .steps ol {{ margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.65; color: #cbd5e1; }}
    .empty-box {{
      padding: 18px;
      border-radius: 12px;
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.35);
      color: #fde68a;
      font-size: 14px;
      line-height: 1.5;
    }}
    .footer {{
      margin-top: 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      color: var(--muted);
    }}
    .footer a {{ color: #93c5fd; text-decoration: none; }}
    @media (max-width: 480px) {{
      .meta-grid {{ grid-template-columns: 1fr; }}
      .qr-wrap {{ flex-direction: column; text-align: center; }}
    }}
  </style>
</head>
<body>
  <main class="card">
    <span class="badge">OTA Service • Android</span>
    <h1>{app_name}</h1>
    <p class="subtitle">Офіційна сторінка встановлення та оновлення мобільного додатка. Посилання завжди веде на найсвіжіший підписаний реліз.</p>
    {action_block}
    <div class="qr-wrap">
      <div class="qr-box">{qr_svg}</div>
      <div>
        <div class="section-label">Переслати колезі</div>
        <div style="font-size: 13px; color: #cbd5e1; word-break: break-all;">{escaped_landing}</div>
        <div class="share-row">
          <button class="btn-ghost" type="button" onclick="copyShareLink()">Скопіювати посилання</button>
        </div>
      </div>
    </div>
    <div class="steps">
      <div class="section-label">Як встановити на Android</div>
      <ol>
        <li>Натисніть <strong>Завантажити APK</strong> і відкрийте завантажений файл.</li>
        <li>Якщо Android запитає дозвіл на встановлення з цього джерела — увімкніть його у налаштуваннях.</li>
        <li>Надалі додаток сам повідомлятиме про нові версії та оновлюватиметься штатно без втрати даних.</li>
      </ol>
    </div>
    <div class="footer">
      <span>Релізний підпис SHA-256 перевірено</span>
      <a href="/ota/admin">Керування релізами</a>
    </div>
  </main>
  <script>
    function copyShareLink() {{
      const url = {landing_url!r};
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(url).then(() => alert('Посилання скопійовано: ' + url));
      }} else {{
        prompt('Скопіюйте посилання:', url);
      }}
    }}
  </script>
</body>
</html>"""


def render_admin_page(public_base_url: str) -> str:
    """Render lightweight OTA admin dashboard protected via X-OTA-Admin-Token."""
    base_escaped = html.escape(public_base_url.rstrip("/"))
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Cache-Control" content="no-store">
  <title>SD-GEN016 OTA — Адмін-панель</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b1120;
      --card: #111827;
      --border: #1f2937;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #3b82f6;
      --danger: #ef4444;
      --ok: #10b981;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 24px 16px 60px;
    }}
    .wrap {{ max-width: 920px; margin: 0 auto; display: grid; gap: 18px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 20px;
    }}
    h1, h2 {{ margin: 0 0 12px; }}
    .row {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    input, textarea {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0f172a;
      color: var(--text);
      font-size: 14px;
    }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin: 10px 0 4px; }}
    button {{
      border: 0;
      border-radius: 10px;
      padding: 10px 16px;
      font-weight: 600;
      font-size: 14px;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
    }}
    button.secondary {{ background: #1e293b; border: 1px solid var(--border); }}
    button.danger {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .pill {{
      display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;
    }}
    .pill-ok {{ background: rgba(16, 185, 129, 0.2); color: #6ee7b7; }}
    .pill-warn {{ background: rgba(245, 158, 11, 0.2); color: #fde68a; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    @media (max-width: 640px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card row" style="justify-content: space-between;">
      <div>
        <h1 style="font-size:22px; margin:0;">SD-GEN016 OTA — Керування релізами</h1>
        <div style="font-size:13px; color:var(--muted); margin-top:4px;">
          Фіксоване посилання: <a href="/ota/" style="color:#93c5fd;">{base_escaped}/</a> · Прямий APK: <a href="/ota/download/latest.apk" style="color:#93c5fd;">{base_escaped}/download/latest.apk</a>
        </div>
      </div>
      <div class="row">
        <input id="adminToken" type="password" placeholder="OTA Admin Token" style="width:240px;">
        <button type="button" onclick="saveAndLoad()">Увійти / Оновити</button>
      </div>
    </div>

    <div id="adminBody" style="display:none; gap:18px;">
      <div class="card">
        <h2 style="font-size:17px;">Завантажити новий APK</h2>
        <form id="uploadForm" onsubmit="uploadApk(event)">
          <div class="grid-2">
            <div>
              <label>Файл APK (.apk)</label>
              <input id="apkFile" type="file" accept=".apk" required>
            </div>
            <div>
              <label>versionName (напр. 5.6.3)</label>
              <input id="versionName" type="text" placeholder="5.6.3" required>
            </div>
            <div>
              <label>versionCode (ціле число &gt; поточного)</label>
              <input id="versionCode" type="number" min="1" required>
            </div>
            <div>
              <label>Мін. підтримуваний versionCode (0 = не блокувати)</label>
              <input id="uploadMinSupported" type="number" min="0" placeholder="Не змінювати або число">
            </div>
          </div>
          <label>Список змін (Changelog)</label>
          <textarea id="changelog" rows="3" placeholder="Виправлено..."></textarea>
          <div class="row" style="margin-top:12px;">
            <label style="display:flex; align-items:center; gap:8px; margin:0; cursor:pointer;">
              <input id="isMandatory" type="checkbox" style="width:auto;"> Примусове оновлення (is_mandatory)
            </label>
            <button type="submit">Опублікувати реліз</button>
          </div>
        </form>
      </div>

      <div class="card">
        <h2 style="font-size:17px;">Політика підтримки старих версій</h2>
        <div class="row">
          <div style="flex:1; min-width:220px;">
            <label style="margin-top:0;">Мінімально підтримуваний versionCode (усі нижчі версії блокуватимуться вимогою оновити)</label>
            <input id="policyMinCode" type="number" min="0" value="0">
          </div>
          <button type="button" onclick="saveMinSupported()">Зберегти політику</button>
        </div>
      </div>

      <div class="card" style="overflow-x:auto;">
        <h2 style="font-size:17px;">Історія релізів</h2>
        <table>
          <thead>
            <tr>
              <th>Версія</th>
              <th>Статус</th>
              <th>Розмір</th>
              <th>Завантажень</th>
              <th>Changelog / SHA-256</th>
              <th>Дії</th>
            </tr>
          </thead>
          <tbody id="releasesBody"></tbody>
        </table>
      </div>
    </div>
  </div>
  <script>
    const STORAGE_KEY = 'sdgen_ota_admin_token';
    const tokenInput = document.getElementById('adminToken');
    tokenInput.value = sessionStorage.getItem(STORAGE_KEY) || '';
    if (tokenInput.value) loadReleases();

    function getToken() {{
      return tokenInput.value.trim();
    }}

    function saveAndLoad() {{
      const t = getToken();
      if (!t) return alert('Введіть OTA Admin Token');
      sessionStorage.setItem(STORAGE_KEY, t);
      loadReleases();
    }}

    async function apiFetch(url, opts = {{}}) {{
      const headers = new Headers(opts.headers || {{}});
      headers.set('X-OTA-Admin-Token', getToken());
      const res = await fetch(url, {{ ...opts, headers }});
      if (!res.ok) {{
        const err = await res.json().catch(() => ({{ detail: res.statusText }}));
        throw new Error(err.detail || res.statusText);
      }}
      return res.json();
    }}

    async function loadReleases() {{
      try {{
        const data = await apiFetch('/ota/api/releases');
        document.getElementById('adminBody').style.display = 'grid';
        document.getElementById('policyMinCode').value = data.min_supported_version_code || 0;
        const tbody = document.getElementById('releasesBody');
        tbody.innerHTML = '';
        for (const r of data.releases) {{
          const tr = document.createElement('tr');
          const mb = (r.file_size / (1024 * 1024)).toFixed(2) + ' МБ';
          const statusPill = r.is_active
            ? '<span class="pill pill-ok">Активний</span>'
            : '<span class="pill">Архів</span>';
          const mandatoryPill = r.is_mandatory
            ? ' <span class="pill pill-warn">Обовʼязковий</span>'
            : '';
          tr.innerHTML = `
            <td><strong>v${{escapeHtml(r.version_name)}}</strong><br><small>build ${{r.version_code}}</small></td>
            <td>${{statusPill}}${{mandatoryPill}}</td>
            <td>${{mb}}</td>
            <td>${{r.download_count}}</td>
            <td><div>${{escapeHtml(r.changelog || '—')}}</div><small style="color:var(--muted);">${{r.sha256.slice(0, 16)}}...</small></td>
            <td>
              <div class="row">
                <a class="secondary" style="padding:6px 10px; border-radius:8px; text-decoration:none; color:#fff; background:#1e293b;" href="/ota/download/${{r.version_code}}.apk">APK</a>
                ${{r.is_active ? '' : `<button type="button" class="secondary" onclick="activateVersion(${{r.version_code}})">Зробити активним</button>`}}
                <button type="button" class="danger" onclick="deleteVersion(${{r.version_code}})">Видалити</button>
              </div>
            </td>
          `;
          tbody.appendChild(tr);
        }}
      }} catch (e) {{
        document.getElementById('adminBody').style.display = 'none';
        alert('Помилка авторизації або запиту: ' + e.message);
      }}
    }}

    function escapeHtml(s) {{
      return String(s).replace(/[&<>"']/g, ch => ({{ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }}[ch]));
    }}

    async function uploadApk(ev) {{
      ev.preventDefault();
      const file = document.getElementById('apkFile').files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('version_code', document.getElementById('versionCode').value);
      fd.append('version_name', document.getElementById('versionName').value.trim());
      fd.append('changelog', document.getElementById('changelog').value.trim());
      fd.append('is_mandatory', document.getElementById('isMandatory').checked ? 'true' : 'false');
      const minSup = document.getElementById('uploadMinSupported').value.trim();
      if (minSup !== '') fd.append('min_supported_version_code', minSup);
      try {{
        await apiFetch('/ota/api/releases', {{ method: 'POST', body: fd }});
        document.getElementById('uploadForm').reset();
        await loadReleases();
        alert('Реліз успішно опубліковано!');
      }} catch (e) {{
        alert('Помилка публікації: ' + e.message);
      }}
    }}

    async function saveMinSupported() {{
      const minVal = parseInt(document.getElementById('policyMinCode').value || '0', 10);
      try {{
        await apiFetch('/ota/api/policy', {{
          method: 'PATCH',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ min_supported_version_code: minVal }}),
        }});
        await loadReleases();
        alert('Політику оновлено!');
      }} catch (e) {{
        alert('Помилка: ' + e.message);
      }}
    }}

    async function activateVersion(code) {{
      try {{
        await apiFetch('/ota/api/policy', {{
          method: 'PATCH',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ active_version_code: code }}),
        }});
        await loadReleases();
      }} catch (e) {{
        alert('Помилка: ' + e.message);
      }}
    }}

    async function deleteVersion(code) {{
      if (!confirm('Видалити реліз build ' + code + '?')) return;
      try {{
        await apiFetch('/ota/api/releases/' + code, {{ method: 'DELETE' }});
        await loadReleases();
      }} catch (e) {{
        alert('Помилка: ' + e.message);
      }}
    }}
  </script>
</body>
</html>"""
