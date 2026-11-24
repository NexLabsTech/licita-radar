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
        server = _server(port, str(Path(directory) / "visual.db"))
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
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=12)


if __name__ == "__main__":
    run()
