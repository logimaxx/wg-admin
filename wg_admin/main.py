from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from wg_admin import __version__
from wg_admin.config import Settings, get_settings
from wg_admin.service import Manager, check_password, decode_peer_id, safe_name

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="wg-admin", version=__version__, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def bind_app(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    app.state.settings = settings
    app.state.manager = Manager(settings)


bind_app()


def _manager(request: Request) -> Manager:
    return request.app.state.manager


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _authed(request: Request) -> bool:
    return bool(request.session.get("auth"))


def _csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def _check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise PermissionError("Invalid CSRF token")


def _needs_setup(request: Request) -> bool:
    manager = _manager(request)
    manager.reload_state()
    return not manager.state.password_hash


def _host_hint(request: Request) -> str:
    host = request.headers.get("host", "")
    return host.split(":")[0] if host else ""


def _ctx(request: Request, **extra):
    return {
        "request": request,
        "csrf": _csrf(request) if _authed(request) or request.url.path in {"/login", "/setup"} else "",
        "demo": _settings(request).demo,
        "version": __version__,
        "error": extra.pop("error", ""),
        "notice": extra.pop("notice", request.query_params.get("notice", "")),
        **extra,
    }


def _redirect(path: str, notice: str = "") -> RedirectResponse:
    url = f"{path}?notice={quote(notice)}" if notice else path
    return RedirectResponse(url, status_code=303)


@app.middleware("http")
async def gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static"):
        return await call_next(request)
    if _needs_setup(request) and path != "/setup":
        return RedirectResponse("/setup", status_code=303)
    if not _needs_setup(request) and path == "/setup":
        return RedirectResponse("/login", status_code=303)
    public = {"/login", "/setup"}
    if path not in public and not _authed(request):
        return RedirectResponse("/login", status_code=303)
    try:
        return await call_next(request)
    except FileNotFoundError:
        return templates.TemplateResponse(
            request,
            "error.html",
            _ctx(request, title="Not found", message="That interface or peer does not exist."),
            status_code=404,
        )
    except PermissionError as exc:
        return templates.TemplateResponse(
            request,
            "error.html",
            _ctx(request, title="Forbidden", message=str(exc)),
            status_code=403,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "error.html",
            _ctx(request, title="Cannot complete", message=str(exc)),
            status_code=400,
        )


app.add_middleware(
    SessionMiddleware,
    secret_key=get_settings().session_secret(),
    session_cookie="wg_admin",
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 12,
)


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    discovered = [cfg.name for cfg in _manager(request).configs()]
    return templates.TemplateResponse(
        request,
        "setup.html",
        _ctx(request, title="First run", discovered=discovered, csrf=_csrf(request)),
    )


@app.post("/setup")
async def setup_submit(
    request: Request,
    password: str = Form(...),
    confirm: str = Form(...),
    csrf: str = Form(...),
):
    _check_csrf(request, csrf)
    manager = _manager(request)
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "setup.html",
            _ctx(
                request,
                title="First run",
                discovered=[cfg.name for cfg in manager.configs()],
                csrf=_csrf(request),
                error="Password must be at least 8 characters.",
            ),
            status_code=400,
        )
    if password != confirm:
        return templates.TemplateResponse(
            request,
            "setup.html",
            _ctx(
                request,
                title="First run",
                discovered=[cfg.name for cfg in manager.configs()],
                csrf=_csrf(request),
                error="Passwords do not match.",
            ),
            status_code=400,
        )
    manager.setup_password(password)
    request.session["auth"] = True
    return _redirect("/", "Imported existing WireGuard config.")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _authed(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        _ctx(request, title="Sign in", csrf=_csrf(request)),
    )


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...), csrf: str = Form(...)):
    _check_csrf(request, csrf)
    manager = _manager(request)
    manager.reload_state()
    if not check_password(password, manager.state.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            _ctx(request, title="Sign in", csrf=_csrf(request), error="Wrong password."),
            status_code=401,
        )
    request.session["auth"] = True
    return _redirect("/")


@app.post("/logout")
async def logout(request: Request, csrf: str = Form(...)):
    _check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    interfaces = _manager(request).dashboard(host_hint=_host_hint(request))
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(
            request,
            title="Interfaces",
            interfaces=interfaces,
            config_dir=str(_settings(request).config_dir),
        ),
    )


