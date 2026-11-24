"""Aplicação web individual: login, pesquisa local e sincronização PNCP."""
import asyncio
import hmac
import os
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from .ai import (
    MAX_PDF_BYTES,
    AIConfig,
    AIError,
    analyze_opportunity,
    calls_today,
    document_input,
    init_ai,
)
from .intelligence import CATEGORIES, analyze, validate_quote
from .pncp import sync_pncp
from .quotes import get_item, get_quote, get_quotes_for_items, init_quotes, save_quote
from .scheduler import periodic_scan_loop
from .security import (
    SESSION_SECONDS,
    valid_password_hash,
    make_session,
    new_login_csrf,
    read_session,
    verify_login_csrf,
    verify_password,
)
from .storage import STATUSES, init_db, list_items, recent_events

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def _server_secret(name: str) -> str:
    """Segredo opcional em Docker secret; nunca mostrar conteúdo em erros."""
    file_path = os.getenv(name + "_FILE", "")
    plain = os.getenv(name, "")
    if not file_path:
        return plain
    if plain:
        raise RuntimeError("Segredo configurado por ambiente e arquivo simultaneamente.")
    try:
        source = Path(file_path)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 8192:
            raise OSError("invalid")
        return source.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("Arquivo de segredo obrigatório indisponível.") from None


