"""PNCP resultados: contratos públicos, nenhuma inferência de licitantes."""
import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.results import (
    ResultFetchError,
    get_result_snapshot,
    init_results,
    parse_decimal4,
    parse_results,
    refresh_item_results,
    result_source_url,
)
from app.security import hash_password
from app.storage import init_db, upsert_tender

CONTROL = "12345678000190-1-000007/2026"
PW = "SenhaResultadosTeste#2026"
SECRET = "session_secret_results_tests_long_enough_2026"


def tender():
    return {
        "id": CONTROL, "cnpj": "12345678000190", "ano": 2026, "sequencial": 7,
        "orgao": "Prefeitura Fictícia", "municipio": "Salto", "uf": "SP",
        "objeto": "Compra de papelaria",
        "data_publicacao": "2026-11-20", "abertura": None, "encerramento": None,
        "link": "https://pncp.gov.br/app/editais/12345678000190/2026/7",
    }


def item():
    return [{
        "numeroItem": 1, "materialOuServico": "M", "descricao": "Papel sulfite",
        "quantidade": 25, "valorTotal": 1500, "situacaoCompraItemId": 2,
    }]


def official_results():
    return {
        "listaResultados": [{
            "numeroItem": 1, "sequencialResultado": 1,
            "quantidadeHomologada": 25.0000,
            "valorUnitarioHomologado": 19.9876,
            "tipoPessoa": "PJ", "niFornecedor": "12345678000190",
            "nomeRazaoSocialFornecedor": "Papelaria Exemplo Ltda",
            "situacaoCompraItemResultadoId": 1,
            "ordemClassificacaoSrp": 1,
            "dataResultado": "2026-11-21",
        }, {
            "numeroItem": 1, "sequencialResultado": 2,
            "quantidadeHomologada": "25.0000",
            "valorUnitarioHomologado": "20.0000",
            "tipoPessoa": "PF", "niFornecedor": "99999999999",
            "nomeRazaoSocialFornecedor": "CPF_PRIVADO_EXEMPLO",
            "situacaoCompraItemResultadoId": 2,
            "dataResultado": "2026-11-22",
        }],
    }


def endpoint():
    return result_source_url("12345678000190", 2026, 7, 1)


def transport(payload=None, status_code=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        assert str(request.url) == endpoint()
        assert request.url.host == "pncp.gov.br"
        return httpx.Response(
            status_code, json=payload if payload is not None else official_results()
        )
    return httpx.MockTransport(handler)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "results.sqlite")
    init_db(path)
    init_results(path)
    upsert_tender(path, tender(), item())
    return path


@pytest.fixture
def client(db):
    settings = Settings(
        username="admin",
        password_hash=hash_password(PW, b"1234567890abcdef"),
        session_secret=SECRET, db_path=db, secure_cookies=False,
    )
    with TestClient(create_app(settings)) as http:
        yield http


def login(client):
    html = client.get("/login").text
    token = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    result = client.post("/login", data={
        "csrf": token, "username": "admin", "password": PW,
    }, follow_redirects=False)
    assert result.status_code == 303


def csrf(client, url="/results?tender_id=12345678000190-1-000007%2F2026&numero=1"):
    page = client.get(url)
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_fixed_https_endpoint_only():
    assert endpoint() == (
        "https://pncp.gov.br/api/pncp/v1/orgaos/12345678000190/"
        "compras/2026/7/itens/1/resultados"
    )
    with pytest.raises(ResultFetchError):
        result_source_url("../evil.com", 2026, 7, 1)
    with pytest.raises(ResultFetchError):
        result_source_url("12345678000190", 2026, 0, 1)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "1000000000001", "4.00001", True, {}])
def test_decimal_rejects_invalid_or_overprecise(bad):
    with pytest.raises(ResultFetchError):
        parse_decimal4(bad)


def test_decimal_retains_four_digit_precision():
    assert parse_decimal4(Decimal("3.1234")) == "3.1234"
    assert parse_decimal4("0.0001") == "0.0001"
    assert parse_decimal4(None) is None


@pytest.mark.parametrize("payload", [
    None, [], {}, {"data": []},
    {"listaResultados": [None]},
    {"listaResultados": [{"numeroItem": 1, "sequencialResultado": 0}]},
    {"listaResultados": [{"numeroItem": 99, "sequencialResultado": 1}]},
    {"listaResultados": [{"numeroItem": 1, "sequencialResultado": 1,
                          "valorUnitarioHomologado": "NaN"}]},
    {"listaResultados": [{"numeroItem": 1, "sequencialResultado": 1},
                         {"numeroItem": 1, "sequencialResultado": 1}]},
])
def test_response_validation_fail_closed(payload):
    with pytest.raises(ResultFetchError):
        parse_results(payload, 1)


def test_valid_result_records_hide_personal_ids(db):
    observed = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    seen = []
    result = asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport(seen=seen), now=observed,
    ))
    assert len(seen) == 1
    assert result["result_records"] == 2
    assert result["participant_count"] is None
    assert result["participant_count_source"] == "não fornecido por este endpoint"
    first, second = result["results"]
    assert first["supplier"] == "Papelaria Exemplo Ltda"
    assert first["unit_price"] == "19.9876"
    assert first["quantity"] == "25.0000"
    assert first["status"] == 1
    assert second["supplier"] == "Pessoa física (identificação omitida)"
    assert second["status"] == 2
    assert "CPF_PRIVADO_EXEMPLO" not in str(result)
    assert "99999999999" not in str(result)


