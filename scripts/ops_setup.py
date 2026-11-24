"""One-time local preflight; creates private files on operator's own host.

Never pass password as a CLI argument or store secrets in the public repository.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import stat
from pathlib import Path

from app.security import hash_password, valid_password_hash

DOMAIN = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z-]{0,61}[a-z])?$"
)
USERNAME = re.compile(r"^[a-zA-Z0-9._-]{2,50}$")


def validate_domain(value: str) -> str:
    value = value.strip().lower()
    if (
        not DOMAIN.fullmatch(value)
        or value.endswith((".example.com", ".example", ".test", ".invalid", ".local"))
        or value in ("example.com", "localhost")
    ):
        raise ValueError("Informe domínio DNS real, sem esquema, porta ou caminho.")
    return value


def validate_email(value: str) -> str:
    value = value.strip()
    if (
        not 3 <= len(value) <= 254
        or " " in value
        or value.count("@") != 1
        or not value.split("@")[0]
    ):
        raise ValueError("E-mail ACME inválido.")
    domain = value.rsplit("@", 1)[1]
    validate_domain(domain)
    return value


def _write_new(path: Path, data: str) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(data.rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def initialize(
    root: Path,
    domain: str,
    email: str,
    username: str,
    password: str,
) -> None:
    valid_domain = validate_domain(domain)
    valid_email = validate_email(email)
    if not USERNAME.fullmatch(username):
        raise ValueError("Usuário: 2-50 caracteres de letras, números, _, . ou -.")
    if not 12 <= len(password) <= 256:
        raise ValueError("A senha precisa de 12 a 256 caracteres.")
    if root.is_symlink():
        raise ValueError("Diretório de operações não pode ser link simbólico.")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("Diretório de operações não está vazio; nada foi sobrescrito.")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)
    secure = root / "secrets"
    secure.mkdir(mode=0o700, exist_ok=False)
    _write_new(secure / "password_hash", hash_password(password))
    _write_new(secure / "session_secret", secrets.token_urlsafe(48))
    _write_new(root / "app.env", (
        "APP_ENV=production\n"
        "COOKIE_SECURE=1\n"
        f"LOGIN_USERNAME={username}\n"
        "DB_PATH=/app/data/licitaradar.db\n"
        "AUTO_SCAN_ENABLED=1\n"
        "AUTO_SCAN_INTERVAL_MINUTES=360\n"
        "AUTO_SCAN_UF=SP\n"
        "AI_ENABLED=0\n"
        "AI_PROVIDER=deepseek\n"
        "AI_DAILY_LIMIT=10"
    ))
    _write_new(root / "compose.env", f"RADAR_DOMAIN={valid_domain}\nACME_EMAIL={valid_email}")
    preflight(root)


def _parse_env(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Arquivo de configuração inválido.")
        name, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name) or name in result:
            raise ValueError("Nome de configuração inválido ou repetido.")
        result[name] = value
    return result


def _safe_private_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("Segredo indisponível ou inválido.")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Arquivo de credencial deve ser privado (chmod 600).")
    return path.read_text(encoding="utf-8").rstrip("\r\n")


def preflight(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Diretório de operações ausente/inseguro.")
    if stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("Diretório de operações precisa de chmod 700.")
    app = _parse_env(root / "app.env")
    deploy = _parse_env(root / "compose.env")
    if app.get("APP_ENV") != "production" or app.get("COOKIE_SECURE") != "1":
        raise ValueError("Produção exige APP_ENV=production e COOKIE_SECURE=1.")
    if app.get("DB_PATH") != "/app/data/licitaradar.db":
        raise ValueError("DB_PATH deve apontar para o volume persistente.")
    if not USERNAME.fullmatch(app.get("LOGIN_USERNAME", "")):
        raise ValueError("Login inválido.")
    if app.get("AI_ENABLED") != "0":
        raise ValueError("Habilitação da IA requer Work Order adicional e gate de custos.")
    if app.get("AUTO_SCAN_ENABLED") not in ("0", "1"):
        raise ValueError("AUTO_SCAN_ENABLED inválido.")
    try:
        interval = int(app.get("AUTO_SCAN_INTERVAL_MINUTES", "360"))
    except ValueError as exc:
        raise ValueError("Intervalo de coleta inválido.") from exc
    if not 30 <= interval <= 1440:
        raise ValueError("Intervalo de coleta fora do permitido.")
    if not re.fullmatch(r"[A-Z]{2}", app.get("AUTO_SCAN_UF", "")):
        raise ValueError("UF de coleta inválida.")

    domain = validate_domain(deploy.get("RADAR_DOMAIN", ""))
    validate_email(deploy.get("ACME_EMAIL", ""))
    if not valid_password_hash(_safe_private_file(root / "secrets" / "password_hash")):
        raise ValueError("Hash de login inválido.")
    if len(_safe_private_file(root / "secrets" / "session_secret")) < 32:
        raise ValueError("Segredo de sessão insuficiente.")
    return {"domain": domain, "user": app["LOGIN_USERNAME"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="LicitaRadar: configuração LOCAL protegida")
    parser.add_argument("action", choices=("init", "check"))
    parser.add_argument("--root", type=Path, default=Path("ops/runtime"))
    parser.add_argument("--domain")
    parser.add_argument("--email")
    parser.add_argument("--user", default="admin")
    args = parser.parse_args()
    if args.action == "init":
        if not args.domain or not args.email:
            parser.error("init requer --domain e --email")
        password = getpass.getpass("Nova senha do LicitaRadar (não será exibida): ")
        confirm = getpass.getpass("Repita a senha: ")
        if not secrets.compare_digest(password, confirm):
            parser.error("Senhas não coincidem.")
        initialize(args.root, args.domain, args.email, args.user, password)
    else:
        preflight(args.root)
    print("Preflight local PASS: configuração privada válida, sem executar deploy.")


if __name__ == "__main__":
    main()