@dataclass(frozen=True)
class Settings:
    username: str = ""
    password_hash: str = ""
    session_secret: str = ""
    db_path: str = "data/licitaradar.db"
    secure_cookies: bool = True
    auto_scan: bool = False
    scan_interval_minutes: int = 360
    scan_uf: str = "SP"
    ai: AIConfig = field(default_factory=AIConfig)

    @classmethod
    def from_env(cls):
        if os.getenv("APP_ENV") == "production" and os.getenv("COOKIE_SECURE", "1") != "1":
            raise RuntimeError("COOKIE_SECURE=1 é obrigatório em produção.")
        return cls(
            username=os.getenv("LOGIN_USERNAME", ""),
            password_hash=_server_secret("LOGIN_PASSWORD_HASH"),
            session_secret=_server_secret("SESSION_SECRET"),
            db_path=os.getenv("DB_PATH", "data/licitaradar.db"),
            secure_cookies=os.getenv("COOKIE_SECURE", "1") == "1",
            auto_scan=os.getenv("AUTO_SCAN_ENABLED", "0") == "1",
            scan_interval_minutes=int(os.getenv("AUTO_SCAN_INTERVAL_MINUTES", "360")),
            scan_uf=os.getenv("AUTO_SCAN_UF", "SP").strip().upper(),
            ai=AIConfig(
                enabled=os.getenv("AI_ENABLED", "0") == "1",
                provider=os.getenv("AI_PROVIDER", "deepseek").strip().lower(),
                key=_server_secret("AI_API_KEY"),
                model=os.getenv("AI_MODEL", "").strip(),
                daily_limit=int(os.getenv("AI_DAILY_LIMIT", "10")),
            ),
        )

    @property
    def configured(self) -> bool:
        return (
            bool(self.username)
            and "|" not in self.username
            and valid_password_hash(self.password_hash)
            and len(self.session_secret) >= 32
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if os.getenv("APP_ENV") == "production":
        if not settings.secure_cookies or not settings.configured:
            raise RuntimeError("Produção exige login válido e cookie seguro.")
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker = None
        if settings.configured and settings.auto_scan:
            if not 30 <= settings.scan_interval_minutes <= 1440:
                raise RuntimeError("Intervalo automático permitido: 30 a 1440 minutos.")
            if len(settings.scan_uf) != 2 or not settings.scan_uf.isascii() or not settings.scan_uf.isalpha():
                raise RuntimeError("AUTO_SCAN_UF inválida.")
            worker = asyncio.create_task(periodic_scan_loop(
                settings.db_path, settings.scan_uf, settings.scan_interval_minutes,
                _app.state.lock,
            ))
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app = FastAPI(
        title="LicitaRadar", docs_url=None, redoc_url=None,
        openapi_url=None, lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    app.state.settings = settings
    app.state.lock = asyncio.Lock()
    app.state.ai_lock = asyncio.Lock()
    app.state.failed_attempts: dict[str, list[float]] = {}
    if settings.configured:
        init_db(settings.db_path)
        init_quotes(settings.db_path)
        init_ai(settings.db_path)

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
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
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
                        page: int = Query(1, ge=1, le=10000),
                        category: str = Query("", max_length=30)):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        uf = uf.strip().upper()
        if uf and (len(uf) != 2 or not uf.isalpha()):
            return no_cache(PlainTextResponse("UF inválida.", status_code=422))
        if category and category not in CATEGORIES:
            return no_cache(PlainTextResponse("Categoria inválida.", status_code=422))
        records, total, counts, last_sync = list_items(
            settings.db_path, q=q.strip(), uf=uf, status=status, page=page,
            category=category)
        quote_map = get_quotes_for_items(settings.db_path, records)
        for record in records:
            record["analysis"] = analyze(
                record, quote_map.get((record["tender_id"], record["numero"]))
            )
        end = date.today()
        start = end - timedelta(days=1)
        return no_cache(templates.TemplateResponse(request, "dashboard.html", {
            "records": records, "total": total, "counts": counts, "last_sync": last_sync,
            "statuses": STATUSES, "csrf": csrf, "q": q, "uf": uf,
            "status": status, "page": page, "category": category,
            "categories": CATEGORIES,
            "events": recent_events(settings.db_path, 10),
            "auto_scan": settings.auto_scan,
            "scan_interval": settings.scan_interval_minutes,
            "scan_uf": settings.scan_uf,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }))

    @app.get("/api/items")
    async def items_api(request: Request, q: str = Query("", max_length=120),
                        uf: str = Query("", max_length=2),
                        status: int = Query(0, ge=0, le=5),
                        page: int = Query(1, ge=1, le=10000),
                        category: str = Query("", max_length=30)):
        csrf = guard(request, json=True)
        if not isinstance(csrf, str):
            return csrf
        uf = uf.strip().upper()
        if uf and (len(uf) != 2 or not uf.isalpha()):
            return JSONResponse({"error": "UF inválida."}, status_code=422)
        if category and category not in CATEGORIES:
            return no_cache(JSONResponse({"error": "Categoria inválida."}, status_code=422))
        rows, total, counts, latest = list_items(
            settings.db_path, q=q.strip(), uf=uf, status=status, page=page,
            category=category)
        quote_map = get_quotes_for_items(settings.db_path, rows)
        for row in rows:
            row["analysis"] = analyze(
                row, quote_map.get((row["tender_id"], row["numero"]))
            )
        return no_cache(JSONResponse({
            "data": rows, "total": total, "page": page,
            "counts": counts, "last_sync": latest,
            "participant_count": None, "participant_count_source": "não disponível",
        }))

    @app.get("/api/changes")
    async def changes_api(request: Request):
        csrf = guard(request, json=True)
        if not isinstance(csrf, str):
            return csrf
        return no_cache(JSONResponse({"data": recent_events(settings.db_path, 100)}))


    @app.get("/quote", response_class=HTMLResponse)
    async def quote_page(
        request: Request,
        tender_id: str = Query(..., min_length=1, max_length=180),
        numero: int = Query(..., ge=1, le=100000),
    ):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        item = get_item(settings.db_path, tender_id, numero)
        if item is None:
            return no_cache(PlainTextResponse("Item não encontrado.", status_code=404))
        quote = get_quote(settings.db_path, tender_id, numero)
        form = quote or {
            "supplier": "", "unit_cost": "", "freight": "0.00",
            "packaging": "0.00", "other": "0.00", "risk_reserve": "0.00",
            "tax_percent": "0.00", "target_margin": "15.00",
        }
        return no_cache(templates.TemplateResponse(request, "quote.html", {
            "csrf": csrf, "item": item, "form": form, "error": None,
            "analysis": analyze(item, quote),
        }))

    @app.post("/quote", response_class=HTMLResponse)
    async def quote_submit(request: Request):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        form_data = await request.form()
        if not check_csrf(csrf, str(form_data.get("csrf") or "")):
            return no_cache(PlainTextResponse("Token de segurança inválido.", status_code=403))
        tender_id = str(form_data.get("tender_id") or "")
        try:
            numero = int(str(form_data.get("numero") or "0"))
        except ValueError:
            return no_cache(PlainTextResponse("Item inválido.", status_code=422))
        if not 1 <= len(tender_id) <= 180 or not 1 <= numero <= 100000:
            return no_cache(PlainTextResponse("Item inválido.", status_code=422))
        item = get_item(settings.db_path, tender_id, numero)
        if item is None:
            return no_cache(PlainTextResponse("Item não encontrado.", status_code=404))
        fields = ("supplier", "unit_cost", "freight", "packaging", "other",
                  "risk_reserve", "tax_percent", "target_margin")
        entered = {key: str(form_data.get(key) or "") for key in fields}
        try:
            values = validate_quote(entered)
            save_quote(settings.db_path, tender_id, numero, values)
        except ValueError as exc:
            return no_cache(templates.TemplateResponse(
                request, "quote.html", {
                    "csrf": csrf, "item": item, "form": entered,
                    "error": str(exc), "analysis": analyze(
                        item, get_quote(settings.db_path, tender_id, numero)),
                }, status_code=422
            ))
        from urllib.parse import urlencode

        target = urlencode({"tender_id": tender_id, "numero": numero})
        return no_cache(RedirectResponse("/quote?" + target, status_code=303))


    def ai_context(item: dict, csrf: str, *, report: dict | None = None,
                   origin: str = "Sem documento fornecido", cached: bool = False,
                   error: str | None = None):
        quote = get_quote(settings.db_path, item["tender_id"], item["numero"])
        financial = analyze(item, quote)
        return {
            "csrf": csrf, "item": item, "analysis": financial,
            "ai_status": settings.ai.public_status(),
            "calls_today": calls_today(settings.db_path),
            "report": report, "origin": origin, "cached": cached, "error": error,
        }

    @app.get("/ai", response_class=HTMLResponse)
    async def ai_page(
        request: Request,
        tender_id: str = Query(..., min_length=1, max_length=180),
        numero: int = Query(..., ge=1, le=100000),
    ):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        item = get_item(settings.db_path, tender_id, numero)
        if item is None:
            return no_cache(PlainTextResponse("Item não encontrado.", status_code=404))
        return no_cache(templates.TemplateResponse(
            request, "ai.html", ai_context(item, csrf),
        ))

    @app.post("/ai", response_class=HTMLResponse)
    async def ai_submit(request: Request):
        csrf = guard(request)
        if not isinstance(csrf, str):
            return csrf
        form_data = await request.form()
        if not check_csrf(csrf, str(form_data.get("csrf") or "")):
            return no_cache(PlainTextResponse("Token de segurança inválido.", status_code=403))
        tender_id = str(form_data.get("tender_id") or "")
        try:
            numero = int(str(form_data.get("numero") or "0"))
        except ValueError:
            return no_cache(PlainTextResponse("Item inválido.", status_code=422))
        if not 1 <= len(tender_id) <= 180 or not 1 <= numero <= 100000:
            return no_cache(PlainTextResponse("Item inválido.", status_code=422))
        item = get_item(settings.db_path, tender_id, numero)
        if item is None:
            return no_cache(PlainTextResponse("Item não encontrado.", status_code=404))
        if form_data.get("consent") != "yes":
            return no_cache(PlainTextResponse(
                "Confirme o compartilhamento dos dados com o provedor de IA.",
                status_code=403,
            ))
        if not settings.ai.valid:
            return no_cache(templates.TemplateResponse(
                request, "ai.html", ai_context(
                    item, csrf, error="IA desativada. Configure AI_ENABLED=1 e "
                    "AI_API_KEY no ambiente privado do servidor.",
                ), status_code=503
            ))
        try:
            excerpt = str(form_data.get("document_text") or "")
            if len(excerpt) > 3500:
                raise AIError("Trecho de texto maior que 3.500 caracteres.")
            upload = form_data.get("document_pdf")
            pdf_bytes = None
            if isinstance(upload, UploadFile) and upload.filename:
                if not upload.filename.casefold().endswith(".pdf"):
                    raise AIError("Anexe somente arquivo .pdf.")
                pdf_bytes = await upload.read(MAX_PDF_BYTES + 1)
            document, origin = document_input(excerpt, pdf_bytes)
            quote = get_quote(settings.db_path, tender_id, numero)
            async with app.state.ai_lock:
                report, cached = await analyze_opportunity(
                    settings.db_path, settings.ai, item, quote,
                    document, origin,
                )
        except AIError as exc:
            return no_cache(templates.TemplateResponse(
                request, "ai.html", ai_context(
                    item, csrf, error=str(exc),
                ), status_code=exc.status_code
            ))
        return no_cache(templates.TemplateResponse(
            request, "ai.html", ai_context(
                item, csrf, report=report, origin=origin, cached=cached,
            ),
        ))

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
