"""Provas de segurança e matemática para cotações privadas de fornecedores."""
from datetime import date
import re

import pytest
from fastapi.testclient import TestClient

from app.intelligence import analyze
from app.main import Settings, create_app
from app.quotes import get_item, get_quote, init_quotes
from app.security import hash_password
from app.storage import init_db, upsert_tender
from app.suppliers import (
    SupplierError,
    add_offer,
    compare_offers,
    get_offers,
    init_suppliers,
    promote_offer,
    remove_offer,
    validate_source_date,
    validate_source_url,
)

PW = "SenhaFornecedoresTeste#2026"
SECRET = "suppliers_long_secret_string_2026_never_reuse"
CONTROL = "12345678000190-1-000007/2026"
SECOND = "12345678000190-1-000008/2026"


def tender(control=CONTROL, number=7):
    return {
        "id": control, "cnpj": "12345678000190", "ano": 2026,
        "sequencial": number, "orgao": "Prefeitura Fictícia",
        "municipio": "Salto", "uf": "SP", "objeto": "Material de papelaria",
        "data_publicacao": "2026-11-20", "abertura": None, "encerramento": None,
        "link": f"https://pncp.gov.br/app/editais/12345678000190/2026/{number}",
    }


def items(name="Papel sulfite A4 pacote 500 folhas", quantity=10):
    return [{
        "numeroItem": 1, "materialOuServico": "M", "descricao": name,
        "situacaoCompraItemId": 1, "quantidade": quantity, "valorTotal": 300,
    }]


def fields(supplier="Distribuidora Sul", cost="12.00", freight="10.00"):
    return {
        "supplier": supplier, "unit_cost": cost, "freight": freight,
        "packaging": "0.00", "other": "0.00", "risk_reserve": "0.00",
        "tax_percent": "10.00", "target_margin": "20.00",
    }


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "suppliers.sqlite3")
    init_db(path)
    init_quotes(path)
    init_suppliers(path)
    upsert_tender(path, tender(), items())
    return path


