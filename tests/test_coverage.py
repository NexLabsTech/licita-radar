"""Coleta PNCP extensível: limites, retomada, API oficial e sem falsas coberturas."""
import asyncio
import re
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.coverage import (
    CoverageError,
    _page_rows,
    coverage_jobs,
    create_job,
    delete_job,
    init_coverage,
    next_step,
)
from app.main import Settings, create_app
from app.security import hash_password
from app.storage import init_db, list_items

PW = "SenhaCoberturaTeste#2026"
SECRET = "coverage_test_session_secret_not_real_2026"
CNPJ = "12345678000190"
DAY = date.today() - timedelta(days=2)
FIRST = DAY.isoformat()
LAST = (DAY + timedelta(days=1)).isoformat()


def tender(number, uf="SP"):
    return {
        "numeroControlePNCP": f"{CNPJ}-1-{number:06d}/{DAY.year}",
        "anoCompra": DAY.year, "sequencialCompra": number,
        "orgaoEntidade": {"cnpj": CNPJ, "razaoSocial": "Prefeitura Fictícia"},
        "unidadeOrgao": {"ufSigla": uf, "municipioNome": "Cidade Teste"},
        "objetoCompra": "Material de escritório",
        "dataPublicacaoPncp": FIRST,
    }


def item():
    return {
        "itens": [{
            "numeroItem": 1, "materialOuServico": "M",
            "descricao": "Papel sulfite A4 pacote 500 folhas",
            "situacaoCompraItemId": 4, "quantidade": 20, "valorTotal": 500,
        }],
        "totalPaginas": 1,
    }


def mock_transport(page_map, seen=None, uf="SP"):
    def handler(request):
        assert request.url.host == "pncp.gov.br"
        if "/contratacoes/publicacao" in request.url.path:
            page = int(request.url.params["pagina"])
            assert request.url.params["tamanhoPagina"] == "20"
            assert request.url.params["codigoModalidadeContratacao"] == "6"
            assert request.url.params["uf"] == uf
            assert request.url.params["codigoMunicipioIbge"] == "3509502"
            if seen is not None:
                seen.append(("publication", page))
            value = page_map.get(page)
            if value == "503":
                return httpx.Response(503, json={"message": "upstream down"})
            return httpx.Response(200, json=value if value is not None else {
                "data": [], "paginasRestantes": 0,
            })
        if seen is not None:
            seen.append(("items", request.url.path))
        return httpx.Response(200, json=item())
    return httpx.MockTransport(handler)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "coverage.sqlite3")
    init_db(path)
    init_coverage(path)
    return path


@pytest.fixture
def client(db):
    settings = Settings(
        username="admin", password_hash=hash_password(
            PW, b"1234567890abcdef"
        ), session_secret=SECRET, db_path=db, secure_cookies=False,
    )
    with TestClient(create_app(settings)) as web:
        yield web


def login(web):
    page = web.get("/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    result = web.post("/login", data={
        "csrf": token, "username": "admin", "password": PW,
    }, follow_redirects=False)
    assert result.status_code == 303


def csrf(web):
    return re.search(
        r'name="csrf" value="([^"]+)"', web.get("/coverage").text
    ).group(1)


def make(db):
    return create_job(db, DAY, DAY + timedelta(days=1), "SP", 6, "3509502")


