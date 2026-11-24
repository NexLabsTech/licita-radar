"""Workflow local: zero inscrição externa, dados privados, prazos e exportação segura."""
import csv
import io
import re

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app
from app.security import hash_password
from app.storage import init_db, upsert_tender
from app.workspace import (
    WorkspaceError,
    add_task,
    case_events,
    case_tasks,
    delete_task,
    export_csv,
    get_case,
    init_workspace,
    list_cases,
    save_case,
    safe_excel_text,
    toggle_task,
)

PW = "SenhaWorkflowTeste#2026"
SECRET = "workspace_test_secret_long_enough_to_sign_2026"
CONTROL = "12345678000190-1-000007/2026"
OTHER = "12345678000190-1-000008/2026"


def tender(control=CONTROL, sequence=7):
    return {
        "id": control, "cnpj": "12345678000190",
        "ano": 2026, "sequencial": sequence,
        "orgao": "Prefeitura Fictícia", "municipio": "Salto",
        "uf": "SP", "objeto": "Papelaria",
        "data_publicacao": "2026-11-23",
        "abertura": None, "encerramento": None,
        "link": f"https://pncp.gov.br/app/editais/12345678000190/2026/{sequence}",
    }


def item(status=1, name="Caderno escolar"):
    return [{
        "numeroItem": 1, "materialOuServico": "M",
        "descricao": name, "situacaoCompraItemId": status,
        "quantidade": 10, "valorTotal": 2000,
    }]


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "workspace.sqlite3")
    init_db(path)
    init_workspace(path)
    upsert_tender(path, tender(), item())
    return path


@pytest.fixture
def client(db):
    with TestClient(create_app(Settings(
        username="admin",
        password_hash=hash_password(PW, b"1234567890abcdef"),
        session_secret=SECRET, db_path=db, secure_cookies=False,
    ))) as http:
        yield http


def login(web):
    csrf = re.search(
        r'name="csrf" value="([^"]+)"', web.get("/login").text
    ).group(1)
    response = web.post("/login", data={
        "csrf": csrf, "username": "admin", "password": PW,
    }, follow_redirects=False)
    assert response.status_code == 303


def csrf(web, page="/workspace"):
    response = web.get(page)
    assert response.status_code == 200
    return re.search(
        r'name="csrf" value="([^"]+)"', response.text
    ).group(1)


def test_save_case_and_stage_history_is_manual(db):
    first = save_case(db, CONTROL, 1, "avaliar", "normal",
                      "2026-12-10", "Pedir preço de papelaria")
    assert first["stage"] == "avaliar"
    assert first["deadline"] == "2026-12-10"
    assert first["notes"] == "Pedir preço de papelaria"
    assert len(case_events(db, CONTROL, 1)) == 1
    save_case(db, CONTROL, 1, "avaliar", "alta", "2026-12-10", "Atualizada")
    assert len(case_events(db, CONTROL, 1)) == 1
    save_case(db, CONTROL, 1, "inscrito", "alta", "2026-12-10", "Marquei manualmente")
    assert case_events(db, CONTROL, 1)[0]["old_stage"] == "avaliar"
    assert case_events(db, CONTROL, 1)[0]["new_stage"] == "inscrito"
    assert len(list_cases(db)) == 1
    assert list_cases(db)[0]["priority"] == "alta"


def test_case_survives_item_reimport_without_automatic_stage_change(db):
    save_case(db, CONTROL, 1, "cotando", "normal")
    add_task(db, CONTROL, 1, "Conferir estoque")
    upsert_tender(db, tender(), item(status=4, name="Caderno escolar"))
    actual = get_case(db, CONTROL, 1)
    assert actual["stage"] == "cotando"
    assert actual["pncp_status"] == 4
    assert len(case_tasks(db, CONTROL, 1)) == 1
    assert len(case_events(db, CONTROL, 1)) == 1
    assert actual["link"].startswith("https://pncp.gov.br/")