@pytest.fixture
def client(db):
    settings = Settings(
        username="admin", password_hash=hash_password(PW, b"1234567890abcdef"),
        session_secret=SECRET, db_path=db, secure_cookies=False,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    result = client.post("/login", data={
        "csrf": token, "username": "admin", "password": PW,
    }, follow_redirects=False)
    assert result.status_code == 303


def csrf(client, url=None):
    url = url or "/suppliers?tender_id=" + CONTROL.replace("/", "%2F") + "&numero=1"
    page = client.get(url)
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def add(db, supplier="Distribuidora Sul", cost="12.00", freight="10.00",
        source="https://example.com/produto"):
    return add_offer(
        db, CONTROL, 1, fields(supplier, cost, freight),
        date.today().isoformat(), source, "Frete informado manualmente",
    )


def test_comparison_uses_existing_decimal_engine_without_auto_promote(db):
    expensive = add(db, "Fornecedor A", "13.00", "20.00")
    cheap = add(db, "Fornecedor B", "9.00", "30.00")
    report = compare_offers(db, get_item(db, CONTROL, 1))
    assert [x["id"] for x in report] == [cheap, expensive]
    # Prova independente: preço total = 9 x 10 + 30 = 120.
    assert report[0]["analysis"]["total_cost"] == "120.00"
    # Piso com 10% tributos e 20% margem: ceil(120 / 0.70, 2) = 171.43.
    assert report[0]["analysis"]["min_viable"] == "171.43"
    assert report[0]["analysis"]["reference"] == "300.00"
    assert report[0]["analysis"]["profit_reference"] == "150.00"
    assert not any(x["active"] for x in report)
    assert get_quote(db, CONTROL, 1) is None
    promote_offer(db, CONTROL, 1, cheap)
    main = get_quote(db, CONTROL, 1)
    assert main["supplier"] == "Fornecedor B"
    assert analyze(get_item(db, CONTROL, 1), main)["total_cost"] == "120.00"
    assert compare_offers(db, get_item(db, CONTROL, 1))[0]["active"]


def test_cannot_promote_offer_of_another_item(db):
    upsert_tender(db, tender(SECOND, 8), items())
    offer_id = add(db)
    with pytest.raises(SupplierError) as error:
        promote_offer(db, SECOND, 1, offer_id)
    assert error.value.status_code == 404
    assert get_quote(db, SECOND, 1) is None
    assert len(get_offers(db, CONTROL, 1)) == 1


def test_stale_offer_blocks_promotion_and_keeps_active_quote(db):
    keep = add(db, "Vendedor válido", "10.00", "0.00")
    promote_offer(db, CONTROL, 1, keep)
    earlier = get_quote(db, CONTROL, 1).copy()
    other = add(db, "Novo vendedor", "8.00", "0.00")
    upsert_tender(db, tender(), items(quantity=20))
    comparison = compare_offers(db, get_item(db, CONTROL, 1))
    assert all(x["analysis"]["status"] == "desatualizada" for x in comparison)
    assert all(x["analysis"]["min_viable"] is None for x in comparison)
    with pytest.raises(SupplierError, match="desatualizada"):
        promote_offer(db, CONTROL, 1, other)
    assert get_quote(db, CONTROL, 1)["supplier"] == earlier["supplier"]
    assert analyze(get_item(db, CONTROL, 1), get_quote(db, CONTROL, 1))["status"] == "desatualizada"


def test_reimport_preserves_valid_offers_and_selection(db):
    oid = add(db)
    promote_offer(db, CONTROL, 1, oid)
    upsert_tender(db, tender(), items())
    assert len(get_offers(db, CONTROL, 1)) == 1
    assert compare_offers(db, get_item(db, CONTROL, 1))[0]["active"]
    assert get_quote(db, CONTROL, 1)["supplier"] == "Distribuidora Sul"


def test_remove_is_item_scoped_and_does_not_delete_active_baseline(db):
    oid = add(db)
    upsert_tender(db, tender(SECOND, 8), items())
    promote_offer(db, CONTROL, 1, oid)
    remove_offer(db, SECOND, 1, oid)
    assert len(get_offers(db, CONTROL, 1)) == 1
    remove_offer(db, CONTROL, 1, oid)
    assert not get_offers(db, CONTROL, 1)
    assert get_quote(db, CONTROL, 1)["supplier"] == "Distribuidora Sul"


def test_limit_twelve_and_invalid_financial_input(db):
    for index in range(12):
        add(db, f"Vendedor {index}")
    assert len(get_offers(db, CONTROL, 1)) == 12
    with pytest.raises(SupplierError, match="12 cotações"):
        add(db, "Vendedor extra")
    with pytest.raises(SupplierError):
        add_offer(db, CONTROL, 1, fields(cost="nan"), date.today().isoformat())
    with pytest.raises(SupplierError):
        add_offer(db, CONTROL, 1, fields(cost="-1.00"), date.today().isoformat())
    assert len(get_offers(db, CONTROL, 1)) == 12


@pytest.mark.parametrize("unsafe", [
    "http://example.com/item", "https://127.0.0.1/item",
    "https://localhost/item", "https://example.local/item",
    "https://admin:pass@example.com/", "https://user@example.com/path",
    "https://example.com:8443/item", "https://example.com/a b",
    "javascript:alert(1)", "file:///etc/passwd",
    "https://example.test/a", "https://example.com/\nInjected: header",
    "//example.com/a", "https://[::1]/",
])
def test_urls_reject_unsafe_or_unverifiable_sources(unsafe):
    with pytest.raises(SupplierError):
        validate_source_url(unsafe)


def test_public_https_urls_are_display_only():
    assert validate_source_url("https://example.com/produto?q=foo") == (
        "https://example.com/produto?q=foo"
    )
    assert validate_source_url("") == ""
    with pytest.raises(SupplierError):
        validate_source_url("https://example.com/" + "x" * 600)


def test_date_cannot_be_in_future_or_invalid():
    assert validate_source_date(date.today().isoformat()) == date.today().isoformat()
    with pytest.raises(SupplierError):
        validate_source_date("2020-12-31")
    with pytest.raises(SupplierError):
        validate_source_date("2099-01-01")
    with pytest.raises(SupplierError):
        validate_source_date("2026-02-30")


def test_no_cotations_for_unknown_item(db):
    with pytest.raises(SupplierError) as error:
        add_offer(db, "unknown", 1, fields(), date.today().isoformat())
    assert error.value.status_code == 404


def test_auth_csrf_and_only_manual_activation(client, db):
    params = {"tender_id": CONTROL, "numero": 1}
    assert client.get("/suppliers", params=params, follow_redirects=False).status_code == 303
    assert client.get("/api/suppliers", params=params).status_code == 401
    assert client.post("/suppliers/add", data={}, follow_redirects=False).status_code == 303
    login(client)
    token = csrf(client)
    assert "Comparação registrada" in client.get("/suppliers", params=params).text
    for url in ("/suppliers/add", "/suppliers/promote", "/suppliers/remove"):
        assert client.post(url, data={"csrf": "invalid"}).status_code == 403
    payload = {**fields(), "csrf": token, "tender_id": CONTROL, "numero": "1",
               "observed_on": date.today().isoformat(),
               "source_url": "https://example.com/item", "note": "Fonte declarada"}
    created = client.post("/suppliers/add", data=payload, follow_redirects=False)
    assert created.status_code == 303
    assert get_quote(db, CONTROL, 1) is None
    state = client.get("/api/suppliers", params=params)
    assert state.headers["cache-control"] == "no-store"
    assert len(state.json()["data"]) == 1
    offer_id = state.json()["data"][0]["id"]
    selected = client.post("/suppliers/promote", data={
        "csrf": token, "tender_id": CONTROL, "numero": 1, "offer_id": offer_id,
    }, follow_redirects=False)
    assert selected.status_code == 303
    assert get_quote(db, CONTROL, 1)["supplier"] == "Distribuidora Sul"
    assert "Distribuidora Sul" in client.get("/quote", params=params).text
    assert client.get("/api/suppliers", params=params).json()["data"][0]["active"]
    assert "Comparar fornecedores" in client.get("/").text


def test_html_escaping_and_invalid_offer_not_saved(client, db):
    login(client)
    bad_name = "<img src=x onerror=alert(1)>"
    payload = {**fields(supplier=bad_name), "csrf": csrf(client),
               "tender_id": CONTROL, "numero": 1,
               "observed_on": date.today().isoformat(),
               "source_url": "https://example.com/supplier",
               "note": "<script>alert(1)</script>"}
    assert client.post("/suppliers/add", data=payload, follow_redirects=False).status_code == 303
    html = client.get("/suppliers", params={"tender_id": CONTROL, "numero": 1}).text
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<script>alert(1)</script>" not in html
    malicious = payload | {"source_url": "javascript:alert(1)"}
    assert client.post("/suppliers/add", data=malicious).status_code == 422
    assert len(get_offers(db, CONTROL, 1)) == 1


def test_source_is_user_entered_and_not_verified_remotely(db):
    oid = add(db, source="https://example.com/oferta")
    offer = get_offers(db, CONTROL, 1)[0]
    assert offer["id"] == oid
    assert offer["source_url"] == "https://example.com/oferta"
    assert offer["observed_on"] == date.today().isoformat()
    assert len(compare_offers(db, get_item(db, CONTROL, 1))) == 1
