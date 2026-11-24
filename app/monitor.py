"""Monitor local de licitações com evidências PNCP e sem notificações externas.

Não declara competição, reabertura ou republicação como fatos provados.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, date, datetime

from .intelligence import CATEGORIES, classify
from .storage import connection

RULE_LIMIT = 20
FAVORITE_LIMIT = 100
HISTORY_LIMIT = 5000
CANDIDATE_DAYS = 365
KINDS = frozenset({"rule_match", "watched_change", "candidate_republication"})


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def normalize_description(value: str) -> str:
    lowered = unicodedata.normalize("NFKD", value.casefold())
    no_marks = "".join(char for char in lowered if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", no_marks))


def candidate_eligible(description: str) -> bool:
    normalized = normalize_description(description)
    return len(normalized) >= 18 and len(normalized.split()) >= 4


def _digest(parts: tuple[object, ...]) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def _notify(
    db, *, key: tuple[object, ...], kind: str, tender_id: str, numero: int,
    title: str, detail: str, created_at: str, source_tender_id: str | None = None,
    source_numero: int | None = None,
) -> None:
    if kind not in KINDS:
        raise ValueError("Tipo de alerta inválido.")
    db.execute("""
        INSERT OR IGNORE INTO monitor_alerts
          (dedupe_key,kind,tender_id,numero,source_tender_id,source_numero,
           title,detail,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        _digest(key), kind, tender_id, numero, source_tender_id, source_numero,
        title[:160], detail[:500], created_at,
    ))


def _matches_rule(rule, tender: dict, item: dict, status: int) -> bool:
    if status not in (1, 4, 5):
        return False
    if rule["uf"] and str(tender.get("uf") or "").upper() != rule["uf"]:
        return False
    if rule["status"] and status != rule["status"]:
        return False
    if rule["category"] and classify(str(item.get("descricao") or "")) != rule["category"]:
        return False
    description = normalize_description(str(item.get("descricao") or ""))
    object_text = normalize_description(str(tender.get("objeto") or ""))
    keyword = normalize_description(rule["keyword"])
    return bool(keyword and (keyword in description or keyword in object_text))


def observe_import(db, tender: dict, item: dict, previous_status: int | None,
                   observed_at: str) -> None:
    """Executado na mesma transação da importação de um item PNCP já persistido."""
    tender_id = str(tender["id"])
    numero = int(item["numeroItem"])
    status = int(item.get("situacaoCompraItemId") or 0)
    if status not in (1, 2, 3, 4, 5):
        status = 0
    description = str(item.get("descricao") or "")
    watching = db.execute(
        "SELECT 1 FROM monitor_favorites WHERE tender_id=? AND numero=?",
        (tender_id, numero),
    ).fetchone()
    if watching and previous_status is not None and status != previous_status:
        _notify(
            db, key=("watched_change", tender_id, numero, previous_status, status),
            kind="watched_change", tender_id=tender_id, numero=numero,
            title="Item acompanhado mudou de situação",
            detail=f"PNCP: {previous_status} → {status}. Confira o edital oficial.",
            created_at=observed_at,
        )

    if status in (1, 4, 5):
        rules = db.execute(
            "SELECT * FROM monitor_rules ORDER BY id LIMIT ?", (RULE_LIMIT,)
        ).fetchall()
        for rule in rules:
            if _matches_rule(rule, tender, item, status):
                _notify(
                    db, key=("rule_match", rule["id"], tender_id, numero, status),
                    kind="rule_match", tender_id=tender_id, numero=numero,
                    title="Nova correspondência de regra",
                    detail=f"Regra: {rule['keyword']}. Status PNCP {status}; confirme prazo e edital.",
                    created_at=observed_at,
                )

    # Indício conservador: mesmo órgão + descrição normalizada EXATA + quantidade,
    # em processo diferente publicado depois, com status antigo deserto/fracassado.
    if previous_status is not None or status != 1 or not candidate_eligible(description):
        return
    new_date_text = str(tender.get("data_publicacao") or "")[:10]
    try:
        new_date = date.fromisoformat(new_date_text)
    except ValueError:
        return
    if not 2021 <= new_date.year <= 2100:
        return

    older = db.execute("""
        SELECT i.tender_id, i.numero, i.descricao, i.quantidade, i.status,
               t.data_publicacao, t.link
        FROM items i JOIN tenders t ON t.id=i.tender_id
        WHERE t.cnpj=? AND i.tender_id<>? AND i.status IN (4,5)
          AND t.data_publicacao IS NOT NULL
          AND substr(t.data_publicacao,1,10) < ?
        ORDER BY t.data_publicacao DESC, i.tender_id, i.numero
        LIMIT 200
    """, (tender["cnpj"], tender_id, new_date.isoformat())).fetchall()

    for original in older:
        try:
            days = (new_date - date.fromisoformat(original["data_publicacao"][:10])).days
        except ValueError:
            continue
        if not 1 <= days <= CANDIDATE_DAYS:
            continue
        if normalize_description(original["descricao"]) != normalize_description(description):
            continue
        previous_quantity = original["quantidade"]
        current_quantity = item.get("quantidade")
        if previous_quantity is None or current_quantity is None:
            continue
        if abs(float(previous_quantity) - float(current_quantity)) > 1e-9:
            continue
        _notify(
            db, key=("candidate_republication", original["tender_id"],
                     original["numero"], tender_id, numero),
            kind="candidate_republication", tender_id=tender_id, numero=numero,
            source_tender_id=original["tender_id"], source_numero=original["numero"],
            title="Possível republicação (não confirmada)",
            detail=(
                "Mesmo órgão, descrição e quantidade em contratação distinta: "
                f"item anterior com status PNCP {original['status']}; "
                "novo item em andamento. É apenas coincidência verificável, "
                "não prova vínculo nem edital aberto agora."
            ),
            created_at=observed_at,
        )
        # Reduz spam: no máximo 3 possíveis itens anteriores por novo item.
        if db.execute(
            "SELECT COUNT(*) FROM monitor_alerts WHERE kind='candidate_republication' "
            "AND tender_id=? AND numero=?", (tender_id, numero)
        ).fetchone()[0] >= 3:
            break


