"""Banco SQLite local e importação idempotente de itens de material."""
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .intelligence import classify

STATUSES = {1: "Em andamento", 2: "Homologado", 3: "Cancelado", 4: "Deserto", 5: "Fracassado"}


@contextmanager
def connection(path: str):
    """Transação com commit/rollback e fechamento garantido do SQLite."""
    db = sqlite3.connect(path, timeout=15)
    try:
        db.row_factory = sqlite3.Row
        db.create_function("lr_category", 1, classify, deterministic=True)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tenders (
            id TEXT PRIMARY KEY,
            cnpj TEXT NOT NULL,
            ano INTEGER NOT NULL,
            sequencial INTEGER NOT NULL,
            orgao TEXT NOT NULL,
            municipio TEXT NOT NULL,
            uf TEXT NOT NULL,
            objeto TEXT NOT NULL,
            data_publicacao TEXT,
            abertura TEXT,
            encerramento TEXT,
            link TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS items (
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            quantidade REAL,
            valor_total REAL,
            status INTEGER NOT NULL,
            atualizado_pncp TEXT,
            coletado_em TEXT NOT NULL,
            PRIMARY KEY(tender_id, numero)
        );
        CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
        CREATE INDEX IF NOT EXISTS idx_tenders_uf ON tenders(uf);
        CREATE TABLE IF NOT EXISTS item_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            previous_status INTEGER,
            current_status INTEGER NOT NULL,
            changed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_item_events_recent ON item_events(id DESC);
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            fetched INTEGER NOT NULL,
            material_items INTEGER NOT NULL,
            errors INTEGER NOT NULL,
            details TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monitor_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL COLLATE NOCASE,
            uf TEXT NOT NULL DEFAULT '',
            status INTEGER NOT NULL DEFAULT 0 CHECK(status IN (0,1,4,5)),
            category TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(keyword,uf,status,category)
        );
        CREATE TABLE IF NOT EXISTS monitor_favorites (
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(tender_id,numero)
        );
        CREATE TABLE IF NOT EXISTS monitor_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedupe_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK(kind IN ('rule_match','watched_change','candidate_republication')),
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            source_tender_id TEXT,
            source_numero INTEGER,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_monitor_alerts_unread
            ON monitor_alerts(read_at,id DESC);
        CREATE INDEX IF NOT EXISTS idx_monitor_favorites_tender
            ON monitor_favorites(tender_id,numero);
        """)


def upsert_tender(path: str, tender: dict, items: list[dict]) -> int:
    """Atualiza a compra e itens somente após obter a lista de itens completa."""
    stamp = datetime.now(UTC).isoformat()
    valid = [item for item in items if item.get("materialOuServico") == "M"]
    with connection(path) as db:
        db.execute("""
        INSERT INTO tenders
            (id,cnpj,ano,sequencial,orgao,municipio,uf,objeto,data_publicacao,
             abertura,encerramento,link,atualizado_em)
        VALUES (:id,:cnpj,:ano,:sequencial,:orgao,:municipio,:uf,:objeto,
                :data_publicacao,:abertura,:encerramento,:link,:atualizado_em)
        ON CONFLICT(id) DO UPDATE SET
            orgao=excluded.orgao, municipio=excluded.municipio, uf=excluded.uf,
            objeto=excluded.objeto, data_publicacao=excluded.data_publicacao,
            abertura=excluded.abertura, encerramento=excluded.encerramento,
            link=excluded.link, atualizado_em=excluded.atualizado_em
        """, {**tender, "atualizado_em": stamp})
        previous = {
            row["numero"]: row["status"]
            for row in db.execute(
                "SELECT numero,status FROM items WHERE tender_id = ?", (tender["id"],))
        }
        db.execute("DELETE FROM items WHERE tender_id = ?", (tender["id"],))
        from .monitor import observe_import

        for item in valid:
            status = int(item.get("situacaoCompraItemId") or 0)
            if status not in STATUSES:
                status = 0
            old_status = previous.get(int(item["numeroItem"]))
            if old_status != status and (old_status is not None or status in (4, 5)):
                db.execute("""
                    INSERT INTO item_events
                    (tender_id,numero,descricao,previous_status,current_status,changed_at)
                    VALUES (?,?,?,?,?,?)
                """, (
                    tender["id"], int(item["numeroItem"]),
                    str(item.get("descricao") or ""), old_status, status, stamp
                ))
            confidential = item.get("orcamentoSigiloso") is True
            db.execute("""
            INSERT INTO items
                (tender_id,numero,descricao,quantidade,valor_total,status,
                 atualizado_pncp,coletado_em)
            VALUES (?,?,?,?,?,?,?,?)
            """, (
                tender["id"], int(item["numeroItem"]), str(item.get("descricao") or ""),
                item.get("quantidade"), None if confidential else item.get("valorTotal"),
                status, item.get("dataAtualizacao"), stamp
            ))
            # Notificação e dados PNCP na MESMA transação: rollback em falha.
            observe_import(db, tender, item, old_status, stamp)
    return len(valid)


def list_items(path: str, q: str = "", uf: str = "", status: int = 0,
               page: int = 1, category: str = ""):
    predicates, values = [], []
    if q:
        predicates.append("(i.descricao LIKE ? ESCAPE '\\' OR t.objeto LIKE ? ESCAPE '\\' OR t.municipio LIKE ? ESCAPE '\\')")
        safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.extend([f"%{safe}%"] * 3)
    if uf:
        predicates.append("t.uf = ?")
        values.append(uf)
    if status in STATUSES:
        predicates.append("i.status = ?")
        values.append(status)
    if category:
        predicates.append("lr_category(i.descricao) = ?")
        values.append(category)
    where = (" WHERE " + " AND ".join(predicates)) if predicates else ""
    with connection(path) as db:
        total = db.execute("SELECT COUNT(*) FROM items i JOIN tenders t ON t.id=i.tender_id" + where, values).fetchone()[0]
        rows = db.execute("""
        SELECT i.*,t.orgao,t.municipio,t.uf,t.objeto,t.link,t.encerramento,t.data_publicacao
        FROM items i JOIN tenders t ON t.id=i.tender_id
        """ + where + " ORDER BY t.data_publicacao DESC, i.tender_id, i.numero LIMIT 25 OFFSET ?",
                          values + [(page - 1) * 25]).fetchall()
        counts = {int(row["status"]): row["total"] for row in db.execute(
            "SELECT status, COUNT(*) AS total FROM items GROUP BY status")}
        latest = db.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    return [dict(r) for r in rows], total, counts, dict(latest) if latest else None


def record_sync(path: str, fetched: int, material_items: int, errors: int, details: str):
    with connection(path) as db:
        db.execute(
            "INSERT INTO sync_runs(started_at,fetched,material_items,errors,details) VALUES (?,?,?,?,?)",
            (datetime.now(UTC).isoformat(), fetched, material_items, errors, details[:500]))


def recent_events(path: str, limit: int = 15) -> list[dict]:
    """Somente transições registradas de itens; eventos não são provas de republicação."""
    with connection(path) as db:
        rows = db.execute("""
            SELECT e.*, t.orgao, t.municipio, t.uf, t.link
            FROM item_events e JOIN tenders t ON t.id=e.tender_id
            ORDER BY e.id DESC LIMIT ?
        """, (max(1, min(100, limit)),)).fetchall()
    return [dict(row) for row in rows]
