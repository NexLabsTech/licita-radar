"""Invariantes do monitor local: dedupe, fonte, alerta seguro e CSRF."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.monitor import (
    candidate_eligible,
    change_favorite,
    create_rule,
    delete_rule,
    mark_read,
    monitor_data,
    normalize_description,
    unread_count,
    watched_keys,
)
from app.security import hash_password
from app.storage import init_db, upsert_tender

PW = "SenhaMonitorTeste#2026"
HASH = hash_password(PW, b"1234567890abcdef")
SECRET = "my_test_session_secret_do_not_use_real_2026"
DESC = "Papel sulfite A4 pacote 500 folhas"


def tender(n=1, cnpj="12345678000190", published="2026-11-21", uf="SP"):
    return {
        "id": f"{cnpj}-1-{n:06d}/2026",
        "cnpj": cnpj, "ano": 2026, "sequencial": n,
        "orgao": "Prefeitura Fictícia", "municipio": "Salto",
        "uf": uf, "objeto": "Materiais de escritório",
        "data_publicacao": published, "abertura": None, "encerramento": None,
        "link": f"https://pncp.gov.br/app/editais/{cnpj}/2026/{n}",
    }


def item(description=DESC, status=4, quantity=25, n=1):
    return {
        "numeroItem": n, "materialOuServico": "M",
        "descricao": description, "situacaoCompraItemId": status,
        "quantidade": quantity, "valorTotal": 3500.00,
    }


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "monitor.sqlite")
    init_db(path)
    return path


@pytest.fixture
def client(db):
    settings = Settings(
        username="admin", password_hash=HASH, session_secret=SECRET,
        db_path=db, secure_cookies=False,
    )
    with TestClient(create_app(settings)) as http:
        yield http


def login(http):
    page = http.get("/login")
    assert page.status_code == 200
    match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert match
    response = http.post("/login", data={
        "csrf": match.group(1), "username": "admin", "password": PW,
    }, follow_redirects=False)
    assert response.status_code == 303


def csrf(http, page="/monitor"):
    response = http.get(page)
    assert response.status_code == 200
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_rules_match_new_and_existing_items_without_duplicates(db):
    base = tender()
    upsert_tender(db, base, [item()])
    rule_id = create_rule(db, "PAPEL SULFITE", "SP", 4, "papelaria")
    assert rule_id == create_rule(db, "PAPEL SULFITE", "SP", 4, "papelaria")
    first = monitor_data(db)
    assert len(first["rules"]) == 1
    assert len(first["alerts"]) == 1
    assert first["alerts"][0]["kind"] == "rule_match"
    assert first["unread"] == 1
    upsert_tender(db, base, [item()])
    assert monitor_data(db)["unread"] == 1
    # A origem antiga não é emitida como nova licitação após reimportação.
    new = tender(2, published="2026-11-22")
    upsert_tender(db, new, [item(status=4)])
    assert monitor_data(db)["unread"] == 2
    mark_read(db, first["alerts"][0]["id"])
    mark_read(db, first["alerts"][0]["id"])
    assert unread_count(db) == 1
    delete_rule(db, rule_id)
    assert not monitor_data(db)["rules"]
    assert monitor_data(db)["unread"] == 1  # Histórico de evidência preservado


def test_favorite_survives_reimport_and_observes_status_delta(db):
    t = tender()
    upsert_tender(db, t, [item(status=1)])
    change_favorite(db, t["id"], 1, True)
    assert watched_keys(db, [{"tender_id": t["id"], "numero": 1}]) == {(t["id"], 1)}
    upsert_tender(db, t, [item(status=4)])
    alerts = monitor_data(db)["alerts"]
    assert len(alerts) == 1 and alerts[0]["kind"] == "watched_change"
    assert "1 → 4" in alerts[0]["detail"]
    upsert_tender(db, t, [item(status=4)])
    assert len(monitor_data(db)["alerts"]) == 1
    assert len(monitor_data(db)["favorites"]) == 1
    change_favorite(db, t["id"], 1, False)
    assert not monitor_data(db)["favorites"]


def test_relisting_requires_evidence_and_has_two_pncp_links(db):
    past = tender(1, published="2026-11-21")
    new = tender(2, published="2026-11-23")
    upsert_tender(db, past, [item(status=4)])
    upsert_tender(db, new, [item(status=1)])
    alerts = monitor_data(db)["alerts"]
    candidates = [a for a in alerts if a["kind"] == "candidate_republication"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["tender_id"] == new["id"]
    assert candidate["source_tender_id"] == past["id"]
    assert candidate["link"] == new["link"]
    assert candidate["source_link"] == past["link"]
    assert "não prova vínculo" in candidate["detail"]
    upsert_tender(db, new, [item(status=1)])
    assert len(monitor_data(db)["alerts"]) == 1


@pytest.mark.parametrize("difference", [
    {"cnpj": "99000111000112"},
    {"quantity": 26},
    {"description": "Papel toalha pacote 500 folhas"},
    {"published": "2026-11-20"},
    {"status": 5},
])
def test_no_false_candidate_when_source_does_not_match(db, difference):
    past = tender(1, published="2026-11-21")
    new = tender(2, published=difference.get("published", "2026-11-23"),
                 cnpj=difference.get("cnpj", past["cnpj"]))
    upsert_tender(db, past, [item(status=4)])
    upsert_tender(db, new, [item(
        description=difference.get("description", DESC),
        quantity=difference.get("quantity", 25),
        status=difference.get("status", 1),
    )])
    assert not [a for a in monitor_data(db)["alerts"]
                if a["kind"] == "candidate_republication"]


def test_cannot_infer_relisting_from_short_or_unknown_quantity(db):
    assert not candidate_eligible("Caneta azul")
    assert normalize_description("PAPÉL  SÚLFITE!") == "papel sulfite"
    upsert_tender(db, tender(), [item(description="Caneta azul", quantity=30)])
    upsert_tender(db, tender(2, published="2026-11-23"),
                  [item(description="Caneta azul", status=1, quantity=30)])
    assert monitor_data(db)["unread"] == 0


@pytest.mark.parametrize("params", [
    ("x", "", 0, ""),
    ("a" * 81, "", 0, ""),
    ("papel", "SÃO", 0, ""),
    ("papel", "SP", 3, ""),
    ("papel", "SP", 1, "unauthorized"),
])
def test_rules_reject_unbounded_or_invalid_settings(db, params):
    with pytest.raises(ValueError):
        create_rule(db, *params)


def test_rules_limited_to_20(db):
    for index in range(20):
        create_rule(db, f"mercadoria-{index}")
    assert len(monitor_data(db)["rules"]) == 20
    with pytest.raises(ValueError, match="20 regras"):
        create_rule(db, "mercadoria-20")


def test_favorites_require_existing_item_and_reject_bad_action(db):
    with pytest.raises(ValueError):
        change_favorite(db, "não-existe", 1, True)
    with pytest.raises(ValueError):
        change_favorite(db, "x", 0, True)


def test_monitor_requires_login_and_csrf_for_every_write(client, db):
    entry = tender()
    upsert_tender(db, entry, [item()])
    assert client.get("/monitor", follow_redirects=False).status_code == 303
    assert client.get("/api/monitor").status_code == 401
    assert client.post("/monitor/rule", data={},
                       follow_redirects=False).status_code == 303
    login(client)
    response = client.get("/monitor")
    assert "Regras de oportunidade" in response.text
    assert "Favoritos" in response.text
    assert client.get("/api/monitor").headers["cache-control"] == "no-store"
    wrong = {
        "csrf": "invalid", "keyword": "papel", "uf": "SP", "status": "4",
    }
    for route in ("rule", "rule/delete", "favorite", "read"):
        assert client.post("/monitor/" + route, data=wrong).status_code == 403

    valid_csrf = csrf(client)
    saved = client.post("/monitor/rule", data={
        "csrf": valid_csrf, "keyword": "papel sulfite",
        "uf": "SP", "status": "4", "category": "papelaria",
    }, follow_redirects=False)
    assert saved.status_code == 303
    assert saved.headers["location"] == "/monitor"
    assert client.get("/api/monitor").json()["unread"] == 1
    focus = client.get("/monitor", params={"tender_id": entry["id"], "numero": 1})
    assert focus.status_code == 200
    assert "Acompanhar este item" in focus.text

    favorite = client.post("/monitor/favorite", data={
        "csrf": valid_csrf, "tender_id": entry["id"],
        "numero": "1", "action": "add",
    }, follow_redirects=False)
    assert favorite.status_code == 303
    assert len(client.get("/api/monitor").json()["favorites"]) == 1
    assert "Acompanhando" in client.get("/").text
    assert client.get("/api/items").json()["data"][0]["watched"] is True


def test_monitor_escapes_untrusted_rule_terms(client):
    login(client)
    rule = "<script>alert(1)</script>"
    response = client.post("/monitor/rule", data={
        "csrf": csrf(client), "keyword": rule,
    }, follow_redirects=False)
    assert response.status_code == 303
    html = client.get("/monitor").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_read_api_and_delete_rules_preserve_history(client, db):
    upsert_tender(db, tender(), [item()])
    login(client)
    token = csrf(client)
    client.post("/monitor/rule", data={
        "csrf": token, "keyword": "papel sulfite", "status": 4,
    })
    alert = client.get("/api/monitor").json()["alerts"][0]
    assert not alert["read_at"]
    assert client.post("/monitor/read", data={
        "csrf": token, "id": alert["id"],
    }, follow_redirects=False).status_code == 303
    assert client.get("/api/monitor").json()["unread"] == 0
    rule_id = client.get("/api/monitor").json()["rules"][0]["id"]
    assert client.post("/monitor/rule/delete", data={
        "csrf": token, "id": rule_id,
    }, follow_redirects=False).status_code == 303
    assert not client.get("/api/monitor").json()["rules"]
    assert len(client.get("/api/monitor").json()["alerts"]) == 1


def test_failed_import_does_not_leave_orphan_alerts(db):
    create_rule(db, "papel sulfite")
    t = tender()
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.InterfaceError)):
        # A primeira linha poderia gerar alerta; a segunda falha e tudo volta.
        upsert_tender(db, t, [item(), item(n=2, quantity={"invalid": "object"})])
    assert monitor_data(db)["unread"] == 0
    assert not monitor_data(db)["alerts"]