def create_rule(path: str, keyword: str, uf: str = "", status: int = 0,
                category: str = "") -> int:
    keyword = " ".join(keyword.split())
    uf = uf.strip().upper()
    if not 3 <= len(keyword) <= 80 or not normalize_description(keyword):
        raise ValueError("Palavra-chave deve ter de 3 a 80 caracteres úteis.")
    if uf and not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF inválida.")
    if status not in (0, 1, 4, 5):
        raise ValueError("Situação não permitida para regra.")
    if category and category not in CATEGORIES:
        raise ValueError("Categoria inválida.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("""
            SELECT id FROM monitor_rules
            WHERE keyword=? COLLATE NOCASE AND uf=? AND status=? AND category=?
        """, (keyword, uf, status, category)).fetchone()
        if existing:
            return int(existing["id"])
        count = db.execute("SELECT COUNT(*) FROM monitor_rules").fetchone()[0]
        if count >= RULE_LIMIT:
            raise ValueError("Limite de 20 regras atingido.")
        cursor = db.execute("""
            INSERT INTO monitor_rules(keyword,uf,status,category,created_at)
            VALUES (?,?,?,?,?)
        """, (keyword, uf, status, category, stamp()))
        rule_id = int(cursor.lastrowid)
        rule = db.execute("SELECT * FROM monitor_rules WHERE id=?", (rule_id,)).fetchone()
        # Backfill limitado a 500 itens atuais recentes, sem afirmar cobertura exaustiva.
        rows = db.execute("""
            SELECT i.*, t.id, t.cnpj, t.objeto, t.uf, t.data_publicacao
            FROM items i JOIN tenders t ON t.id=i.tender_id
            WHERE i.status IN (1,4,5)
            ORDER BY t.data_publicacao DESC
            LIMIT 500
        """).fetchall()
        matched = 0
        for row in rows:
            item = dict(row)
            tender = {
                "uf": row["uf"], "objeto": row["objeto"],
            }
            if _matches_rule(rule, tender, item, int(row["status"])):
                _notify(
                    db, key=("rule_match", rule_id, item["tender_id"],
                             item["numero"], item["status"]),
                    kind="rule_match", tender_id=item["tender_id"],
                    numero=item["numero"], title="Correspondência inicial de regra",
                    detail=f"Regra: {keyword}. Encontrado entre itens já coletados; confirme publicação.",
                    created_at=stamp(),
                )
                matched += 1
                if matched >= 50:
                    break
        return rule_id


def delete_rule(path: str, rule_id: int) -> None:
    if rule_id <= 0:
        raise ValueError("Regra inválida.")
    with connection(path) as db:
        db.execute("DELETE FROM monitor_rules WHERE id=?", (rule_id,))


def change_favorite(path: str, tender_id: str, numero: int, add: bool) -> None:
    if not 1 <= len(tender_id) <= 180 or not 1 <= numero <= 100000:
        raise ValueError("Item inválido.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if not add:
            db.execute(
                "DELETE FROM monitor_favorites WHERE tender_id=? AND numero=?",
                (tender_id, numero),
            )
            return
        exists = db.execute(
            "SELECT 1 FROM items WHERE tender_id=? AND numero=?",
            (tender_id, numero),
        ).fetchone()
        if exists is None:
            raise ValueError("Item não encontrado no PNCP local.")
        count = db.execute("SELECT COUNT(*) FROM monitor_favorites").fetchone()[0]
        already = db.execute(
            "SELECT 1 FROM monitor_favorites WHERE tender_id=? AND numero=?",
            (tender_id, numero),
        ).fetchone()
        if count >= FAVORITE_LIMIT and not already:
            raise ValueError("Limite de 100 favoritos atingido.")
        db.execute("""
            INSERT OR IGNORE INTO monitor_favorites(tender_id,numero,created_at)
            VALUES (?,?,?)
        """, (tender_id, numero, stamp()))


def mark_read(path: str, alert_id: int) -> None:
    if alert_id <= 0:
        raise ValueError("Alerta inválido.")
    with connection(path) as db:
        db.execute(
            "UPDATE monitor_alerts SET read_at=? WHERE id=? AND read_at IS NULL",
            (stamp(), alert_id),
        )


def monitor_data(path: str, limit: int = 80) -> dict:
    limit = max(1, min(100, limit))
    with connection(path) as db:
        rules = [dict(r) for r in db.execute(
            "SELECT * FROM monitor_rules ORDER BY id DESC"
        )]
        favorites = [dict(r) for r in db.execute("""
            SELECT f.*, i.descricao, i.status, t.orgao, t.uf, t.municipio, t.link
            FROM monitor_favorites f
            JOIN items i ON i.tender_id=f.tender_id AND i.numero=f.numero
            JOIN tenders t ON t.id=f.tender_id
            ORDER BY f.created_at DESC LIMIT ?
        """, (FAVORITE_LIMIT,))]
        alerts = [dict(r) for r in db.execute("""
            SELECT a.*, i.descricao, t.link, t.uf, t.municipio,
                   old.link AS source_link
            FROM monitor_alerts a
            LEFT JOIN items i ON i.tender_id=a.tender_id AND i.numero=a.numero
            JOIN tenders t ON t.id=a.tender_id
            LEFT JOIN tenders old ON old.id=a.source_tender_id
            ORDER BY a.id DESC LIMIT ?
        """, (limit,))]
        unread = int(db.execute(
            "SELECT COUNT(*) FROM monitor_alerts WHERE read_at IS NULL"
        ).fetchone()[0])
    return {
        "rules": rules, "favorites": favorites, "alerts": alerts,
        "unread": unread, "total_alerts": len(alerts),
        "history_note": "Alertas gerados apenas a partir de itens efetivamente coletados.",
    }


def watched_keys(path: str, rows: list[dict]) -> set[tuple[str, int]]:
    if not rows:
        return set()
    with connection(path) as db:
        stored = db.execute(
            "SELECT tender_id,numero FROM monitor_favorites",
        ).fetchall()
    keys = {(r["tender_id"], r["numero"]) for r in stored}
    return keys & {(r["tender_id"], r["numero"]) for r in rows}


def unread_count(path: str) -> int:
    with connection(path) as db:
        return int(db.execute(
            "SELECT COUNT(*) FROM monitor_alerts WHERE read_at IS NULL"
        ).fetchone()[0])
