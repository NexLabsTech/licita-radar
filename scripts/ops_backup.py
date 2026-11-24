"""Online SQLite backups, integrity verification and non-destructive recovery.

Backup files contain PRIVATE user quotes and AI reports. Store only in private volumes.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import signal
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

BACKUP_PATTERN = re.compile(r"^licitaradar-\d{8}T\d{6}Z-[0-9a-f]{8}\.sqlite3$")
EXPECTED_TABLES = {"tenders", "items", "item_quotes", "ai_calls", "ai_cache"}


def verify_sqlite(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Arquivo de banco ausente ou não regular.")
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=15)) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise ValueError("Falha de integridade do banco.")
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not EXPECTED_TABLES.issubset(tables):
            raise ValueError("Backup não contém o esquema esperado do LicitaRadar.")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(
    db_path: str | Path,
    directory: str | Path,
    keep: int = 7,
    when: datetime | None = None,
) -> Path:
    if not 1 <= keep <= 30:
        raise ValueError("Retenção deve estar entre 1 e 30 arquivos.")
    source = Path(db_path)
    destination_dir = Path(directory)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Banco de origem ausente ou não regular.")
    if destination_dir.is_symlink():
        raise ValueError("Diretório de backup não pode ser link simbólico.")
    destination_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = (when or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = destination_dir / f"licitaradar-{stamp}-{secrets.token_hex(4)}.sqlite3"
    fd, temp_path = tempfile.mkstemp(prefix=".lr-backup-", suffix=".tmp", dir=destination_dir)
    os.close(fd)
    temporary = Path(temp_path)
    try:
        os.chmod(temporary, 0o600)
        source_uri = source.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True, timeout=20)) as read_db,
            closing(sqlite3.connect(temporary, timeout=20)) as write_db,
        ):
            read_db.backup(write_db, pages=128, sleep=0.05)
        verify_sqlite(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        # Só removemos arquivos com nome canônico, e somente após um novo backup validado.
        backups = sorted(
            (p for p in destination_dir.iterdir()
             if p.is_file() and not p.is_symlink() and BACKUP_PATTERN.fullmatch(p.name)),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
        for obsolete in backups[keep:]:
            obsolete.unlink()
        return target
    finally:
        temporary.unlink(missing_ok=True)


def restore_to_new_file(backup_path: str | Path, new_path: str | Path) -> Path:
    """Nunca substitui um DB existente; operador deve parar containers para troca real."""
    source = Path(backup_path)
    target = Path(new_path)
    verify_sqlite(source)
    if target.is_symlink() or target.exists():
        raise FileExistsError("Destino já existe; restauração destrutiva é proibida.")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("O diretório de destino deve existir e ser confiável.")
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True, timeout=20)) as read_db,
            closing(sqlite3.connect(target, timeout=20)) as restored,
        ):
            read_db.backup(restored)
        verify_sqlite(target)
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def run_loop(db: str, directory: str, keep: int, hours: int) -> None:
    if not 1 <= hours <= 48:
        raise ValueError("Intervalo permitido: 1 a 48 horas.")
    stop = threading.Event()

    def shutdown(_signal: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while not stop.is_set():
        try:
            backup = backup_database(db, directory, keep)
            print(f"Backup SQLite OK: {backup.name} sha256={file_sha256(backup)}", flush=True)
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            print(f"Backup SQLite FAILED: {type(exc).__name__}", flush=True)
        stop.wait(hours * 3600)


def main() -> None:
    parser = argparse.ArgumentParser(description="LicitaRadar: recuperação SQLite privada")
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ("once", "loop"):
        sub = commands.add_parser(action)
        sub.add_argument("--db", required=True)
        sub.add_argument("--dir", required=True)
        sub.add_argument("--keep", type=int, default=7)
        if action == "loop":
            sub.add_argument("--interval-hours", type=int, default=24)
    verify = commands.add_parser("verify")
    verify.add_argument("--source", required=True)
    restore = commands.add_parser("restore-new")
    restore.add_argument("--source", required=True)
    restore.add_argument("--dest", required=True)
    args = parser.parse_args()

    if args.command == "once":
        created = backup_database(args.db, args.dir, args.keep)
        print(f"Backup OK: {created.name} sha256={file_sha256(created)}")
    elif args.command == "loop":
        run_loop(args.db, args.dir, args.keep, args.interval_hours)
    elif args.command == "verify":
        target = Path(args.source)
        verify_sqlite(target)
        print(f"Arquivo OK sha256={file_sha256(target)}")
    elif args.command == "restore-new":
        created = restore_to_new_file(args.source, args.dest)
        print(f"Restauração em NOVO arquivo OK: {created.name}")


if __name__ == "__main__":
    main()
