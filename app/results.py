"""Consulta manual de resultados de item PNCP, sem inferir licitantes participantes."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from .storage import connection

PNCP_RESULT_ROOT = "https://pncp.gov.br/api/pncp/v1/orgaos"
MAX_BODY_BYTES = 512 * 1024
MAX_RESULTS = 200
COOLDOWN_SECONDS = 60
MAX_NUMBER = Decimal(1000000000000)
FOUR = Decimal("0.0001")
RESULT_STATES = {0: "Situação desconhecida", 1: "Informado", 2: "Cancelado"}


class ResultFetchError(ValueError):
    def __init__(self, message: str, status_code: int = 503):
        self.status_code = status_code
        super().__init__(message)


def now_utc() -> datetime:
    return datetime.now(UTC)


def result_source_url(cnpj: str, year: int, sequence: int, number: int) -> str:
    if not re.fullmatch(r"[A-Z0-9]{14}", cnpj):
        raise ResultFetchError("Identificação PNCP do órgão inválida.", 422)
    if not 2021 <= year <= 2100 or not 1 <= sequence <= 100000000:
        raise ResultFetchError("Identificação PNCP da compra inválida.", 422)
    if not 1 <= number <= 100000:
        raise ResultFetchError("Número de item inválido.", 422)
    return (
        f"{PNCP_RESULT_ROOT}/{cnpj}/compras/{year}/{sequence}"
        f"/itens/{number}/resultados"
    )


def parse_decimal4(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ResultFetchError("Número retornado pelo PNCP é inválido.", 502)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ResultFetchError("Valor monetário PNCP inválido.", 502) from None
    if not result.is_finite() or result < 0 or result > MAX_NUMBER:
        raise ResultFetchError("Valor monetário fora de limites.", 502)
    try:
        quantized = result.quantize(FOUR)
    except InvalidOperation:
        raise ResultFetchError("Precisão decimal inválida.", 502) from None
    if result != quantized:
        raise ResultFetchError("PNCP retornou precisão superior a quatro casas.", 502)
    return format(quantized, ".4f")


def parse_result(raw: dict, number: int) -> dict:
    if not isinstance(raw, dict):
        raise ResultFetchError("Registro de resultado PNCP inválido.", 502)
    seq = raw.get("sequencialResultado")
    if isinstance(seq, bool) or not isinstance(seq, int) or not 1 <= seq <= 1000000:
        raise ResultFetchError("Sequencial do resultado inválido.", 502)
    item_number = raw.get("numeroItem")
    if item_number is not None and item_number != number:
        raise ResultFetchError("Resultado pertence a outro item.", 502)
    code = raw.get("situacaoCompraItemResultadoId")
    status = code if type(code) is int and code in (1, 2) else 0
    person_type = raw.get("tipoPessoa")
    if person_type not in (None, "PJ", "PF", "PE"):
        raise ResultFetchError("Tipo de fornecedor inválido.", 502)
    supplier = "Fornecedor não identificado no resultado"
    if person_type == "PJ":
        name = raw.get("nomeRazaoSocialFornecedor")
        if not isinstance(name, str) or len(name) > 100:
            raise ResultFetchError("Razão social do PNCP inválida.", 502)
        supplier = name.strip() or "Fornecedor PJ sem nome divulgado"
    elif person_type == "PF":
        supplier = "Pessoa física (identificação omitida)"
    elif person_type == "PE":
        supplier = "Fornecedor estrangeiro (identificação omitida)"
    ranking = raw.get("ordemClassificacaoSrp")
    if ranking is not None and (
        type(ranking) is not int or ranking < 1 or ranking > 100000
    ):
        raise ResultFetchError("Ordem SRP inválida.", 502)
    raw_date = raw.get("dataResultado")
    if raw_date is not None and (
        not isinstance(raw_date, str) or len(raw_date) > 35
    ):
        raise ResultFetchError("Data do resultado inválida.", 502)
    return {
        "seq": seq,
        "quantity": parse_decimal4(raw.get("quantidadeHomologada")),
        "unit_price": parse_decimal4(raw.get("valorUnitarioHomologado")),
        "supplier": supplier,
        "person_type": person_type if person_type in ("PJ", "PF", "PE") else "",
        "status": status,
        "ranking_srp": ranking,
        "result_date": raw_date,
    }


def parse_results(payload: object, number: int) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("listaResultados"), list):
        raise ResultFetchError("Resposta PNCP sem lista de resultados válida.", 502)
    rows = payload["listaResultados"]
    if len(rows) > MAX_RESULTS:
        raise ResultFetchError("Consulta excedeu o limite seguro de 200 resultados.", 502)
    results = [parse_result(raw, number) for raw in rows]
    if len({row["seq"] for row in results}) != len(results):
        raise ResultFetchError("PNCP retornou sequenciais duplicados.", 502)
    return results


def init_results(path: str) -> None:
    with connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS result_observations (
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('ok','empty','error')),
            checked_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            error_message TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(tender_id,numero)
        );
        CREATE TABLE IF NOT EXISTS item_official_results (
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            quantity TEXT,
            unit_price TEXT,
            supplier TEXT NOT NULL,
            person_type TEXT NOT NULL,
            status INTEGER NOT NULL,
            ranking_srp INTEGER,
            result_date TEXT,
            observed_at TEXT NOT NULL,
            PRIMARY KEY(tender_id,numero,seq)
        );
        CREATE INDEX IF NOT EXISTS idx_item_results_tender
            ON item_official_results(tender_id,numero,status);
        """)


