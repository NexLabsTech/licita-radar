"""Contrato do assistente: falhar fechado, custo limitado, dados e PDFs não confiáveis."""
import asyncio
import io
import json
import re
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ai import (
    AIConfig, AIError, analyze_opportunity, calls_today, document_input, extract_pdf,
    get_cached, init_ai, reserve_call, run_model, validate_model_output,
)
from app.main import Settings, create_app
from app.quotes import get_item, get_quote, init_quotes, save_quote
from app.security import hash_password
from app.storage import init_db, upsert_tender
from app.intelligence import validate_quote


def tender():
    return {
        "id": "12345678000190-1-000007/2026",
        "cnpj": "12345678000190", "ano": 2026, "sequencial": 7,
        "orgao": "Prefeitura Teste", "municipio": "Salto", "uf": "SP",
        "objeto": "Papelaria", "data_publicacao": "2026-11-23",
        "abertura": "2026-11-23", "encerramento": "2026-11-28",
        "link": "https://pncp.gov.br/app/editais/12345678000190/2026/7",
    }


def item(status=1):
    return {
        "numeroItem": 1, "materialOuServico": "M",
        "descricao": "Caneta azul", "quantidade": 10,
        "valorTotal": 300.0, "situacaoCompraItemId": status,
    }


def quote():
    return validate_quote({
        "supplier": "Fornecedor teste",
        "unit_cost": "10.00", "freight": "10.00",
        "packaging": "0.00", "other": "0.00",
        "risk_reserve": "10.00", "tax_percent": "10.00",
        "target_margin": "20.00",
    })


def valid_output():
    return {
        "acao": "investigar", "confianca": "baixa",
        "resumo": "Rever edital e condições de entrega antes de qualquer proposta.",
        "riscos": ["Especificações ainda não conferidas."],
        "requisitos": ["Verificar exigências documentais no edital."],
        "lacunas": ["Ainda não foi revisado o edital completo."],
        "proximos_passos": ["Abrir a fonte oficial e conferir prazos."],
        "evidencias_documentais": [],
    }


def transport_for(result, callback=None, status=200):
    def handler(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        if callback:
            callback(request)
        return httpx.Response(status, json=result)
    return httpx.MockTransport(handler)


def wrapped(reply=None):
    return {
        "choices": [{"finish_reason": "stop",
                     "message": {"content": json.dumps(
                         reply if reply is not None else valid_output(), ensure_ascii=False
                     )}}],
        "usage": {"total_tokens": 100},
    }


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "ai.sqlite")
    init_db(path)
    init_quotes(path)
    init_ai(path)
    upsert_tender(path, tender(), [item()])
    return path


@pytest.fixture
def config():
    return AIConfig(enabled=True, key="TEST_KEY_NOT_REAL", daily_limit=2)


@pytest.fixture
def client(db_path):
    settings = Settings(
        username="owner", password_hash=hash_password(
            "TestPasswordSecure#2026", b"1234567890abcdef"),
        session_secret="secret" * 10, db_path=db_path, secure_cookies=False,
    )
    with TestClient(create_app(settings)) as instance:
        yield instance


def login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/login", data={"csrf": token, "username": "owner",
                        "password": "TestPasswordSecure#2026"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def pdf_with_text():
    pdf = PdfWriter()
    page = pdf.add_blank_page(width=595, height=842)
    font = pdf._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 70 750 Td (Prazo de entrega em 15 dias) Tj ET")
    page[NameObject("/Contents")] = pdf._add_object(stream)
    output = io.BytesIO()
    pdf.write(output)
    return output.getvalue()


def test_configs_and_model_allowlist_fail_closed():
    assert not AIConfig().valid
    assert AIConfig(enabled=True, key="fake").valid
    assert AIConfig(enabled=True, key="fake").selected_model == "deepseek-flash"
    assert not AIConfig(enabled=True, key="fake", provider="custom").valid
    assert not AIConfig(enabled=True, key="fake", model="surprise-model").valid
    assert not AIConfig(enabled=True, key="fake", daily_limit=200).valid
    other = AIConfig(enabled=True, key="fake", provider="openrouter")
    assert other.valid
    assert other.selected_model == "deepseek/deepseek-v4.1-flash"
    assert other.endpoint == "https://openrouter.ai/api/v1/chat/completions"
    assert "key" not in AIConfig(enabled=True, key="fake").public_status()


