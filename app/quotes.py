"""Cotações privadas informadas pelo usuário, preservadas entre reimportações PNCP."""
from datetime import UTC, datetime

from .intelligence import item_fingerprint
from .storage import connection


def init_quotes(path: str) -> None:
    with connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS item_quotes (
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            supplier TEXT NOT NULL,
            unit_cost TEXT NOT NULL,
            freight TEXT NOT NULL,
            packaging TEXT NOT NULL,
            other TEXT NOT NULL,
            risk_reserve TEXT NOT NULL,
            tax_percent TEXT NOT NULL,
            target_margin TEXT NOT NULL,
            item_fingerprint TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (tender_id, numero)
        );
        """)


def get_item(path: str, tender_id: str, numero: int) -> dict | None:
    with connection(path) as db:
        row = db.execute("""
            SELECT i.*, t.orgao, t.municipio, t.uf, t.objeto, t.link,
                   t.encerramento, t.data_publicacao
            FROM items i JOIN tenders t ON t.id=i.tender_id
            WHERE i.tender_id=? AND i.numero=?
        """, (tender_id, numero)).fetchone()
    return dict(row) if row else None


def get_quote(path: str, tender_id: str, numero: int) -> dict | None:
    with connection(path) as db:
        row = db.execute("""
            SELECT * FROM item_quotes WHERE tender_id=? AND numero=?
        """, (tender_id, numero)).fetchone()
    return dict(row) if row else None


def get_quotes_for_items(path: str, items: list[dict]) -> dict[tuple[str, int], dict]:
    """Busca única por página: nunca mistura cotações entre diferentes compras."""
    if not items:
        return {}
    conditions = " OR ".join("(tender_id=? AND numero=?)" for _ in items)
    params = [value for item in items for value in (item["tender_id"], item["numero"])]
    with connection(path) as db:
        rows = db.execute(
            "SELECT * FROM item_quotes WHERE " + conditions, params
        ).fetchall()
    return {(row["tender_id"], row["numero"]): dict(row) for row in rows}


def save_quote(path: str, tender_id: str, numero: int,
               values: dict[str, str]) -> None:
    """Snapshot do item + cotação na mesma transação; falha se item foi removido."""
    with connection(path) as db:
        item = db.execute("""
            SELECT descricao, quantidade FROM items
            WHERE tender_id=? AND numero=?
        """, (tender_id, numero)).fetchone()
        if item is None:
            raise ValueError("Item não encontrado. Atualize o radar e tente novamente.")
        fingerprint = item_fingerprint(item["descricao"], item["quantidade"])
        db.execute("""
            INSERT INTO item_quotes
                (tender_id,numero,supplier,unit_cost,freight,packaging,other,
                 risk_reserve,tax_percent,target_margin,item_fingerprint,updated_at)
            VALUES (:tender_id,:numero,:supplier,:unit_cost,:freight,:packaging,
                    :other,:risk_reserve,:tax_percent,:target_margin,
                    :item_fingerprint,:updated_at)
            ON CONFLICT(tender_id,numero) DO UPDATE SET
                supplier=excluded.supplier, unit_cost=excluded.unit_cost,
                freight=excluded.freight, packaging=excluded.packaging,
                other=excluded.other, risk_reserve=excluded.risk_reserve,
                tax_percent=excluded.tax_percent,
                target_margin=excluded.target_margin,
                item_fingerprint=excluded.item_fingerprint,
                updated_at=excluded.updated_at
        """, {**values, "tender_id": tender_id, "numero": numero,
              "item_fingerprint": fingerprint,
              "updated_at": datetime.now(UTC).isoformat()})
