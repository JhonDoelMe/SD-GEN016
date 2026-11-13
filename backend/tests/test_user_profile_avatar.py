import io
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from backend.app.config import settings


def _make_png_bytes(width: int = 400, height: int = 300, color=(20, 130, 200)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_profile_update_and_avatar_lifecycle(
    client: AsyncClient,
    superadmin_auth: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    # 1. Update own profile
    upd = await client.put(
        "/api/v1/auth/me",
        json={"full_name": "Олександр Іваненко", "email": "oleksandr@example.com"},
        headers=superadmin_auth,
    )
    assert upd.status_code == 200
    assert upd.json()["full_name"] == "Олександр Іваненко"
    assert upd.json()["email"] == "oleksandr@example.com"

    # Invalid email rejected
    bad_upd = await client.put(
        "/api/v1/auth/me",
        json={"email": "not-an-email"},
        headers=superadmin_auth,
    )
    assert bad_upd.status_code == 422

    # 2. Reject invalid image upload (e.g. SVG script attempt)
    bad_file = await client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("xss.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
        headers=superadmin_auth,
    )
    assert bad_file.status_code == 400

    # 3. Upload valid PNG avatar -> converted to 256x256 WebP
    png1 = _make_png_bytes(512, 320, (14, 165, 233))
    up1 = await client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("photo.png", png1, "image/png")},
        headers=superadmin_auth,
    )
    assert up1.status_code == 200
    avatar_url1 = up1.json()["avatar_url"]
    assert avatar_url1 and avatar_url1.startswith("/uploads/avatars/user_")
    assert avatar_url1.endswith(".webp")

    rel1 = avatar_url1.removeprefix("/uploads/")
    file1 = tmp_path / rel1
    assert file1.is_file()
    with Image.open(file1) as saved:
        assert saved.size == (256, 256)
        assert saved.format == "WEBP"

    # Cookie/Bearer fetch succeeds; clearing cookie fails auth with 401
    auth_get = await client.get(avatar_url1, headers=superadmin_auth)
    assert auth_get.status_code == 200
    saved_cookies = client.cookies.jar
    client.cookies.clear()
    try:
        anon_get = await client.get(avatar_url1)
        assert anon_get.status_code == 401
    finally:
        for cookie in saved_cookies:
            client.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)

    # 4. Replacing avatar deletes the previous file
    png2 = _make_png_bytes(300, 300, (34, 197, 94))
    up2 = await client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("photo2.png", png2, "image/png")},
        headers=superadmin_auth,
    )
    assert up2.status_code == 200
    avatar_url2 = up2.json()["avatar_url"]
    assert avatar_url2 != avatar_url1
    assert not file1.exists()
    assert (tmp_path / avatar_url2.removeprefix("/uploads/")).is_file()

    # 5. Deleting own avatar clears avatar_url and removes file
    del_res = await client.delete("/api/v1/auth/me/avatar", headers=superadmin_auth)
    assert del_res.status_code == 200
    assert del_res.json()["avatar_url"] is None
    assert not (tmp_path / avatar_url2.removeprefix("/uploads/")).exists()


@pytest.mark.asyncio
async def test_admin_manage_user_avatar(
    client: AsyncClient,
    superadmin_auth: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    create_res = await client.post(
        "/api/v1/users",
        json={
            "login": "avatar_operator",
            "password": "OperatorPass123",
            "full_name": "Тестовий Оператор",
            "facility_id": 1,
        },
        headers=superadmin_auth,
    )
    assert create_res.status_code == 201
    uid = create_res.json()["id"]

    up_res = await client.post(
        f"/api/v1/users/{uid}/avatar",
        files={"file": ("op.png", _make_png_bytes(), "image/png")},
        headers=superadmin_auth,
    )
    assert up_res.status_code == 200
    av_url = up_res.json()["avatar_url"]
    assert av_url and (tmp_path / av_url.removeprefix("/uploads/")).is_file()

    del_res = await client.delete(f"/api/v1/users/{uid}/avatar", headers=superadmin_auth)
    assert del_res.status_code == 200
    assert del_res.json()["avatar_url"] is None
    assert not (tmp_path / av_url.removeprefix("/uploads/")).exists()


@pytest.mark.asyncio
async def test_modular_frontend_assets_and_unique_ids(client: AsyncClient):
    import re
    from collections import Counter

    root_res = await client.get("/")
    assert root_res.status_code == 200
    html = root_res.text
    assert "/frontend/css/base.css" in html
    assert "/frontend/css/layout.css" in html
    assert "/frontend/js/view-loader.js" in html
    assert 'id="navDrawer"' in html
    assert 'id="accountMenuBtn"' in html
    assert 'id="accountDropdown"' in html
    assert 'mobile-bottom-nav' not in html

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    html_files = [frontend_dir / "index.html", *sorted((frontend_dir / "views").glob("*.html"))]
    all_ids: list[tuple[str, str]] = []
    for path in html_files:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'\bid="([^"]+)"', text):
            all_ids.append((match.group(1), path.name))

    counts = Counter(elem_id for elem_id, _ in all_ids)
    duplicates = {elem_id: [f for eid, f in all_ids if eid == elem_id] for elem_id, n in counts.items() if n > 1}
    assert not duplicates, f"Duplicate element IDs across modular HTML views: {duplicates}"

    for subdir, ext in (("css", "*.css"), ("views", "*.html"), ("js", "*.js")):
        for asset in sorted((frontend_dir / subdir).glob(ext)):
            resp = await client.get(f"/frontend/{subdir}/{asset.name}")
            assert resp.status_code == 200, f"Failed to serve /frontend/{subdir}/{asset.name}"

    expected_tabs = (
        "dashboard",
        "fuel",
        "maintenance",
        "faults",
        "runs",
        "reports",
        "audit",
        "measurement",
        "admin",
    )
    for tab_name in expected_tabs:
        view_path = frontend_dir / "views" / f"{tab_name}.html"
        content = re.sub(r"^\s*(?:<!--[\s\S]*?-->\s*)*", "", view_path.read_text(encoding="utf-8")).strip()
        assert re.match(rf'^<section id="tab-{tab_name}" class="tab-pane(?:\s+active)?"', content), (
            f"{view_path.name} must start with <section id=\"tab-{tab_name}\" class=\"tab-pane...\""
        )
        assert content.endswith("</section>"), f"{view_path.name} must end with </section>"
        assert f'data-tab="tab-{tab_name}"' in html, f"Menu item for tab-{tab_name} missing from index.html"

    for view_path in sorted((frontend_dir / "views").glob("*.html")):
        text = view_path.read_text(encoding="utf-8")
        assert len(re.findall(r"<section\b", text)) == len(re.findall(r"</section>", text)), (
            f"Unbalanced <section> tags in {view_path.name}"
        )
        assert len(re.findall(r"<div\b", text)) == len(re.findall(r"</div>", text)), (
            f"Unbalanced <div> tags in {view_path.name}"
        )