def get_result_snapshot(path: str, tender_id: str, number: int) -> dict:
    with connection(path) as db:
        observation = db.execute("""
            SELECT * FROM result_observations WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
        rows = db.execute("""
            SELECT * FROM item_official_results WHERE tender_id=? AND numero=?
            ORDER BY seq LIMIT ?
        """, (tender_id, number, MAX_RESULTS)).fetchall()
    return {
        "observation": dict(observation) if observation else None,
        "results": [dict(row) for row in rows],
        "result_records": len(rows),
        "participant_count": None,
        "participant_count_source": "não fornecido por este endpoint",
    }


def _record_error(path: str, tender_id: str, number: int, source: str,
                  stamp: str, message: str) -> None:
    with connection(path) as db:
        db.execute("""
            INSERT INTO result_observations
                (tender_id,numero,state,checked_at,source_url,error_message)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(tender_id,numero) DO UPDATE SET
                state='error',checked_at=excluded.checked_at,
                source_url=excluded.source_url,error_message=excluded.error_message
        """, (tender_id, number, "error", stamp, source, message[:160]))


async def refresh_item_results(
    path: str, tender_id: str, number: int,
    transport: httpx.AsyncBaseTransport | None = None,
    now: datetime | None = None,
) -> dict:
    if not 1 <= len(tender_id) <= 180 or not 1 <= number <= 100000:
        raise ResultFetchError("Item inválido.", 422)
    with connection(path) as db:
        meta = db.execute("""
            SELECT t.cnpj,t.ano,t.sequencial FROM items i
            JOIN tenders t ON t.id=i.tender_id
            WHERE i.tender_id=? AND i.numero=?
        """, (tender_id, number)).fetchone()
        old = db.execute("""
            SELECT checked_at FROM result_observations
            WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
    if meta is None:
        raise ResultFetchError("Item não encontrado no radar.", 404)
    source = result_source_url(
        str(meta["cnpj"]), int(meta["ano"]), int(meta["sequencial"]), number
    )
    when = now or now_utc()
    if old:
        try:
            last = datetime.fromisoformat(old["checked_at"])
            if when - last < timedelta(seconds=COOLDOWN_SECONDS):
                raise ResultFetchError(
                    "Consulta recente. Tente novamente após 60 segundos.", 429
                )
        except ValueError:
            pass
    checked = when.isoformat()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False, trust_env=False, transport=transport,
        ) as client:
            response = await client.get(source, headers={"Accept": "application/json"})
        if response.status_code != 200:
            raise ResultFetchError(
                "PNCP não disponibilizou resultados nesta tentativa.", 503
            )
        if len(response.content) > MAX_BODY_BYTES:
            raise ResultFetchError("Resposta PNCP acima do limite permitido.", 502)
        parsed = parse_results(response.json(), number)
    except ResultFetchError as exc:
        _record_error(path, tender_id, number, source, checked, str(exc))
        raise
    except (httpx.HTTPError, ValueError, TypeError, UnicodeError):
        error = ResultFetchError(
            "PNCP indisponível ou resposta inválida. Snapshot anterior preservado.", 503
        )
        _record_error(path, tender_id, number, source, checked, str(error))
        raise error from None

    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        # Um snapshot completo 200 + validação substitui todos os resultados anteriores.
        db.execute(
            "DELETE FROM item_official_results WHERE tender_id=? AND numero=?",
            (tender_id, number),
        )
        for row in parsed:
            db.execute("""
                INSERT INTO item_official_results (
                    tender_id,numero,seq,quantity,unit_price,supplier,person_type,
                    status,ranking_srp,result_date,observed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                tender_id, number, row["seq"], row["quantity"], row["unit_price"],
                row["supplier"], row["person_type"], row["status"],
                row["ranking_srp"], row["result_date"], checked,
            ))
        db.execute("""
            INSERT INTO result_observations
                (tender_id,numero,state,checked_at,source_url,error_message)
            VALUES (?,?,?,?,?,'')
            ON CONFLICT(tender_id,numero) DO UPDATE SET
                state=excluded.state,checked_at=excluded.checked_at,
                source_url=excluded.source_url,error_message=''
        """, (tender_id, number, "ok" if parsed else "empty", checked, source))
    return get_result_snapshot(path, tender_id, number)
