"""Contrato pré-produção R1-R14: sessão, fluxo completo, SQLite e sem rede paga."""
import base64
import binascii
import hashlib
import hmac
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ai import init_ai
from app.coverage import init_coverage
from app.main import Settings, create_app
from app.monitor import monitor_data
from app.quotes import get_quote, init_quotes
from app.results import init_results
from app.security import (
    hash_password,
    read_session,
    unsign,
    verify_login_csrf,
)
from app.storage import init_db, upsert_tender
from app.suppliers import init_suppliers
from app.workspace import get_case, init_workspace

USERNAME = "operator"
PASSWORD = "SenhaSinteticaQA#2026"
SECRET = "safeguard_code_stage_session_secret_2026"
TENDER = "12345678000190-1-000007/2026"


def demo_tender():
    return {
        "id": TENDER, "cnpj": "12345678000190", "ano": 2026,
        "sequencial": 7, "orgao": "Prefeitura Fictícia",
        "municipio": "Salto", "uf": "SP", "objeto": "Papelaria",
        "data_publicacao": "2026-11-20", "abertura": None, "encerramento": None,
        "link": "https://pncp.gov.br/app/editais/12345678000190/2026/7",
    }


def demo_item():
    return [{
        "numeroItem": 1,
        "materialOuServico": "M",
        "descricao": "Papel sulfite A4 pacote 500 folhas",
        "situacaoCompraItemId": 4,
        "quantidade": 10,
        "valorTotal": 300,
    }]


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "release_qa.db")
    init_db(path)
    init_quotes(path)
    init_ai(path)
    init_results(path)
    init_coverage(path)
    init_workspace(path)
    init_suppliers(path)
    upsert_tender(path, demo_tender(), demo_item())
    return path


@pytest.fixture
def http(db):
    with TestClient(create_app(Settings(
        username=USERNAME,
        password_hash=hash_password(PASSWORD, b"1234567890abcdef"),
        session_secret=SECRET,
        db_path=db,
        secure_cookies=False,
        auto_scan=False,
    ))) as client:
        yield client


