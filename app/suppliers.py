"""Múltiplas fontes de preço registradas pelo usuário; nenhuma busca remota nem lance."""
from __future__ import annotations

import ipaddress
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from .intelligence import analyze, item_fingerprint, validate_quote
from .quotes import get_quote
from .storage import connection

MAX_OFFERS_PER_ITEM = 12
MONEY_FIELDS = (
    "supplier", "unit_cost", "freight", "packaging", "other",
    "risk_reserve", "tax_percent", "target_margin",
)


class SupplierError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def validate_source_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    if len(value) > 550 or any(char.isspace() for char in value):
        raise SupplierError("URL de origem inválida ou muito longa.")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise SupplierError("URL de origem inválida.") from None
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise SupplierError("Fonte deve ser HTTPS público e sem credenciais.")
    if port not in (None, 443):
        raise SupplierError("A fonte HTTPS deve usar porta padrão.")
    if host.endswith((".local", ".internal", ".test", ".invalid", ".localhost")):
        raise SupplierError("Endereço interno não permitido como fonte.")
    if host.lower() == "localhost" or not re.fullmatch(
        r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
        r"[a-zA-Z]{2,63}", host,
    ):
        raise SupplierError("Informe um domínio HTTPS público válido.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SupplierError("URLs por IP não são permitidas.")
    return value


def validate_source_date(value: str) -> str:
    if len(value) != 10:
        raise SupplierError("Informe a data da cotação (AAAA-MM-DD).")
    try:
        observed = date.fromisoformat(value)
    except ValueError:
        raise SupplierError("Data da cotação inválida.") from None
    if not 2021 <= observed.year <= 2100 or observed > date.today():
        raise SupplierError("Data da cotação fora dos limites.")
    return observed.isoformat()


def init_suppliers(path: str) -> None:
    with connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS supplier_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            source_url TEXT NOT NULL DEFAULT '',
            observed_on TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_supplier_offers_item
            ON supplier_offers(tender_id,numero,id DESC);
        """)


def _validate_ref(tender_id: str, number: int) -> None:
    if not 1 <= len(tender_id) <= 180 or not 1 <= number <= 100000:
        raise SupplierError("Item inválido.")


def add_offer(
    path: str, tender_id: str, number: int, fields: dict,
    observed_on: str, source_url: str = "", note: str = "",
) -> int:
    _validate_ref(tender_id, number)
    try:
        values = validate_quote(fields)
    except ValueError as exc:
        raise SupplierError(str(exc)) from None
    verified_date = validate_source_date(observed_on)
    verified_url = validate_source_url(source_url)
    if len(note) > 250:
        raise SupplierError("Nota do fornecedor não pode ultrapassar 250 caracteres.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("""
            SELECT descricao,quantidade FROM items
            WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
        if current is None:
            raise SupplierError("Item não encontrado na base PNCP.", 404)
        count = db.execute("""
            SELECT COUNT(*) FROM supplier_offers WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()[0]
        if count >= MAX_OFFERS_PER_ITEM:
            raise SupplierError("Limite de 12 cotações por item atingido.")
        cursor = db.execute("""
            INSERT INTO supplier_offers
              (tender_id,numero,supplier,unit_cost,freight,packaging,other,
               risk_reserve,tax_percent,target_margin,item_fingerprint,
               source_url,observed_on,note,created_at)
            VALUES (:tender_id,:numero,:supplier,:unit_cost,:freight,:packaging,
                    :other,:risk_reserve,:tax_percent,:target_margin,:item_fingerprint,
                    :source_url,:observed_on,:note,:created_at)
        """, {
            **values, "tender_id": tender_id, "numero": number,
            "item_fingerprint": item_fingerprint(
                current["descricao"], current["quantidade"],
            ),
            "source_url": verified_url, "observed_on": verified_date,
            "note": note.strip(), "created_at": _stamp(),
        })
        return int(cursor.lastrowid)


def get_offers(path: str, tender_id: str, number: int) -> list[dict]:
    _validate_ref(tender_id, number)
    with connection(path) as db:
        rows = db.execute("""
            SELECT * FROM supplier_offers
            WHERE tender_id=? AND numero=?
            ORDER BY id DESC LIMIT ?
        """, (tender_id, number, MAX_OFFERS_PER_ITEM)).fetchall()
    return [dict(row) for row in rows]


def compare_offers(path: str, item: dict) -> list[dict]:
    offers = get_offers(path, item["tender_id"], item["numero"])
    active = get_quote(path, item["tender_id"], item["numero"])
    comparisons = []
    for offer in offers:
        report = analyze(item, offer)
        selected = (
            active is not None
            and all(str(active.get(key)) == str(offer.get(key)) for key in MONEY_FIELDS)
            and active.get("item_fingerprint") == offer.get("item_fingerprint")
        )
        comparisons.append({
            **offer, "analysis": report, "active": selected,
        })
    # Ordenar apenas por custo TOTAL válido; obsoletas/inválidas sempre depois.
    comparisons.sort(key=lambda entry: (
        entry["analysis"]["total_cost"] is None,
        Decimal(entry["analysis"]["total_cost"])
        if entry["analysis"]["total_cost"] is not None else Decimal(0),
        entry["id"],
    ))
    return comparisons


def promote_offer(path: str, tender_id: str, number: int, offer_id: int) -> None:
    """Seleção explícita; não adota oferta com descrição/quantidade PNCP alterada."""
    _validate_ref(tender_id, number)
    if offer_id <= 0:
        raise SupplierError("Cotação inválida.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        offer = db.execute("""
            SELECT * FROM supplier_offers
            WHERE id=? AND tender_id=? AND numero=?
        """, (offer_id, tender_id, number)).fetchone()
        current = db.execute("""
            SELECT descricao, quantidade FROM items
            WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
        if current is None or offer is None:
            raise SupplierError("Cotação ou item não encontrado.", 404)
        fingerprint = item_fingerprint(current["descricao"], current["quantidade"])
        if offer["item_fingerprint"] != fingerprint:
            raise SupplierError(
                "Cotação desatualizada após alteração do item PNCP. Cadastre uma nova."
            )
        # Valida novamente os dados lidos do banco antes de ativá-los.
        try:
            values = validate_quote(dict(offer))
        except ValueError:
            raise SupplierError("Cotação registrada inválida.") from None
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
                tax_percent=excluded.tax_percent, target_margin=excluded.target_margin,
                item_fingerprint=excluded.item_fingerprint,updated_at=excluded.updated_at
        """, {
            **values, "tender_id": tender_id, "numero": number,
            "item_fingerprint": fingerprint, "updated_at": _stamp(),
        })


def remove_offer(path: str, tender_id: str, number: int, offer_id: int) -> None:
    _validate_ref(tender_id, number)
    if offer_id <= 0:
        raise SupplierError("Cotação inválida.")
    with connection(path) as db:
        db.execute("""
            DELETE FROM supplier_offers WHERE id=? AND tender_id=? AND numero=?
        """, (offer_id, tender_id, number))
    # Se esta cotação era principal, o snapshot principal fica preservado para revisão.