@pytest.mark.parametrize("provider", ["deepseek", "openrouter"])
def test_provider_real_identifiers_with_mock_transport(provider):
    cfg = AIConfig(enabled=True, key="SECRET_FOR_TEST", provider=provider)
    seen = []
    def inspect(request):
        seen.append(request)
        data = json.loads(request.content)
        assert data["model"] == cfg.selected_model
        assert data["max_tokens"] == 900
        assert data["response_format"] == {"type": "json_object"}
        assert request.headers["Authorization"] == "Bearer SECRET_FOR_TEST"
        assert "http" in str(request.url)
        if provider == "deepseek":
            assert str(request.url) == "https://api.deepseek.com/chat/completions"
            assert data["thinking"]["type"] == "disabled"
        else:
            assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
            assert "thinking" not in data
        assert "tools" not in data

    context = {"documento": {"trecho": ""}}
    reply = asyncio.run(run_model(
        cfg, context, transport=transport_for(wrapped(), callback=inspect)
    ))
    assert reply["acao"] == "investigar"
    assert len(seen) == 1


@pytest.mark.parametrize("invalid", [
    {"acao": "participar"},
    {"acao": "enviar_lance"},
    {"confianca": "certeza"},
    {"resumo": "Ganhe R$ 1.000 com certeza."},
    {"evidencias_documentais": ["Cláusula inventada"]},
    {"riscos": ["texto"] * 8},
])
def test_untrusted_model_output_is_rejected(invalid):
    result = {**valid_output(), **invalid}
    with pytest.raises(AIError) as exc:
        validate_model_output(result, has_document=False)
    assert exc.value.status_code == 502


@pytest.mark.parametrize("status", [401, 429, 500])
def test_upstream_errors_redacted(status):
    config = AIConfig(enabled=True, key="ULTRASECRETATEST")
    with pytest.raises(AIError) as exc:
        asyncio.run(run_model(
            config, {"documento": {"trecho": ""}},
            transport=transport_for({"message": "ULTRASECRETATEST"}, status=status),
        ))
    assert "ULTRASECRETATEST" not in str(exc.value)
    assert exc.value.status_code in (502, 503)


def test_truncated_or_malformed_model_response_never_accepted():
    cfg = AIConfig(enabled=True, key="mock")
    for body in (
        {"choices": [{"finish_reason": "length", "message": {
            "content": json.dumps(valid_output())}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "{invalid"}}]},
        {"choices": []},
    ):
        with pytest.raises(AIError):
            asyncio.run(run_model(cfg, {"documento": {"trecho": ""}},
                                  transport=transport_for(body)))


def test_cache_idempotence_and_daily_budget(db_path, config):
    current = get_item(db_path, tender()["id"], 1)
    assert current is not None
    calls = []
    def inspect(request):
        calls.append(request)

    def analyze_once():
        return asyncio.run(analyze_opportunity(
            db_path, config, current, None, "", "Sem documento fornecido",
            transport=transport_for(wrapped(), callback=inspect)
        ))

    response, cached = analyze_once()
    assert response["acao"] == "investigar" and not cached
    response, cached = analyze_once()
    assert cached and len(calls) == 1 and calls_today(db_path) == 1
    changed = asyncio.run(analyze_opportunity(
        db_path, config, current, None, "novo contexto", "Trecho colado",
        transport=transport_for(wrapped()),
    ))
    assert changed[1] is False
    assert calls_today(db_path) == 2
    with pytest.raises(AIError) as exc:
        asyncio.run(analyze_opportunity(
            db_path, config, current, None, "outro documento", "Trecho colado",
            transport=transport_for(wrapped())
        ))
    assert exc.value.status_code == 429


def test_provider_error_consumes_attempt_without_caching(db_path, config):
    entry = get_item(db_path, tender()["id"], 1)
    assert entry
    with pytest.raises(AIError):
        asyncio.run(analyze_opportunity(
            db_path, config, entry, None, "", "Sem documento fornecido",
            transport=transport_for({"error": "refused"}, status=401),
        ))
    assert calls_today(db_path) == 1


def test_pdf_text_extraction_and_nontext_rejection():
    text, pages = extract_pdf(pdf_with_text())
    assert pages == 1
    assert "Prazo de entrega em 15 dias" in text
    extracted, origin = document_input("", pdf_with_text())
    assert "15 dias" in extracted and "PDF" in origin
    blank = PdfWriter()
    blank.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    blank.write(buffer)
    with pytest.raises(AIError, match="sem texto"):
        extract_pdf(buffer.getvalue())


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.4\nBROKEN", b"%PDF-" + b"0" * (3 * 1024 * 1024)])
def test_reject_invalid_pdfs(data):
    with pytest.raises(AIError):
        extract_pdf(data)