def test_first_two_pages_and_recovery_resume(db):
    job_id = make(db)
    assert coverage_jobs(db)[0]["next_page"] == 1
    seen = []
    page_map = {
        1: {"data": [tender(x) for x in range(1, 21)], "paginasRestantes": 2},
        2: {"data": [tender(x) for x in range(21, 41)], "paginasRestantes": 1},
        3: {"data": [tender(41)], "paginasRestantes": 0},
    }
    first = asyncio.run(next_step(
        db, job_id, mock_transport(page_map, seen=seen)
    ))
    assert first["state"] == "paused"
    assert first["next_page"] == 3
    assert first["processed_pages"] == 2
    assert first["fetched"] == 40 and first["material_items"] == 40
    assert len([part for part in seen if part[0] == "publication"]) == 2
    assert list_items(db)[1] == 40

    # Nova chamada, novo processo/instância pode retomar o cursor salvo.
    finished = asyncio.run(next_step(
        db, job_id, mock_transport(page_map, seen=seen)
    ))
    assert finished["state"] == "completed"
    assert finished["next_page"] == 4
    assert finished["processed_pages"] == 3
    assert finished["fetched"] == 41
    assert list_items(db)[1] == 41
    before = len(seen)
    assert asyncio.run(next_step(db, job_id))["state"] == "completed"
    assert len(seen) == before  # nenhuma rede após finalização


def test_failed_next_page_does_not_skip_or_double_count(db):
    job_id = make(db)
    rows = [tender(x) for x in range(1, 21)]
    first = asyncio.run(next_step(db, job_id, mock_transport({
        1: {"data": rows, "paginasRestantes": 1},
        2: "503",
    })))
    assert first["state"] == "error" and first["errors"] == 1
    assert first["next_page"] == 2 and first["fetched"] == 20
    assert list_items(db)[1] == 20
    restored = asyncio.run(next_step(db, job_id, mock_transport({
        2: {"data": [tender(21)], "paginasRestantes": 0},
    })))
    assert restored["state"] == "completed"
    assert restored["fetched"] == 21 and restored["next_page"] == 3
    assert list_items(db)[1] == 21


def test_no_partial_advancement_when_item_request_fails(db):
    job_id = make(db)
    calls = []
    def handler(request):
        if "/contratacoes/publicacao" in request.url.path:
            return httpx.Response(200, json={
                "data": [tender(1), tender(2)], "paginasRestantes": 0,
            })
        calls.append(request)
        if "/compras/" in request.url.path and "/2/itens" in request.url.path:
            return httpx.Response(503, json={"upstream": "down"})
        return httpx.Response(200, json=item())
    failed = asyncio.run(next_step(
        db, job_id, httpx.MockTransport(handler)
    ))
    assert failed["state"] == "error"
    assert failed["next_page"] == 1
    assert failed["fetched"] == 0
    assert list_items(db)[1] == 0
    assert len(calls) == 2
    recovered = asyncio.run(next_step(
        db, job_id, mock_transport({
            1: {"data": [tender(1), tender(2)], "paginasRestantes": 0},
        })
    ))
    assert recovered["state"] == "completed"
    assert list_items(db)[1] == 2


@pytest.mark.parametrize("invalid", [
    {"data": [], "paginasRestantes": 2},
    {"data": [tender(1)] * 21, "paginasRestantes": 0},
    {"data": "wrong", "paginasRestantes": 0},
    {"data": [None], "paginasRestantes": 0},
    {"data": [tender(1)], "paginasRestantes": "many"},
    [],
])
def test_invalid_pagination_never_claims_complete(db, invalid):
    job_id = make(db)
    step = asyncio.run(next_step(db, job_id, mock_transport({1: invalid})))
    assert step["state"] == "error"
    assert step["next_page"] == 1
    assert step["processed_pages"] == 0
    assert step["errors"] == 1
    assert list_items(db)[1] == 0


def test_no_false_complete_on_short_page_if_metadata_says_more():
    rows, done = _page_rows({"data": [tender(1)], "paginasRestantes": 10})
    assert len(rows) == 1 and done is False


def test_missing_pagination_metadata_requires_empty_followup(db):
    job_id = make(db)
    step = asyncio.run(next_step(db, job_id, mock_transport({
        1: {"data": [tender(x) for x in range(1, 21)]},
        2: {"data": [], "paginasRestantes": 0},
    })))
    assert step["state"] == "completed"
    assert step["processed_pages"] == 2
    assert step["fetched"] == 20


