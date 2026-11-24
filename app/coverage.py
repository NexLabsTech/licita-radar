"""Coleta PNCP por lotes retomáveis, com filtro de município IBGE comprovável."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime

import httpx

from .pncp import CONSULTA, PNCPError, _json, fetch_items, normalize_tender
from .storage import connection, record_sync, upsert_tender

PAGE_SIZE = 20
PAGES_PER_STEP = 2
MAX_JOBS = 20
MAX_BODY_ITEMS = PAGE_SIZE


class CoverageError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def init_coverage(path: str) -> None:
    with connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS coverage_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            uf TEXT NOT NULL,
            modality INTEGER NOT NULL CHECK(modality IN (6,8)),
            municipality_ibge TEXT NOT NULL,
            next_page INTEGER NOT NULL DEFAULT 1 CHECK(next_page >= 1),
            processed_pages INTEGER NOT NULL DEFAULT 0,
            fetched INTEGER NOT NULL DEFAULT 0,
            material_items INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'paused'
                CHECK(state IN ('paused','completed','error')),
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_coverage_jobs_new
            ON coverage_jobs(id DESC);
        """)


def validate_params(start: date, end: date, uf: str,
                    modality: int, municipality_ibge: str) -> tuple[str, str]:
    if start.year < 2021 or start > date.today() or end > date.today():
        raise CoverageError("Datas fora do período de publicações permitidas.")
    if end < start or (end - start).days > 6:
        raise CoverageError("Escolha um período de 1 a 7 dias.")
    state = uf.strip().upper()
    if state and not re.fullmatch(r"[A-Z]{2}", state):
        raise CoverageError("UF deve ter exatamente duas letras.")
    city = municipality_ibge.strip()
    if city and not re.fullmatch(r"\d{7}", city):
        raise CoverageError("Código IBGE deve ter 7 dígitos, sem pontuação.")
    if modality not in (6, 8):
        raise CoverageError("Modalidade PNCP não suportada.")
    return state, city


def create_job(path: str, start: date, end: date, uf: str,
               modality: int, municipality_ibge: str = "") -> int:
    state, city = validate_params(start, end, uf, modality, municipality_ibge)
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT COUNT(*) FROM coverage_jobs").fetchone()[0]
        if count >= MAX_JOBS:
            raise CoverageError("Limite de 20 pesquisas. Termine as existentes antes de criar outras.")
        moment = _stamp()
        cursor = db.execute("""
            INSERT INTO coverage_jobs (
                start_date,end_date,uf,modality,municipality_ibge,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?)
        """, (start.isoformat(), end.isoformat(), state, modality, city, moment, moment))
        return int(cursor.lastrowid)


def _get_job(path: str, job_id: int) -> dict:
    if job_id <= 0:
        raise CoverageError("Pesquisa inválida.")
    with connection(path) as db:
        row = db.execute(
            "SELECT * FROM coverage_jobs WHERE id=?", (job_id,)
        ).fetchone()
    if row is None:
        raise CoverageError("Pesquisa não encontrada.", 404)
    return dict(row)


def coverage_jobs(path: str) -> list[dict]:
    with connection(path) as db:
        rows = db.execute(
            "SELECT * FROM coverage_jobs ORDER BY id DESC LIMIT ?",
            (MAX_JOBS,),
        ).fetchall()
    return [dict(row) for row in rows]


def _persist_progress(path: str, job_id: int, page: int, processed: int,
                      fetched: int, items: int, state: str, detail: str,
                      errors: int = 0) -> None:
    if state not in ("paused", "completed", "error"):
        raise ValueError("Estado da coleta inválido.")
    with connection(path) as db:
        db.execute("""
            UPDATE coverage_jobs SET
              next_page=?,processed_pages=processed_pages+?,
              fetched=fetched+?,material_items=material_items+?,
              errors=errors+?,state=?,detail=?,updated_at=?
            WHERE id=?
        """, (page, processed, fetched, items, errors,
              state, detail[:240], _stamp(), job_id))


def _page_rows(payload: object) -> tuple[list, bool]:
    if not isinstance(payload, dict):
        raise PNCPError("Resposta PNCP sem envelope de publicações.")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) > MAX_BODY_ITEMS:
        raise PNCPError("Página de publicações incompleta ou acima do limite.")
    remaining = payload.get("paginasRestantes")
    if remaining is not None and (
        type(remaining) is not int or remaining < 0 or remaining > 100000
    ):
        raise PNCPError("Metadados de paginação inválidos.")
    if any(not isinstance(row, dict) for row in rows):
        raise PNCPError("Contratação com formato inesperado.")
    # Metadado explícito ou página curta provam fim da listagem para o filtro.
    finished = (remaining == 0) or len(rows) < PAGE_SIZE
    return rows, finished


async def next_step(
    path: str, job_id: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """At most 2 x 20 publicações; de novo somente mediante ação do usuário."""
    job = _get_job(path, job_id)
    if job["state"] == "completed":
        return job
    page = int(job["next_page"])
    processed = fetched = products = errors = 0
    state = "paused"
    detail = "Parcial: continue para consultar páginas seguintes."
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False, trust_env=False, transport=transport,
        ) as client:
            for _ in range(PAGES_PER_STEP):
                params = {
                    "dataInicial": job["start_date"].replace("-", ""),
                    "dataFinal": job["end_date"].replace("-", ""),
                    "codigoModalidadeContratacao": job["modality"],
                    "pagina": page, "tamanhoPagina": PAGE_SIZE,
                }
                if job["uf"]:
                    params["uf"] = job["uf"]
                if job["municipality_ibge"]:
                    params["codigoMunicipioIbge"] = job["municipality_ibge"]
                payload = await _json(client, CONSULTA, params)
                rows, finished = _page_rows(payload)
                # Pré-busque todos os itens antes de avançar o cursor da página.
                complete = []
                seen_ids = set()
                for raw in rows:
                    tender = normalize_tender(raw)
                    if tender["id"] in seen_ids:
                        continue
                    seen_ids.add(tender["id"])
                    # Se o PNCP/órgão devolver órgão de outra UF, não rotular
                    # a coleta como cobrindo integralmente o filtro requisitado.
                    if job["uf"] and tender["uf"] != job["uf"]:
                        raise PNCPError("PNCP retornou item fora da UF solicitada.")
                    items = await fetch_items(client, tender)
                    complete.append((tender, items))
                imported = 0
                for tender, items in complete:
                    imported += upsert_tender(path, tender, items)
                fetched += len(complete)
                products += imported
                processed += 1
                page += 1
                if finished:
                    state = "completed"
                    detail = "Páginas finalizadas conforme resposta da API do PNCP."
                    break
    except (PNCPError, httpx.HTTPError, ValueError, TypeError, OverflowError) as exc:
        errors = 1
        state = "error"
        detail = "Erro na página " + str(page) + ": " + type(exc).__name__
    _persist_progress(
        path, job_id, page, processed, fetched, products, state, detail, errors,
    )
    record_sync(path, fetched, products, errors, detail)
    return _get_job(path, job_id)