def test_manual_excerpt_validation():
    assert document_input("  entrega em 5 dias  ", None) == (
        "entrega em 5 dias", "Trecho de edital colado pelo usuário"
    )
    with pytest.raises(AIError):
        document_input("x" * 3501, None)
    with pytest.raises(AIError):
        document_input("texto", pdf_with_text())


def test_historical_items_cannot_be_presented_as_active(db_path, config):
    record = tender()
    upsert_tender(db_path, record, [item(status=4)])
    current = get_item(db_path, record["id"], 1)
    reply = {**valid_output(), "acao": "cotar"}
    result, cached = asyncio.run(analyze_opportunity(
        db_path, config, current, None, "", "Sem documento fornecido",
        transport=transport_for(wrapped(reply)),
    ))
    assert result["acao"] == "investigar"
    assert any("nova publicação" in line for line in result["lacunas"])
    assert not cached


def test_ai_requires_auth_csrf_and_optin(client):
    path = "/ai?tender_id=12345678000190-1-000007%2F2026&numero=1"
    assert client.get(path, follow_redirects=False).status_code == 303
    assert client.post("/ai", data={}, follow_redirects=False).status_code == 303
    login(client)
    page = client.get(path)
    assert page.status_code == 200
    assert "IA desativada" in page.text
    assert "TEST_KEY_NOT_REAL" not in page.text
    assert client.get("/ai?tender_id=missing&numero=1").status_code == 404
    assert client.post("/ai", data={"csrf": "bad", "tender_id": tender()["id"], "numero": 1}).status_code == 403
    form = {
        "csrf": csrf(client, path),
        "tender_id": tender()["id"], "numero": "1", "document_text": "",
    }
    assert client.post("/ai", data=form).status_code == 403
    assert client.post("/ai", data={**form, "consent": "yes"}).status_code == 503


def test_ai_post_with_optin_uses_mock_and_never_renders_secret(db_path, monkeypatch):
    import app.ai as provider

    config = AIConfig(enabled=True, key="KEY_TO_KEEP_SECRET")
    settings = Settings(
        username="owner", password_hash=hash_password(
            "TestPasswordSecure#2026", b"1234567890abcdef"),
        session_secret="secret" * 10, db_path=db_path,
        secure_cookies=False, ai=config,
    )
    async def fake_model(cfg, context, **kwargs):
        assert cfg.key == "KEY_TO_KEEP_SECRET"
        assert "prazo" in context["documento"]["trecho"]
        return valid_output()

    monkeypatch.setattr(provider, "run_model", fake_model)
    with TestClient(create_app(settings)) as web:
        login(web)
        path = "/ai?tender_id=12345678000190-1-000007%2F2026&numero=1"
        result = web.post("/ai", data={
            "csrf": csrf(web, path), "tender_id": tender()["id"],
            "numero": 1, "consent": "yes", "document_text": "prazo a confirmar",
        })
        assert result.status_code == 200
        assert "Relatório de inteligência" in result.text
        assert "Investigar edital" in result.text
        assert "KEY_TO_KEEP_SECRET" not in result.text
        assert web.get("/").status_code == 200
        assert calls_today(db_path) == 1


def test_quote_changes_digest_and_requires_new_call(db_path, config):
    record = get_item(db_path, tender()["id"], 1)
    assert record
    one = asyncio.run(analyze_opportunity(
        db_path, config, record, None, "", "Sem documento fornecido",
        transport=transport_for(wrapped()),
    ))
    assert one[1] is False
    save_quote(db_path, tender()["id"], 1, quote())
    two = asyncio.run(analyze_opportunity(
        db_path, config, record, get_quote(db_path, tender()["id"], 1),
        "", "Sem documento fornecido", transport=transport_for(wrapped()),
    ))
    assert two[1] is False
    assert calls_today(db_path) == 2


def test_status_does_not_expose_key_to_unconfigured_app(client):
    login(client)
    response = client.get("/ai?tender_id=12345678000190-1-000007%2F2026&numero=1")
    assert response.headers["cache-control"] == "no-store"
    assert "Chave:" not in response.text
