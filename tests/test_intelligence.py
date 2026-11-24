"""Motor de lucro sem invenção de custos, cotação segura e recuperação de dados."""
import re
import sqlite3
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.intelligence import (
    CATEGORIES,
    analyze,
    classify,
    item_fingerprint,
    validate_quote,
)
from app.main import Settings, create_app
from app.quotes import get_item, get_quote, init_quotes, save_quote
from app.security import hash_password
from app.storage import connection, init_db, list_items, upsert_tender


def sample_tender():
    return {
        "id": "12345678000190-1-000007/2026",
        "cnpj": "12345678000190", "ano": 2026, "sequencial": 7,
        "orgao": "Prefeitura de Testes", "municipio": "Indaiatuba", "uf": "SP",
        "objeto": "Materiais de consumo", "data_publicacao": "2026-11-23",
        "abertura": "2026-11-24", "encerramento": "2026-11-28",
        "link": "https://pncp.gov.br/app/editais/12345678000190/2026/7",
    }


def sample_item(quantity=10, price=2000, status=1):
    return {
        "numeroItem": 1, "materialOuServico": "M",
        "descricao": "Caixa de papel A4", "quantidade": quantity,
        "valorTotal": price, "situacaoCompraItemId": status,
    }


def sample_quote():
    return {
        "supplier": "Distribuidor informado pelo usuário",
        "unit_cost": "100.00", "freight": "100.00",
        "packaging": "20.00", "other": "30.00",
        "risk_reserve": "50.00", "tax_percent": "10.00",
        "target_margin": "20.00",
    }


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "licitacoes.sqlite")
    init_db(path)
    init_quotes(path)
    upsert_tender(path, sample_tender(), [sample_item()])
    return path


@pytest.fixture
def client(db_path):
    settings = Settings(
        username="single-owner", password_hash=hash_password(
            "SenhaDeTestesSuficiente#2026", b"1234567890abcdef"
        ),
        session_secret="S" * 48, db_path=db_path, secure_cookies=False,
    )
    with TestClient(create_app(settings)) as user:
        yield user


def login(client):
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    answer = client.post("/login", data={
        "csrf": csrf, "username": "single-owner",
        "password": "SenhaDeTestesSuficiente#2026",
    }, follow_redirects=False)
    assert answer.status_code == 303


def csrf_from_page(page):
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_categories_are_explicitly_heuristic():
    assert classify("PAPEL A4, resma 500 folhas") == "papelaria"
    assert classify("Solução de limpeza, sabão em pó") == "limpeza"
    assert classify("Garrafa térmica") == "copa"
    assert classify("Capacete de segurança") == "epi"
    assert classify("objeto muito específico") == "outros"
    assert CATEGORIES["outros"] == "Outros / a verificar"


def test_profitability_formula_and_rounding(db_path):
    tender = sample_tender()
    item = get_item(db_path, tender["id"], 1)
    assert item is not None
    quote = validate_quote(sample_quote())
    save_quote(db_path, tender["id"], 1, quote)
    persisted = get_quote(db_path, tender["id"], 1)
    result = analyze(item, persisted)
    assert result["status"] == "potencial_financeiro"
    assert result["category"] == "papelaria"
    assert result["total_cost"] == "1200.00"
    assert result["break_even"] == "1333.34"
    assert result["min_viable"] == "1714.29"
    assert result["profit_reference"] == "600.00"
    assert result["margin_reference"] == "30.00"
    assert result["surplus"] == "285.71"
    assert Decimal(result["min_viable"]) * Decimal("0.70") >= Decimal("1200.00")


def test_reference_below_target_not_called_profitable(db_path):
    tender = sample_tender()
    upsert_tender(db_path, tender, [sample_item(price=1600)])
    save_quote(db_path, tender["id"], 1, validate_quote(sample_quote()))
    result = analyze(get_item(db_path, tender["id"], 1),
                     get_quote(db_path, tender["id"], 1))
    assert result["status"] == "margem_insuficiente"
    assert result["profit_reference"] == "240.00"
    assert result["margin_reference"] == "15.00"


def test_missing_budget_never_invents_reference(db_path):
    tender = sample_tender()
    upsert_tender(db_path, tender, [sample_item(price=None)])
    quote = validate_quote(sample_quote())
    save_quote(db_path, tender["id"], 1, quote)
    result = analyze(get_item(db_path, tender["id"], 1),
                     get_quote(db_path, tender["id"], 1))
    assert result["status"] == "sem_referencia"
    assert result["reference"] is None
    assert result["profit_reference"] is None
    assert result["min_viable"] == "1714.29"


def test_quote_survives_reimport_and_flags_changed_quantity(db_path):
    tender = sample_tender()
    values = validate_quote(sample_quote())
    save_quote(db_path, tender["id"], 1, values)
    old = get_quote(db_path, tender["id"], 1)
    upsert_tender(db_path, tender, [sample_item()])
    assert get_quote(db_path, tender["id"], 1)["item_fingerprint"] == old["item_fingerprint"]
    assert analyze(get_item(db_path, tender["id"], 1), get_quote(db_path, tender["id"], 1))["status"] == "potencial_financeiro"
    upsert_tender(db_path, tender, [sample_item(quantity=11)])
    latest = get_quote(db_path, tender["id"], 1)
    assert latest is not None
    assert analyze(get_item(db_path, tender["id"], 1), latest)["status"] == "desatualizada"
    assert latest["item_fingerprint"] == old["item_fingerprint"]
    assert latest["item_fingerprint"] != item_fingerprint("Caixa de papel A4", 11)