def authenticate(client):
    login = client.get("/login")
    assert login.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', login.text).group(1)
    response = client.post("/login", data={
        "csrf": token, "username": USERNAME, "password": PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def csrf(client):
    response = client.get("/")
    assert response.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    return token


def signed_invalid_payload(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
    return payload + "." + signature


def test_invalid_signed_base64_never_raises_or_authenticates(http):
    # Mesmo com assinatura HMAC correta, base64 incorreto não pode virar HTTP 500.
    cookie = signed_invalid_payload("A", SECRET)
    with pytest.raises(binascii.Error):
        base64.urlsafe_b64decode("A===")
    assert unsign(cookie, SECRET) is None
    assert read_session(cookie, USERNAME, SECRET) is None
    assert verify_login_csrf("nonce", cookie, SECRET) is False
    http.cookies.set("lr_session", cookie)
    response = http.get("/api/items")
    assert response.status_code == 401
    assert response.json() == {"error": "Não autenticado."}
    assert http.get("/", follow_redirects=False).status_code == 303
    http.cookies.delete("lr_session")


@pytest.mark.parametrize("route,params", [
    ("/", {}),
    ("/monitor", {}),
    ("/coverage", {}),
    ("/workspace", {}),
    ("/quote", {"tender_id": TENDER, "numero": 1}),
    ("/suppliers", {"tender_id": TENDER, "numero": 1}),
    ("/results", {"tender_id": TENDER, "numero": 1}),
    ("/ai", {"tender_id": TENDER, "numero": 1}),
])
def test_every_sensitive_html_route_denies_anonymous(http, route, params):
    response = http.get(route, params=params, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("route,params", [
    ("/api/items", {}),
    ("/api/monitor", {}),
    ("/api/coverage", {}),
    ("/api/workspace", {}),
    ("/api/suppliers", {"tender_id": TENDER, "numero": 1}),
    ("/api/results", {"tender_id": TENDER, "numero": 1}),
    ("/workspace/export.csv", {}),
])
def test_every_private_api_route_denies_anonymous(http, route, params):
    response = http.get(route, params=params)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_idempotent_sqlite_setup_preserves_quotes_and_opportunities(db):
    # Rodar setup novamente é migração sem perda de dados ou duplicação.
    for _ in range(2):
        init_db(db)
        init_quotes(db)
        init_ai(db)
        init_results(db)
        init_coverage(db)
        init_workspace(db)
        init_suppliers(db)
    upsert_tender(db, demo_tender(), demo_item())
    upsert_tender(db, demo_tender(), demo_item())
    assert len(monitor_data(db)["alerts"]) == 0


def test_full_private_journey_keeps_pncp_and_user_decisions_separate(http, db):
    params = {"tender_id": TENDER, "numero": 1}
    authenticate(http)
    token = csrf(http)
    base_post = {"csrf": token, "tender_id": TENDER, "numero": "1"}

    def post(path, data):
        response = http.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303, (path, response.text[:250])
        return response

    # Fonte oficial sintética: item deserto; regras e favoritos são locais.
    post("/monitor/rule", {
        "csrf": token, "keyword": "papel sulfite", "uf": "SP",
        "status": "4", "category": "papelaria",
    })
    post("/monitor/favorite", {**base_post, "action": "add"})
    alerts = http.get("/api/monitor").json()
    assert alerts["unread"] >= 1
    assert len(alerts["favorites"]) == 1

    # Oráculo determinístico: 9*10 + 30 de frete = 120,
    # preço mínimo = ceil(120/(1 - .10 - .20), 2) = 171.43.
    payload = {
        **base_post, "supplier": "Distribuidora Sintética",
        "unit_cost": "9.00", "freight": "30.00",
        "packaging": "0.00", "other": "0.00",
        "risk_reserve": "0.00", "tax_percent": "10.00",
        "target_margin": "20.00",
        "source_url": "https://example.com/cotacao-informada",
        "observed_on": date.today().isoformat(),
        "note": "Fictício: não enviado a fornecedor real",
    }
    post("/suppliers/add", payload)
    assert get_quote(db, TENDER, 1) is None
    offers = http.get("/api/suppliers", params=params).json()["data"]
    assert len(offers) == 1
    assert offers[0]["analysis"]["total_cost"] == "120.00"
    assert offers[0]["analysis"]["min_viable"] == "171.43"
    post("/suppliers/promote", {**base_post, "offer_id": offers[0]["id"]})
    assert get_quote(db, TENDER, 1)["supplier"] == "Distribuidora Sintética"

    items = http.get("/api/items").json()
    selected = items["data"][0]
    assert selected["status"] == 4  # Estado oficial DESERTO não muda.
    assert selected["watched"] is True
    assert selected["analysis"]["total_cost"] == "120.00"
    assert selected["analysis"]["min_viable"] == "171.43"
    assert items["participant_count"] is None

    post("/workspace/save", {
        **base_post, "stage": "cotando",
        "priority": "alta", "deadline": date.today().isoformat(),
        "notes": "Pesquisa privada, sem licitação ou proposta enviada.",
    })
    post("/workspace/task/add", {**base_post, "label": "Conferir o edital no PNCP"})
    case = get_case(db, TENDER, 1)
    assert case["stage"] == "cotando"
    assert case["pncp_status"] == 4
    assert "sem licitação" in case["notes"]

    assert http.get("/workspace/export.csv").status_code == 200
    assert http.get("/api/workspace").json()["data"][0]["tasks_total"] == 1
    assert http.get("/api/results", params=params).json()["participant_count"] is None
    assert http.get("/api/coverage").json()["data"] == []
    assert "IA desativada" in http.get("/ai", params=params).text
    assert "Comparar fornecedores" in http.get("/quote", params=params).text
    assert "item deserto" in http.get("/monitor").text.lower() or "monitor" in http.get("/monitor").text.lower()

    # Reimportação idempotente não apaga decisão nem altera etapa manual.
    upsert_tender(db, demo_tender(), demo_item())
    assert get_case(db, TENDER, 1)["stage"] == "cotando"
    assert get_quote(db, TENDER, 1)["supplier"] == "Distribuidora Sintética"


def test_authenticated_responses_enforce_private_security_headers(http):
    authenticate(http)
    response = http.get("/api/items")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