def test_task_checklist_lifecycle_and_item_isolation(db):
    upsert_tender(db, tender(OTHER, 8), item())
    save_case(db, CONTROL, 1, "avaliar", "normal")
    save_case(db, OTHER, 1, "avaliar", "normal")
    task_id = add_task(db, CONTROL, 1, "Solicitar cotação com frete")
    assert case_tasks(db, CONTROL, 1)[0]["done"] == 0
    toggle_task(db, task_id, OTHER, 1)
    assert case_tasks(db, CONTROL, 1)[0]["done"] == 0
    delete_task(db, task_id, OTHER, 1)
    assert len(case_tasks(db, CONTROL, 1)) == 1
    toggle_task(db, task_id, CONTROL, 1)
    assert case_tasks(db, CONTROL, 1)[0]["done"] == 1
    toggle_task(db, task_id, CONTROL, 1)
    assert case_tasks(db, CONTROL, 1)[0]["done"] == 0
    delete_task(db, task_id, CONTROL, 1)
    assert case_tasks(db, CONTROL, 1) == []


def test_task_max_20_and_invalid_labels(db):
    save_case(db, CONTROL, 1, "avaliar", "normal")
    for index in range(20):
        add_task(db, CONTROL, 1, f"Pesquisar preço {index}")
    assert len(case_tasks(db, CONTROL, 1)) == 20
    with pytest.raises(WorkspaceError, match="20 tarefas"):
        add_task(db, CONTROL, 1, "Além do máximo")
    with pytest.raises(WorkspaceError):
        add_task(db, CONTROL, 1, "x")
    with pytest.raises(WorkspaceError):
        add_task(db, CONTROL, 1, "x" * 121)


@pytest.mark.parametrize("stage,priority,deadline,notes", [
    ("liquidado", "normal", "", ""),
    ("avaliar", "urgente", "", ""),
    ("avaliar", "normal", "2026-02-30", ""),
    ("avaliar", "normal", "2026-11-23T00:00", ""),
    ("avaliar", "normal", "", "x" * 1201),
])
def test_invalid_workflow_data_is_rejected(db, stage, priority, deadline, notes):
    with pytest.raises(WorkspaceError):
        save_case(db, CONTROL, 1, stage, priority, deadline, notes)
    assert list_cases(db) == []


def test_cannot_create_workflow_for_uncollected_item(db):
    with pytest.raises(WorkspaceError) as exc:
        save_case(db, "none", 1, "avaliar", "normal")
    assert exc.value.status_code == 404
    with pytest.raises(WorkspaceError) as exc:
        add_task(db, CONTROL, 1, "Conferir edital")
    assert exc.value.status_code == 404


def test_export_csv_neutralizes_formula_injection(db):
    malicious = "=HYPERLINK(\"https://bad.example\")"
    upsert_tender(db, tender(), item(name=malicious))
    save_case(db, CONTROL, 1, "avaliar", "normal", "", "   @SUM(1,2)")
    row = list_cases(db)[0]
    document = export_csv([row])
    assert document.startswith("\ufeff")
    fields = list(csv.reader(io.StringIO(document.lstrip("\ufeff"))))
    assert len(fields) == 2
    assert fields[1][2].startswith("'=HYPERLINK")
    assert fields[1][10].lstrip().startswith("'@SUM")
    assert not fields[1][2].startswith("=")
    assert safe_excel_text(" +cmd").startswith("' +cmd")
    assert safe_excel_text("normal") == "normal"