@pytest.mark.parametrize("field,value", [
    ("unit_cost", "-1"), ("unit_cost", "NaN"), ("unit_cost", "Infinity"),
    ("unit_cost", "0"), ("unit_cost", "1.999"), ("freight", "-0.01"),
    ("packaging", "1e300"), ("tax_percent", "99.99"),
    ("target_margin", "99.99"),
])
def test_invalid_quote_values_rejected(field, value):
    entry = sample_quote()
    entry[field] = value
    with pytest.raises(ValueError):
        validate_quote(entry)


def test_margin_plus_taxes_cannot_reach_100():
    quote = sample_quote()
    quote["tax_percent"] = "30.00"
    quote["target_margin"] = "70.00"
    with pytest.raises(ValueError):
        validate_quote(quote)


def test_authenticated_quote_route_and_post_csrf(client, db_path):
    tender_id = sample_tender()["id"]
    path = "/quote?tender_id=" + tender_id.replace("/", "%2F") + "&numero=1"
    assert client.get(path, follow_redirects=False).status_code == 303
    assert client.get("/api/items").status_code == 401
    assert client.post("/quote", data={"tender_id": tender_id, "numero": "1"},
                       follow_redirects=False).status_code == 303
    login(client)
    assert client.get(path).status_code == 200
    assert client.get("/quote?tender_id=unknown&numero=1").status_code == 404
    assert client.post("/quote", data={"tender_id": tender_id, "numero": "1",
                                     "csrf": "invalid"}).status_code == 403
    form = sample_quote()
    form.update({"tender_id": tender_id, "numero": "1",
                 "csrf": csrf_from_page(client.get(path))})
    saved = client.post("/quote", data=form, follow_redirects=False)
    assert saved.status_code == 303
    assert saved.headers["location"].startswith("/quote?")
    result = client.get(path)
    assert "R$ 1714.29" in result.text
    assert "R$ 600.00" in result.text
    assert "Potencial financeiro condicionado" in result.text
    assert client.get("/api/items").json()["data"][0]["analysis"]["status"] == "potencial_financeiro"
    assert get_quote(db_path, tender_id, 1)["supplier"] == form["supplier"]


def test_bad_form_rejected_without_overwriting_previous_quote(client, db_path):
    tender_id = sample_tender()["id"]
    path = "/quote?tender_id=" + tender_id.replace("/", "%2F") + "&numero=1"
    login(client)
    original = sample_quote()
    original.update({"csrf": csrf_from_page(client.get(path)),
                     "tender_id": tender_id, "numero": "1"})
    assert client.post("/quote", data=original, follow_redirects=False).status_code == 303
    invalid = {**original, "unit_cost": "-100"}
    response = client.post("/quote", data=invalid)
    assert response.status_code == 422
    assert "valor fora dos limites" in response.text
    assert get_quote(db_path, tender_id, 1)["unit_cost"] == "100.00"


def test_supplier_html_escaped_in_quote_page(client, db_path):
    tender_id = sample_tender()["id"]
    path = "/quote?tender_id=" + tender_id.replace("/", "%2F") + "&numero=1"
    login(client)
    unsafe = sample_quote()
    unsafe["supplier"] = "<script>alert(7)</script>"
    unsafe.update({"csrf": csrf_from_page(client.get(path)),
                   "tender_id": tender_id, "numero": "1"})
    assert client.post("/quote", data=unsafe, follow_redirects=False).status_code == 303
    page = client.get(path)
    assert "<script>alert(7)</script>" not in page.text
    assert "&lt;script&gt;" in page.text


def test_category_filter_uses_full_dataset_and_validates_input(client, db_path):
    tender_id = sample_tender()["id"]
    assert list_items(db_path, category="papelaria")[1] == 1
    assert list_items(db_path, category="epi")[1] == 0
    login(client)
    assert client.get("/?category=papelaria").status_code == 200
    assert "Caixa de papel A4" in client.get("/?category=papelaria").text
    assert client.get("/api/items?category=outros").json()["total"] == 0
    assert client.get("/?category=nao_existe").status_code == 422
    assert client.get("/api/items?category=nao_existe").status_code == 422
    assert get_item(db_path, tender_id, 1)["numero"] == 1


def test_no_quote_means_no_financial_scoring(client):
    login(client)
    entry = client.get("/api/items").json()["data"][0]
    assert entry["analysis"]["status"] == "sem_cotacao"
    assert entry["analysis"]["profit_reference"] is None
    assert entry["analysis"]["min_viable"] is None
    assert entry["analysis"]["category_label"] == "Papelaria e escritório"


@pytest.mark.parametrize("published", ["0.001", "1e100", "-50", "NaN"])
def test_impossible_official_reference_does_not_crash_or_invent_profit(db_path, published):
    tender_id = sample_tender()["id"]
    quote = validate_quote(sample_quote())
    save_quote(db_path, tender_id, 1, quote)
    item = get_item(db_path, tender_id, 1)
    assert item is not None
    item["valor_total"] = published
    result = analyze(item, get_quote(db_path, tender_id, 1))
    assert result["status"] == "sem_referencia"
    assert result["profit_reference"] is None
    assert result["reference"] is None


def test_sqlite_connection_is_closed_and_failed_writes_are_rolled_back(db_path):
    with connection(db_path) as database:
        initial = database.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
    with pytest.raises(sqlite3.ProgrammingError):
        database.execute("SELECT 1")
    with pytest.raises(RuntimeError), connection(db_path) as database:
        database.execute("""
            INSERT INTO sync_runs
            (started_at,fetched,material_items,errors,details)
            VALUES ('2026-11-23',1,1,0,'synthetic')
        """)
        raise RuntimeError("simular falha após alteração")
    with connection(db_path) as database:
        final = database.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
    assert final == initial