def test_reimport_does_not_remove_result_snapshot(db):
    asyncio.run(refresh_item_results(db, CONTROL, 1, transport=transport()))
    upsert_tender(db, tender(), item())
    assert get_result_snapshot(db, CONTROL, 1)["result_records"] == 2


def test_second_request_is_throttled_without_network(db):
    first = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport(), now=first,
    ))
    seen = []
    with pytest.raises(ResultFetchError) as exc:
        asyncio.run(refresh_item_results(
            db, CONTROL, 1, transport=transport(seen=seen),
            now=first + timedelta(seconds=10),
        ))
    assert exc.value.status_code == 429
    assert not seen
    assert get_result_snapshot(db, CONTROL, 1)["result_records"] == 2


def test_200_empty_is_not_404_or_participant_zero(db):
    result = asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport({"listaResultados": []}),
    ))
    assert result["result_records"] == 0
    assert result["participant_count"] is None
    assert result["observation"]["state"] == "empty"


def test_503_preserves_last_good_snapshot(db):
    start = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport(), now=start,
    ))
    with pytest.raises(ResultFetchError):
        asyncio.run(refresh_item_results(
            db, CONTROL, 1, transport=transport(status_code=503),
            now=start + timedelta(seconds=75),
        ))
    current = get_result_snapshot(db, CONTROL, 1)
    assert current["result_records"] == 2
    assert current["observation"]["state"] == "error"
    assert "não disponibilizou" in current["observation"]["error_message"]


def test_malformed_new_payload_preserves_last_good_snapshot(db):
    start = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport(), now=start,
    ))
    bad = {"listaResultados": [{"numeroItem": 2, "sequencialResultado": 1}]}
    with pytest.raises(ResultFetchError):
        asyncio.run(refresh_item_results(
            db, CONTROL, 1, transport=transport(bad),
            now=start + timedelta(seconds=80),
        ))
    current = get_result_snapshot(db, CONTROL, 1)
    assert current["result_records"] == 2
    assert current["observation"]["state"] == "error"


def test_http_404_does_not_claim_zero_participants(db):
    with pytest.raises(ResultFetchError) as exc:
        asyncio.run(refresh_item_results(
            db, CONTROL, 1, transport=transport(status_code=404),
        ))
    assert exc.value.status_code == 503
    current = get_result_snapshot(db, CONTROL, 1)
    assert current["observation"]["state"] == "error"
    assert current["participant_count"] is None


def test_requires_auth_csrf_and_valid_item(client):
    path = "/results?tender_id=12345678000190-1-000007%2F2026&numero=1"
    assert client.get(path, follow_redirects=False).status_code == 303
    assert client.get("/api/results", params={"tender_id": CONTROL, "numero": 1}).status_code == 401
    assert client.post("/results/refresh", data={}, follow_redirects=False).status_code == 303
    login(client)
    page = client.get(path)
    assert page.status_code == 200
    assert "resultados armazenados" in page.text
    assert "Ainda não consultado" in page.text
    assert client.get("/results", params={"tender_id": "missing", "numero": 1}).status_code == 404
    assert client.post("/results/refresh", data={
        "csrf": "invalid", "tender_id": CONTROL, "numero": 1,
    }).status_code == 403
    response = client.get("/api/results", params={"tender_id": CONTROL, "numero": 1})
    assert response.json()["participant_count"] is None
    assert response.headers["cache-control"] == "no-store"


def test_authenticated_refresh_uses_mock_without_real_network(client, db, monkeypatch):
    import app.main as controller

    async def fake_refresh(path, tender_id, number, **kwargs):
        return await refresh_item_results(
            path, tender_id, number, transport=transport(),
        )
    monkeypatch.setattr(controller, "refresh_item_results", fake_refresh)
    login(client)
    result = client.post("/results/refresh", data={
        "csrf": csrf(client), "tender_id": CONTROL, "numero": 1,
    }, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"].startswith("/results?")
    page = client.get(result.headers["location"])
    assert "Papelaria Exemplo Ltda" in page.text
    assert "19.9876" in page.text
    assert "Pessoa física (identificação omitida)" in page.text
    assert "CPF_PRIVADO_EXEMPLO" not in page.text
    assert "número de licitantes" not in page.text.lower() or "não fornece" in page.text.lower()


def test_supplier_name_escaped_in_html(client, db):
    results = official_results()
    results["listaResultados"][0]["nomeRazaoSocialFornecedor"] = "<img src=x onerror=alert(1)>"
    asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport(results),
    ))
    login(client)
    page = client.get("/results", params={"tender_id": CONTROL, "numero": 1})
    assert "&lt;img src=x onerror=alert(1)&gt;" in page.text
    assert "<img src=x onerror=alert(1)>" not in page.text


def test_no_results_from_nonexistent_item(db):
    with pytest.raises(ResultFetchError) as exc:
        asyncio.run(refresh_item_results(db, CONTROL, 99, transport=transport()))
    assert exc.value.status_code == 404


def test_status_cancelled_not_treated_as_winner(db):
    result = asyncio.run(refresh_item_results(
        db, CONTROL, 1, transport=transport(),
    ))
    assert result["results"][1]["status"] == 2
    assert result["results"][1]["supplier"] == "Pessoa física (identificação omitida)"