def test_authenticated_workflow_and_private_export(client, db):
    assert client.get("/workspace", follow_redirects=False).status_code == 303
    assert client.get("/api/workspace").status_code == 401
    assert client.get("/workspace/export.csv").status_code == 401
    assert client.post("/workspace/save", data={}, follow_redirects=False).status_code == 303
    login(client)
    page = client.get("/workspace", params={"tender_id": CONTROL, "numero": 1})
    assert page.status_code == 200
    assert "Plano da oportunidade" in page.text
    assert "Caderno escolar" in page.text
    assert "Salve o plano primeiro" in page.text
    for route in ("/workspace/save", "/workspace/task/add",
                  "/workspace/task/toggle", "/workspace/task/delete"):
        assert client.post(route, data={"csrf": "wrong"}).status_code == 403
    token = csrf(client)
    result = client.post("/workspace/save", data={
        "csrf": token, "tender_id": CONTROL, "numero": "1",
        "stage": "cotando", "priority": "alta",
        "deadline": "2026-12-01", "notes": "Fornecedor foi consultado",
    }, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"].startswith("/workspace?")
    assert client.get("/api/workspace").json()["data"][0]["stage"] == "cotando"
    assert client.get("/api/workspace").headers["cache-control"] == "no-store"
    exported = client.get("/workspace/export.csv")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert "Fornecedor foi consultado" in exported.text
    assert exported.headers["cache-control"] == "no-store"
    assert "text/csv" in exported.headers["content-type"]


def test_html_escaping_and_private_checklist_routes(client, db):
    login(client)
    token = csrf(client)
    bad_notes = "<script>alert('x')</script>"
    created = client.post("/workspace/save", data={
        "csrf": token, "tender_id": CONTROL, "numero": "1",
        "stage": "avaliar", "priority": "normal", "notes": bad_notes,
    }, follow_redirects=False)
    assert created.status_code == 303
    viewed = client.get(created.headers["location"]).text
    assert "&lt;script&gt;" in viewed
    assert "<script>alert" not in viewed

    added = client.post("/workspace/task/add", data={
        "csrf": token, "tender_id": CONTROL, "numero": 1,
        "label": "Ler documentação",
    }, follow_redirects=False)
    assert added.status_code == 303
    task = case_tasks(db, CONTROL, 1)[0]
    toggled = client.post("/workspace/task/toggle", data={
        "csrf": token, "tender_id": CONTROL, "numero": 1, "task_id": task["id"],
    }, follow_redirects=False)
    assert toggled.status_code == 303
    assert case_tasks(db, CONTROL, 1)[0]["done"] == 1
    assert client.post("/workspace/task/delete", data={
        "csrf": token, "tender_id": CONTROL, "numero": 1, "task_id": task["id"],
    }, follow_redirects=False).status_code == 303
    assert not case_tasks(db, CONTROL, 1)


def test_no_phantom_registration_after_manual_stage(client, db):
    login(client)
    token = csrf(client)
    response = client.post("/workspace/save", data={
        "csrf": token, "tender_id": CONTROL, "numero": "1",
        "stage": "inscrito", "priority": "normal",
        "notes": "Verificar comprovação de inscrição",
    }, follow_redirects=False)
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "Inscrição marcada manualmente" in html
    assert "não comprova inscrição" in html.lower()
    assert get_case(db, CONTROL, 1)["stage"] == "inscrito"
    assert client.get("/").status_code == 200


def test_task_mutation_rejects_invalid_identifiers(client):
    login(client)
    token = csrf(client)
    for action in ("toggle", "delete"):
        response = client.post("/workspace/task/" + action, data={
            "csrf": token, "tender_id": CONTROL,
            "numero": "1", "task_id": "invalid",
        })
        assert response.status_code == 422


def test_workspace_capacity_200_cases(db):
    for index in range(1, 201):
        control = f"12345678000190-1-{index:06d}/2026"
        upsert_tender(db, tender(control, index), item())
        save_case(db, control, 1, "avaliar", "normal")
    assert len(list_cases(db)) == 200
    next_control = "12345678000190-1-000201/2026"
    upsert_tender(db, tender(next_control, 201), item())
    with pytest.raises(WorkspaceError, match="200 oportunidades"):
        save_case(db, next_control, 1, "avaliar", "normal")