@app.get("/interfaces/{name}", response_class=HTMLResponse)
async def interface_page(request: Request, name: str):
    view = _manager(request).interface_view(safe_name(name), host_hint=_host_hint(request))
    return templates.TemplateResponse(
        request,
        "interface.html",
        _ctx(request, title=view.name, view=view),
    )


@app.post("/interfaces/{name}/settings")
async def save_settings(
    request: Request,
    name: str,
    csrf: str = Form(...),
    endpoint: str = Form(""),
    client_dns: str = Form(""),
    client_allowed_ips: str = Form(""),
):
    _check_csrf(request, csrf)
    name = safe_name(name)
    _manager(request).save_interface_settings(name, endpoint, client_dns, client_allowed_ips)
    return _redirect(f"/interfaces/{name}", "Client defaults saved.")


@app.post("/interfaces/{name}/peers")
async def add_peer(
    request: Request,
    name: str,
    csrf: str = Form(...),
    peer_name: str = Form(""),
    allowed_ips: str = Form(""),
    keepalive: str = Form("25"),
    notes: str = Form(""),
    use_psk: str = Form(""),
):
    _check_csrf(request, csrf)
    name = safe_name(name)
    peer = _manager(request).add_peer(name, peer_name, allowed_ips, keepalive, notes, use_psk=bool(use_psk))
    return _redirect(f"/interfaces/{name}", f"Added {peer.name}. Download the client config now.")


@app.post("/interfaces/{name}/peers/{public_key}/edit")
async def edit_peer(
    request: Request,
    name: str,
    public_key: str,
    csrf: str = Form(...),
    peer_name: str = Form(""),
    allowed_ips: str = Form(""),
    keepalive: str = Form(""),
    notes: str = Form(""),
):
    _check_csrf(request, csrf)
    name = safe_name(name)
    public_key = decode_peer_id(public_key)
    _manager(request).edit_peer(name, public_key, peer_name, allowed_ips, keepalive, notes)
    return _redirect(f"/interfaces/{name}", "Peer updated.")


@app.post("/interfaces/{name}/peers/{public_key}/delete")
async def delete_peer(request: Request, name: str, public_key: str, csrf: str = Form(...)):
    _check_csrf(request, csrf)
    name = safe_name(name)
    _manager(request).delete_peer(name, decode_peer_id(public_key))
    return _redirect(f"/interfaces/{name}", "Peer removed.")


@app.post("/interfaces/{name}/peers/{public_key}/rotate")
async def rotate_peer(request: Request, name: str, public_key: str, csrf: str = Form(...)):
    _check_csrf(request, csrf)
    name = safe_name(name)
    peer = _manager(request).rotate_peer(name, decode_peer_id(public_key))
    return _redirect(f"/interfaces/{name}", f"Rotated keys for {peer.name}. Download a new client config.")


@app.get("/interfaces/{name}/peers/{public_key}/config")
async def download_config(request: Request, name: str, public_key: str):
    name = safe_name(name)
    public_key = decode_peer_id(public_key)
    manager = _manager(request)
    body = manager.client_config(name, public_key)
    meta = manager.state.peer(name, public_key)
    filename = f"{meta.name or 'peer'}.conf".replace(" ", "_")
    return Response(
        content=body,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/interfaces/{name}/peers/{public_key}/qr")
async def peer_qr(request: Request, name: str, public_key: str):
    name = safe_name(name)
    png = _manager(request).client_qr_png(name, decode_peer_id(public_key))
    return Response(content=png, media_type="image/png")


@app.get("/api/interfaces/{name}/status")
async def interface_status(request: Request, name: str):
    view = _manager(request).interface_view(safe_name(name))
    return {
        "up": view.up,
        "last_handshake": view.last_handshake,
        "peers": [
            {
                "public_key": peer.public_key,
                "handshake": peer.handshake,
                "handshake_class": peer.handshake_class,
                "transfer": peer.transfer,
                "endpoint": peer.endpoint,
            }
            for peer in view.peers
        ],
    }


def cli() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "wg_admin.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.demo,
    )
