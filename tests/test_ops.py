"""Operação: configuração privada, persistência, recuperação e fail-closed."""
from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime, timedelta

import pytest

from app.ai import init_ai
from app.main import Settings, create_app
from app.quotes import get_quote, init_quotes, save_quote
from app.security import hash_password
from app.storage import init_db, upsert_tender
from scripts.ops_backup import (
    backup_database,
    file_sha256,
    restore_to_new_file,
    verify_sqlite,
)
from scripts.ops_setup import initialize, preflight, validate_domain


@pytest.fixture
def radar_db(tmp_path):
    path = tmp_path / "data" / "live.sqlite3"
    init_db(str(path))
    init_quotes(str(path))
    init_ai(str(path))
    tender = {
        "id": "12345678000190-1-000007/2026", "cnpj": "12345678000190",
        "ano": 2026, "sequencial": 7, "orgao": "Prefeitura Testes",
        "municipio": "Salto", "uf": "SP", "objeto": "Papelaria",
        "data_publicacao": "2026-11-23", "abertura": None, "encerramento": None,
        "link": "https://pncp.gov.br/app/editais/12345678000190/2026/7",
    }
    upsert_tender(str(path), tender, [{
        "numeroItem": 1, "materialOuServico": "M",
        "descricao": "Caneta", "quantidade": 12,
        "valorTotal": 600.0, "situacaoCompraItemId": 4,
    }])
    save_quote(str(path), tender["id"], 1, {
        "supplier": "FORNECEDOR SINTÉTICO",
        "unit_cost": "12.00", "freight": "20.00",
        "packaging": "0.00", "other": "0.00",
        "risk_reserve": "10.00", "tax_percent": "6.00",
        "target_margin": "15.00",
    })
    return path


def table_count(path, table):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]


def test_backup_and_restore_preserve_quotes_and_history(radar_db, tmp_path):
    directory = tmp_path / "backups"
    saved = backup_database(radar_db, directory)
    assert saved.is_file()
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    verify_sqlite(saved)
    assert len(file_sha256(saved)) == 64

    restored = restore_to_new_file(saved, tmp_path / "restored.sqlite3")
    assert table_count(restored, "tenders") == 1
    assert table_count(restored, "items") == 1
    assert table_count(restored, "item_events") == 1
    assert table_count(restored, "item_quotes") == 1
    assert get_quote(str(restored), "12345678000190-1-000007/2026", 1)["supplier"] == "FORNECEDOR SINTÉTICO"
    with pytest.raises(FileExistsError):
        restore_to_new_file(saved, restored)
    assert table_count(radar_db, "items") == 1


def test_backup_retention_only_touches_known_files(radar_db, tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    unrelated = directory / "other-user-export.sqlite3"
    unrelated.write_text("do not delete", encoding="utf-8")
    for i in range(4):
        time = datetime(2026, 11, 23, 10, 0, i, tzinfo=UTC) + timedelta(minutes=i)
        backup_database(radar_db, directory, keep=2, when=time)
    backups = list(directory.glob("licitaradar-*.sqlite3"))
    assert len(backups) == 2
    assert unrelated.read_text(encoding="utf-8") == "do not delete"
    for saved in backups:
        verify_sqlite(saved)


def test_invalid_or_symlinked_backup_is_rejected(radar_db, tmp_path):
    fake = tmp_path / "damaged.sqlite3"
    fake.write_bytes(b"not a database")
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        verify_sqlite(fake)
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(radar_db)
    with pytest.raises(ValueError):
        backup_database(alias, tmp_path / "backups")
    with pytest.raises(ValueError):
        restore_to_new_file(alias, tmp_path / "new.sqlite3")
    with pytest.raises(ValueError):
        backup_database(radar_db, tmp_path / "backups", keep=0)


def test_config_initializer_is_private_and_non_overwriting(tmp_path):
    runtime = tmp_path / "ops" / "runtime"
    initialize(runtime, "radar.licitatests.dev", "admin@licitatests.dev",
               "admin", "SenhaTesteLocal#2026")
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    for name in ("password_hash", "session_secret"):
        path = runtime / "secrets" / name
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert preflight(runtime) == {"domain": "radar.licitatests.dev", "user": "admin"}
    assert "SenhaTesteLocal#2026" not in (runtime / "app.env").read_text()
    with pytest.raises(FileExistsError):
        initialize(runtime, "radar.licitatests.dev", "admin@licitatests.dev",
                   "admin", "SenhaTesteLocal#2026")


def test_preflight_rejects_permission_and_expenses(tmp_path):
    runtime = tmp_path / "runtime"
    initialize(runtime, "radar.licitatests.dev", "admin@licitatests.dev",
               "admin", "SenhaTesteLocal#2026")
    secret = runtime / "secrets" / "session_secret"
    secret.chmod(0o666)
    with pytest.raises(ValueError, match="credencial"):
        preflight(runtime)
    secret.chmod(0o640)
    app_env = runtime / "app.env"
    app_env.write_text(app_env.read_text().replace("AI_ENABLED=0", "AI_ENABLED=1"))
    with pytest.raises(ValueError, match="IA"):
        preflight(runtime)


@pytest.mark.parametrize("domain", [
    "localhost", "radar.example.com", "radar.invalid", "https://radar.com",
    "127.0.0.1", "radar.com:443", "fake.local",
])
def test_preflight_rejects_fake_domains(domain):
    with pytest.raises(ValueError):
        validate_domain(domain)


def test_secrets_only_read_from_private_files(tmp_path, monkeypatch):
    password_file = tmp_path / "hash"
    session_file = tmp_path / "session"
    password_file.write_text(hash_password("SenhaTesteLocal#2026"))
    session_file.write_text("s" * 48)
    monkeypatch.setenv("LOGIN_USERNAME", "admin")
    monkeypatch.setenv("LOGIN_PASSWORD_HASH_FILE", str(password_file))
    monkeypatch.setenv("SESSION_SECRET_FILE", str(session_file))
    monkeypatch.delenv("LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_SECURE", "1")
    settings = Settings.from_env()
    assert settings.configured
    with pytest.raises(RuntimeError, match="simultaneamente"):
        monkeypatch.setenv("SESSION_SECRET", "s" * 48)
        Settings.from_env()
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    session_file.unlink()
    with pytest.raises(RuntimeError, match="indisponível"):
        Settings.from_env()


def test_production_rejects_invalid_or_insecure_login(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="Produção"):
        create_app(Settings())
    with pytest.raises(RuntimeError, match="Produção"):
        create_app(Settings(
            username="admin", password_hash=hash_password("SenhaTesteLocal#2026"),
            session_secret="s" * 48, secure_cookies=False,
        ))


def test_backup_does_not_expose_secrets_in_paths(radar_db, tmp_path):
    directory = tmp_path / "backups"
    backup = backup_database(radar_db, directory)
    assert "FORNECEDOR" not in str(backup.name)
    assert file_sha256(backup) != file_sha256(radar_db) or backup.is_file()
