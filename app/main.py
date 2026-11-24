"""Aplicação web individual: login, pesquisa local e sincronização PNCP."""
import asyncio
import hmac
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .pncp import sync_pncp
from .security import (
    SESSION_SECONDS, make_session, new_login_csrf, read_session,
    verify_login_csrf, verify_password,
)
from .storage import STATUSES, init_db, list_items

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@dataclass(frozen=True)
class Settings:
    username: str = ""
    password_hash: str = ""
    session_secret: str = ""
    db_path: str = "data/licitaradar.db"
    secure_cookies: bool = True

    @classmethod
    def from_env(cls):
        if os.getenv("APP_ENV") == "production" and os.getenv("COOKIE_SECURE", "1") != "1":
            raise RuntimeError("COOKIE_SECURE=1 é obrigatório em produção.")
        return cls(
            username=os.getenv("LOGIN_USERNAME", ""),
            password_hash=os.getenv("LOGIN_PASSWORD_HASH", ""),
            session_secret=os.getenv("SESSION_SECRET", ""),
            db_path=os.getenv("DB_PATH", "data/licitaradar.db"),
            secure_cookies=os.getenv("COOKIE_SECURE", "1") == "1",
        )

    @property
    def configured(self) -> bool:
        return (
            bool(self.username)
            and "|" not in self.username
            and self.password_hash.startswith("pbkdf2_sha256$")
            and len(self.session_secret) >= 32
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="LicitaRadar", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    app.state.settings = settings
    app.state.lock = asyncio.Lock()
    app.state.failed_attempts: dict[str, list[float]] = {}
    if settings.configured:
        init_db(settings.db_path)

    def session_csrf(request: Request) -> str | None:
        if not settings.configured:
            return None
        return read_session(request.cookies.get("lr_session"), settings.username, settings.session_secret)

    def cookie_kwargs() -> dict:
        return {"httponly": True, "secure": settings.secure_cookies,
                "samesite": "strict", "path": "/"}

    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def guard(request: Request, json: bool = False):
        if not settings.configured:
            return no_cache(PlainTextResponse("Configuração de login ausente. Consulte README.", status_code=503))
        csrf = session_csrf(request)
        if csrf is None:
            return no_cache(JSONResponse({"error": "Não autenticado."}, status_code=401)) if json else no_cache(RedirectResponse("/login", status_code=303))
        return csrf

    def check_csrf(expected: str, supplied: str):
        return bool(supplied and hmac.compare_digest(expected, supplied))

    @app.get("/healthz")
    async def health():
        return {"status": "ok" if settings.configured else "setup_required"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if not settings.configured:
            return no_cache(PlainTextResponse("Configure credenciais de login antes de iniciar.", status_code=503))
        if session_csrf(request):
            return no_cache(RedirectResponse("/", status_code=303))
        csrf, signed = new_login_csrf(settings.session_secret)
        response = templates.TemplateResponse(
            request, "login.html", {"csrf": csrf, "error": False})
        response.set_cookie("lr_login_csrf", signed, max_age=900, **cookie_kwargs())
        return no_cache(response)

    @app.post("/login")
    async def login(request: Request):
        if not settings.configured:
            return no_cache(PlainTextResponse("Login não configurado.", status_code=503))
        form = await request.form()
        token = str(form.get("csrf") or "")
        if not verify_login_csrf(token, request.cookies.get("lr_login_csrf"), settings.session_secret):
            return no_cache(PlainTextResponse("Formulário expirado. Recarregue /login.", status_code=403))
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        recent = [x for x in app.state.failed_attempts.get(ip, []) if now - x < 900]
        if len(recent) >= 6:
            app.state.failed_attempts[ip] = recent
            return no_cache(PlainTextResponse("Muitas tentativas. Tente novamente mais tarde.", status_code=429))
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        good_name = hmac.compare_digest(username, settings.username)
        good_pass = verify_password(password, settings.password_hash)
        if not (good_name and good_pass):
            recent.append(now)
            app.state.failed_attempts[ip] = recent
            # Em caso de erro, o nonce antigo não deve servir para sucessivas tentativas.
            csrf, signed = new_login_csrf(settings.session_secret)
            response = templates.TemplateResponse(
                request, "login.html", {"csrf": csrf, "error": True}, status_code=401)
            response.set_cookie("lr_login_csrf", signed, max_age=900, **cookie_kwargs())
            return no_cache(response)
        app.state.failed_attempts.pop(ip, None)
        session, _ = make_session(settings.username, settings.session_secret)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("lr_session", session, max_age=SESSION_SECONDS, **cookie_kwargs())
        response.delete_cookie("lr_login_csrf", path="/")
        return no_cache(response)

    @app.post("/logout")
    async def logout(request: Request):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        form = await request.form()
        if not check_csrf(csrf, str(form.get("csrf") or "")):
            return no_cache(PlainTextResponse("Token de segurança inválido.", status_code=403))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("lr_session", path="/")
        return no_cache(response)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, q: str = Query("", max_length=120),
                        uf: str = Query("", max_length=2),
                        status: int = Query(0, ge=0, le=5),
                        page: int = Query(1, ge=1, le=10000)):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        uf = uf.strip().upper()
        if uf and (len(uf) != 2 or not uf.isalpha()):
            return no_cache(PlainTextResponse("UF inválida.", status_code=422))
        records, total, counts, last_sync = list_items(
            settings.db_path, q=q.strip(), uf=uf, status=status, page=page)
        end = date.today()
        start = end - timedelta(days=1)
        return no_cache(templates.TemplateResponse(request, "dashboard.html", {
            "records": records, "total": total, "counts": counts, "last_sync": last_sync,
            "statuses": STATUSES, "csrf": csrf, "q": q, "uf": uf,
            "status": status, "page": page, "start": start.isoformat(),
            "end": end.isoformat(),
        }))

    @app.get("/api/items")
    async def items_api(request: Request, q: str = Query("", max_length=120),
                        uf: str = Query("", max_length=2),
                        status: int = Query(0, ge=0, le=5),
                        page: int = Query(1, ge=1, le=10000)):
        csrf = guard(request, json=True)
        if not isinstance(csrf, str):
            return csrf
        uf = uf.strip().upper()
        if uf and (len(uf) != 2 or not uf.isalpha()):
            return JSONResponse({"error": "UF inválida."}, status_code=422)
        rows, total, counts, latest = list_items(
            settings.db_path, q=q.strip(), uf=uf, status=status, page=page)
        return no_cache(JSONResponse({
            "data": rows, "total": total, "page": page,
            "counts": counts, "last_sync": latest,
            "participant_count": None, "participant_count_source": "não disponível",
        }))

    @app.post("/sync")
    async def synchronize(request: Request):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        form = await request.form()
        if not check_csrf(csrf, str(form.get("csrf") or "")):
            return no_cache(PlainTextResponse("Token de segurança inválido.", status_code=403))
        try:
            start = date.fromisoformat(str(form.get("start") or ""))
            end = date.fromisoformat(str(form.get("end") or ""))
            uf = str(form.get("uf") or "").strip().upper()
            modality = int(str(form.get("modality") or "6"))
            if start > date.today() or end > date.today() or start.year < 2021:
                raise ValueError("Datas fora dos limites.")
            if app.state.lock.locked():
                return no_cache(PlainTextResponse("Sincronização já está em andamento.", status_code=409))
            async with app.state.lock:
                await sync_pncp(settings.db_path, start, end, uf, modality)
        except ValueError as exc:
            return no_cache(PlainTextResponse(str(exc), status_code=422))
        return no_cache(RedirectResponse("/?synced=1", status_code=303))

    return app


app = create_app()
