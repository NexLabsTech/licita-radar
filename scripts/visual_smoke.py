"""Smoke visual determinístico, com Chromium e credenciais efêmeras (CI).

Execute: pip install playwright && python -m playwright install chromium
         python -m scripts.visual_smoke
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from app.main import Settings, create_app
from app.security import hash_password


def _server(port: int, db_path: str) -> uvicorn.Server:
    settings = Settings(
        username="visual-ci",
        password_hash=hash_password("TesteVisualCI!2026Lime"),
        session_secret="visual_smoke_only_not_a_real_secret_2026_" * 2,
        db_path=db_path,
        secure_cookies=False,
        auto_scan=False,
    )
    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    return uvicorn.Server(config)


def run() -> None:
    # Nada escuta publicamente; dados e credenciais de teste descartados após execução.
    import socket

    with tempfile.TemporaryDirectory(prefix="licitaradar-visual-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        db_path = str(Path(directory) / "visual.db")
        server = _server(port, db_path)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        root = "http://127.0.0.1:" + str(port)
        for _ in range(80):
            try:
                if httpx.get(root + "/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Servidor não iniciou para teste visual.")

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                output = Path("artifacts")
                output.mkdir(exist_ok=True)
                for name, width, height in (
                    ("desktop", 1440, 1000),
                    ("mobile", 390, 844),
                ):
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                        reduced_motion="reduce",
                    )
                    problems = []
                    page.on("pageerror", lambda exception: problems.append(str(exception)))
                    page.goto(root + "/login", wait_until="networkidle")
                    assert page.get_by_role("heading", name="Bem-vindo de volta.").is_visible()
                    page.screenshot(
                        path=str(output / ("login-" + name + ".png")),
                        full_page=True,
                        animations="disabled",
                    )
                    page.get_by_label("Usuário").fill("visual-ci")
                    page.get_by_label("Senha").fill("TesteVisualCI!2026Lime")
                    page.get_by_role("button", name="Acessar o radar").click()
                    page.wait_for_url(root + "/")
                    assert page.get_by_role(
                        "heading", name="Oportunidades em foco."
                    ).is_visible()
                    assert page.get_by_text("Nenhum item encontrado").is_visible()
                    assert page.get_by_role("link", name="Portal oficial").count() == 1
                    assert page.locator("main #sync-form").count() == 1
                    page.get_by_role("button", name="Recarregar os dados do painel").click()
                    page.wait_for_function(
                        "() => document.querySelector('#refresh-state')"
                        ".textContent.includes('Tela atualizada')"
                    )
                    no_overflow = page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                    )
                    assert no_overflow, "Overflow horizontal global em " + name
                    assert not problems, "Erro de JavaScript em " + name + ": " + str(problems)
                    page.screenshot(
                        path=str(output / ("dashboard-" + name + ".png")),
                        full_page=True,
                        animations="disabled",
                    )
                    page.close()
                    print("Visual smoke " + name + ": PASS")
                # Produto de CI explicitamente fictício, nunca apresentado como edital real.
                from urllib.parse import urlencode

                from app.storage import upsert_tender

                control = "12345678000190-1-000007/2026"
                upsert_tender(db_path, {
                    "id": control, "cnpj": "12345678000190", "ano": 2026,
                    "sequencial": 7, "orgao": "Órgão FICTÍCIO (teste CI)",
                    "municipio": "Cidade CI", "uf": "SP",
                    "objeto": "Amostra automatizada para testes, NÃO REAL",
                    "data_publicacao": "2026-11-23", "abertura": None,
                    "encerramento": None,
                    "link": "https://pncp.gov.br/app/editais/12345678000190/2026/7",
                }, [{
                    "numeroItem": 1, "materialOuServico": "M",
                    "descricao": "Caderno CI - produto de teste fictício",
                    "situacaoCompraItemId": 1, "quantidade": 10,
                    "valorTotal": 2000,
                }])
                quote_url = root + "/quote?" + urlencode({
                    "tender_id": control, "numero": 1,
                })
                for name, width, height in (
                    ("desktop", 1440, 1000), ("mobile", 390, 844),
                ):
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1, reduced_motion="reduce",
                    )
                    problems = []
                    page.on("pageerror", lambda exception: problems.append(str(exception)))
                    page.goto(root + "/login", wait_until="networkidle")
                    page.get_by_label("Usuário").fill("visual-ci")
                    page.get_by_label("Senha").fill("TesteVisualCI!2026Lime")
                    page.get_by_role("button", name="Acessar o radar").click()
                    page.wait_for_url(root + "/")
                    page.goto(quote_url, wait_until="networkidle")
                    assert page.get_by_role(
                        "heading", name="Calculadora de oportunidade."
                    ).is_visible()
                    page.get_by_label("Fornecedor / origem da cotação").fill("Fornecedor TESTE CI")
                    for field, value in {
                        "unit_cost": "100.00", "freight": "100.00",
                        "packaging": "20.00", "other": "30.00",
                        "risk_reserve": "50.00", "tax_percent": "10.00",
                        "target_margin": "20.00",
                    }.items():
                        page.locator("#" + field).fill(value)
                    page.get_by_role("button", name="Salvar e calcular margem").click()
                    page.wait_for_url(quote_url)
                    assert page.get_by_text("Potencial financeiro condicionado").is_visible()
                    assert page.get_by_text("R$ 1714.29").is_visible()
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                    ), "Overflow global na calculadora de " + name
                    assert not problems, "Script na calculadora " + name + ": " + str(problems)
                    page.screenshot(
                        path=str(output / ("quote-" + name + ".png")),
                        full_page=True, animations="disabled",
                    )
                    ai_url = root + "/ai?" + urlencode({
                        "tender_id": control, "numero": 1,
                    })
                    page.goto(ai_url, wait_until="networkidle")
                    assert page.get_by_role(
                        "heading", name="Decisões mais claras. Com IA."
                    ).is_visible()
                    assert page.get_by_text("IA desativada").count() >= 1
                    assert page.get_by_role(
                        "button", name="Analisar oportunidade"
                    ).is_disabled()
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                    ), "Overflow global no assistente de " + name
                    assert not problems, "Erro JavaScript no assistente: " + str(problems)
                    page.screenshot(
                        path=str(output / ("assistant-" + name + ".png")),
                        full_page=True, animations="disabled",
                    )
                    monitor_url = root + "/monitor?" + urlencode({
                        "tender_id": control, "numero": 1,
                    })
                    page.goto(monitor_url, wait_until="networkidle")
                    assert page.get_by_role(
                        "heading", name="Regras de oportunidade"
                    ).is_visible()
                    if page.get_by_role(
                        "button", name="★ Acompanhar este item"
                    ).count():
                        page.get_by_role(
                            "button", name="★ Acompanhar este item"
                        ).click()
                        page.wait_for_url(root + "/monitor")
                    assert page.get_by_role(
                        "heading", name="Favoritos"
                    ).is_visible()
                    assert page.get_by_text(
                        "Caderno CI - produto de teste fictício"
                    ).count() >= 1
                    if name == "desktop":
                        page.get_by_label("Produto ou palavra-chave").fill("Caderno")
                        page.get_by_role(
                            "button", name="Criar regra"
                        ).click()
                        page.wait_for_url(root + "/monitor")
                        assert page.get_by_text("Nova correspondência de regra").count() == 0
                        assert page.get_by_text("Correspondência inicial de regra").count() >= 1
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                    ), "Overflow global em monitor " + name
                    assert not problems, "Erro de script em monitor " + name + ": " + str(problems)
                    page.screenshot(
                        path=str(output / ("monitor-" + name + ".png")),
                        full_page=True, animations="disabled",
                    )
                    results_url = root + "/results?" + urlencode({
                        "tender_id": control, "numero": 1,
                    })
                    page.goto(results_url, wait_until="networkidle")
                    assert page.get_by_role(
                        "heading", name="Registros de resultados"
                    ).is_visible()
                    assert page.get_by_text("Ainda não consultado").count() >= 1
                    assert page.get_by_role(
                        "button", name="Atualizar resultados PNCP"
                    ).is_visible()
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                    ), "Overflow no painel de resultados " + name
                    assert not problems, "Erros JS em resultados " + name + ": " + str(problems)
                    page.screenshot(
                        path=str(output / ("results-" + name + ".png")),
                        full_page=True, animations="disabled",
                    )
                    page.goto(root + "/coverage", wait_until="networkidle")
                    assert page.locator("#new-scan-title").is_visible()
                    assert page.locator("#coverage-jobs-title").is_visible()
                    if name == "desktop":
                        page.get_by_label("Código IBGE do município").fill("3509502")
                        page.get_by_role("button", name="Criar pesquisa").click()
                        page.locator(".coverage-job").first.wait_for()
                        assert page.get_by_role(
                            "button", name="Consultar próximo lote"
                        ).is_visible()
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                    ), "Overflow no painel de cobertura " + name
                    assert not problems, "Script de cobertura " + name + ": " + str(problems)
                    page.screenshot(
                        path=str(output / ("coverage-" + name + ".png")),
                        full_page=True, animations="disabled",
                    )
                    page.close()
                    print("Quote + AI visual smoke " + name + ": PASS")
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=12)


if __name__ == "__main__":
    run()