def test_municipality_and_uf_mismatch_fails_closed(db):
    job_id = make(db)
    step = asyncio.run(next_step(db, job_id, mock_transport({
        1: {"data": [tender(1, "RJ")], "paginasRestantes": 0},
    })))
    assert step["state"] == "error"
    assert list_items(db)[1] == 0


@pytest.mark.parametrize("args", [
    (DAY, DAY + timedelta(days=7), "SP", 6, ""),
    (DAY, DAY, "SÃO", 6, ""),
    (DAY, DAY, "", 6, "abc"),
    (DAY, DAY, "", 6, "12345678"),
    (DAY, DAY, "", 9, ""),
    (date(2020, 12, 31), date(2020, 12, 31), "", 6, ""),
    (date.today() + timedelta(days=1), date.today() + timedelta(days=1), "", 6, ""),
])
def test_bad_coverage_filter_fails_without_creating_jobs(db, args):
    with pytest.raises(CoverageError):
        create_job(db, *args)
    assert coverage_jobs(db) == []


def test_job_limit_and_non_destructive_removal(db):
    for index in range(20):
        job = create_job(db, DAY, DAY, "SP", 6, "")
        assert job == index + 1
    with pytest.raises(CoverageError, match="20 pesquisas"):
        create_job(db, DAY, DAY, "SP", 6, "")
    delete_job(db, 5)
    assert len(coverage_jobs(db)) == 19
    assert create_job(db, DAY, DAY, "SP", 6, "") > 20


def test_auth_csrf_start_and_synthetic_dashboard(client):
    assert client.get("/coverage", follow_redirects=False).status_code == 303
    assert client.get("/api/coverage").status_code == 401
    assert client.post("/coverage/start", data={}, follow_redirects=False).status_code == 303
    login(client)
    page = client.get("/coverage")
    assert page.status_code == 200
    assert "Mais municípios." in page.text
    assert "Cobertura" in client.get("/").text
    for path in ("/coverage/start", "/coverage/next", "/coverage/delete"):
        assert client.post(path, data={"csrf": "invalid"}).status_code == 403
    invalid = client.post("/coverage/start", data={
        "csrf": csrf(client), "start": FIRST, "end": LAST,
        "modality": "6", "uf": "SP", "municipality_ibge": "123<script>",
    })
    assert invalid.status_code == 422
    valid = client.post("/coverage/start", data={
        "csrf": csrf(client), "start": FIRST, "end": LAST,
        "modality": "6", "uf": "SP", "municipality_ibge": "3509502",
    }, follow_redirects=False)
    assert valid.status_code == 303
    assert valid.headers["location"] == "/coverage"
    jobs = client.get("/api/coverage").json()["data"]
    assert len(jobs) == 1 and jobs[0]["municipality_ibge"] == "3509502"
    assert jobs[0]["state"] == "paused"
    assert client.get("/api/coverage").headers["cache-control"] == "no-store"
    deleted = client.post("/coverage/delete", data={
        "csrf": csrf(client), "id": jobs[0]["id"],
    }, follow_redirects=False)
    assert deleted.status_code == 303
    assert client.get("/api/coverage").json()["data"] == []


def test_continuation_endpoint_guarded_without_network(client, monkeypatch):
    import app.main as controller

    login(client)
    data = {
        "csrf": csrf(client), "start": FIRST, "end": LAST,
        "modality": "6", "uf": "SP", "municipality_ibge": "3509502",
    }
    client.post("/coverage/start", data=data)
    seen = []
    async def no_network(path, job_id):
        seen.append(job_id)
        return {"state": "paused"}
    monkeypatch.setattr(controller, "next_step", no_network)
    assert client.post("/coverage/next", data={
        "csrf": csrf(client), "id": 1,
    }, follow_redirects=False).status_code == 303
    assert seen == [1]
    assert client.post("/coverage/next", data={
        "csrf": csrf(client), "id": "not-an-id",
    }).status_code == 422
