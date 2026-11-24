"""Testes locais, sem acesso à Internet: API PNCP simulada."""
import re
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.pncp import sync_pncp
from app.security import hash_password, make_session, read_session, verify_password
from app.storage import init_db, list_items, upsert_tender

STRONG_PASSWORD = "SenhaLongaUnicaDeTeste#2026"
SECRET = "s" * 48


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "licitaradar.sqlite")
    init_db(path)
    return path


@pytest.fixture
def client(db_path):
    app = create_app(Settings(
        username="admin", password_hash=hash_password(STRONG_PASSWORD, b"1234567890abcdef"),
        session_secret=SECRET, db_path=db_path, secure_cookies=False,
    ))
    with TestClient(app) as instance:
        yield instance


def login(client):
    page = client.get("/login")
    assert page.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post("/login", data={
        "csrf": token, "username": "admin", "password": STRONG_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 303
    return response


def demo_tender():
    return {
        "numeroControlePNCP": "12345678000190-1-000001/2026",
        "anoCompra": 2026, "sequencialCompra": 1,
        "orgaoEntidade": {"cnpj": "12345678000190", "razaoSocial": "Prefeitura Exemplo"},
        "unidadeOrgao": {"ufSigla": "SP", "municipioNome": "Salto"},
        "objetoCompra": "Aquisição de cadeira para escola",
        "dataPublicacaoPncp": "2026-11-22T12:00:00",
        "dataAberturaProposta": "2026-11-22T13:00:00",
        "dataEncerramentoProposta": "2026-11-27T13:00:00",
    }


def demo_items():
    return [
        {"numeroItem": 1, "materialOuServico": "M", "descricao": "Cadeira escolar",
         "situacaoCompraItemId": 4, "valorTotal": 1200.0, "quantidade": 6},
        {"numeroItem": 2, "materialOuServico": "M", "descricao": "Capacete de segurança",
         "situacaoCompraItemId": 5, "valorTotal": 500.0, "quantidade": 5},
        {"numeroItem": 3, "materialOuServico": "S", "descricao": "Instalação",
         "situacaoCompraItemId": 2, "valorTotal": 100.0},
    ]


def test_password_hash_and_session_expiry():
    encoded = hash_password(STRONG_PASSWORD, b"1234567890abcdef")
    assert verify_password(STRONG_PASSWORD, encoded)
    assert not verify_password("errada", encoded)
    assert not verify_password(STRONG_PASSWORD, "pbkdf2_sha256$9999999999999$a$b")
    cookie, csrf = make_session("admin", SECRET, now=1000)
    assert read_session(cookie, "admin", SECRET, now=1001) == csrf
    assert read_session(cookie, "admin", SECRET, now=1000 + 12 * 3600 + 1) is None
    assert read_session(cookie + "x", "admin", SECRET, now=1001) is None


def test_login_and_route_protection(client):
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/items").status_code == 401
    assert client.get("/register").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/healthz").json()["status"] == "ok"
    response = login(client)
    assert "lr_session" in response.cookies
    assert "Oportunidades em foco" in client.get("/").text
    assert client.get("/api/items").json()["total"] == 0
    assert client.get("/").headers["cache-control"] == "no-store"


def test_login_wrong_password_and_csrf(client):
    page = client.get("/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    assert client.post("/login", data={"username": "admin", "password": STRONG_PASSWORD,
                                       "csrf": "invalido"}).status_code == 403
    wrong = client.post("/login", data={"username": "admin",
                         "password": "senha incorreta", "csrf": token})
    assert wrong.status_code == 401
    assert "lr_session" not in wrong.cookies


def test_logout_and_sync_require_csrf(client):
    login(client)
    assert client.post("/sync", data={}).status_code == 403
    assert client.post("/logout", data={"csrf": "invalido"}).status_code == 403
    dashboard = client.get("/")
    token = re.search(r'name="csrf" value="([^"]+)"', dashboard.text).group(1)
    assert client.post("/logout", data={"csrf": token}, follow_redirects=False).status_code == 303
    assert client.get("/api/items").status_code == 401


@pytest.mark.asyncio
async def _unused():
    """Não são necessários plugins de pytest async: usar asyncio.run para ingestão."""
    return None


def test_pncp_import_is_idempotent_and_detects_deserts(db_path):
    from asyncio import run
    def handler(request: httpx.Request) -> httpx.Response:
        if "/contratacoes/publicacao" in str(request.url):
            assert request.url.params["codigoModalidadeContratacao"] == "6"
            return httpx.Response(200, json={"data": [demo_tender()], "paginasRestantes": 0})
        assert "/api/pncp/v1/orgaos/" in str(request.url)
        return httpx.Response(200, json={"itens": demo_items(), "totalPaginas": 1})

    transport = httpx.MockTransport(handler)
    for _ in range(2):
        result = run(sync_pncp(db_path, date(2026, 11, 21), date(2026, 11, 22),
                               "SP", 6, transport=transport))
        assert result == {"fetched": 1, "items": 2, "errors": 0, "detail": "Concluído."}
    rows, count, statuses, latest = list_items(db_path)
    assert count == 2
    assert statuses == {4: 1, 5: 1}
    assert latest["errors"] == 0
    assert {r["descricao"] for r in rows} == {"Cadeira escolar", "Capacete de segurança"}
    assert list_items(db_path, status=4)[1] == 1
    assert list_items(db_path, q="capacete")[1] == 1
    assert list_items(db_path, uf="RJ")[1] == 0
    assert list_items(db_path, q="%")[1] == 0


def test_pncp_item_failure_does_not_create_false_zero(db_path):
    from asyncio import run
    def handler(request):
        if "/contratacoes/publicacao" in str(request.url):
            return httpx.Response(200, json={"data": [demo_tender()], "paginasRestantes": 0})
        return httpx.Response(503, json={"error": "down"})

    result = run(sync_pncp(db_path, date(2026, 11, 21), date(2026, 11, 22), "",
                           6, transport=httpx.MockTransport(handler)))
    assert result["errors"] == 1
    assert result["items"] == 0
    assert list_items(db_path)[1] == 0


def test_pncp_invalid_date_rejected_without_request(db_path):
    from asyncio import run
    with pytest.raises(ValueError):
        run(sync_pncp(db_path, date(2026, 11, 1), date(2026, 11, 22), "SP", 6))
    with pytest.raises(ValueError):
        run(sync_pncp(db_path, date(2026, 11, 21), date(2026, 11, 22), "SÃO", 6))
    with pytest.raises(ValueError):
        run(sync_pncp(db_path, date(2026, 11, 21), date(2026, 11, 22), "", 99))


def test_confidential_budget_and_html_escaping(client, db_path):
    tender = {
        "id": "ID-1", "cnpj": "12345678000190", "ano": 2026, "sequencial": 1,
        "orgao": "Cidade", "municipio": "Salto", "uf": "SP",
        "objeto": "Cadeiras", "data_publicacao": "2026-11-23",
        "abertura": None, "encerramento": None,
        "link": "https://pncp.gov.br/app/editais/12345678000190/2026/1",
    }
    upsert_tender(db_path, tender, [{
        "numeroItem": 1, "materialOuServico": "M",
        "descricao": "<script>alert('x')</script>", "orcamentoSigiloso": True,
        "valorTotal": 5000, "situacaoCompraItemId": 4,
    }])
    login(client)
    result = client.get("/")
    assert "&lt;script&gt;" in result.text
    assert "<script>alert" not in result.text
    assert "Não informado / sigiloso" in result.text
    assert client.get("/api/items").json()["participant_count"] is None


def test_missing_credentials_fail_closed(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "missing.db")))
    with TestClient(app) as client:
        assert client.get("/").status_code == 503
        assert client.get("/login").status_code == 503
        assert client.get("/api/items").status_code == 503
        assert client.get("/healthz").json()["status"] == "setup_required"
