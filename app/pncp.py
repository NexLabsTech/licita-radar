"""Cliente oficial PNCP; consultas limitadas, sem scraping ou credenciais."""
import re
from datetime import date

import httpx

from .storage import record_sync, upsert_tender

CONSULTA = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
ITENS_BASE = "https://pncp.gov.br/api/pncp/v1/orgaos"
MAX_PUBLICATION_PAGES = 2
MAX_ITEM_PAGES = 5


class PNCPError(Exception):
    pass


async def _json(client: httpx.AsyncClient, url: str, params: dict) -> dict | list:
    try:
        response = await client.get(url, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PNCPError("Falha na consulta ao PNCP: " + type(exc).__name__) from exc
    if not isinstance(data, (dict, list)):
        raise PNCPError("Formato de resposta PNCP inválido.")
    return data


def normalize_tender(raw: dict) -> dict:
    cnpj = str((raw.get("orgaoEntidade") or {}).get("cnpj") or "").upper()
    ano = int(raw.get("anoCompra") or 0)
    seq = int(raw.get("sequencialCompra") or 0)
    if not re.fullmatch("[A-Z0-9]{14}", cnpj) or not 2021 <= ano <= 2100 or seq < 1:
        raise PNCPError("Identificação PNCP incompleta.")
    controle = str(raw.get("numeroControlePNCP") or "")
    if not controle:
        raise PNCPError("Identificador PNCP não informado.")
    unidade = raw.get("unidadeOrgao") or {}
    orgao = raw.get("orgaoEntidade") or {}
    return {
        "id": controle,
        "cnpj": cnpj,
        "ano": ano,
        "sequencial": seq,
        "orgao": str(orgao.get("razaoSocial") or ""),
        "municipio": str(unidade.get("municipioNome") or ""),
        "uf": str(unidade.get("ufSigla") or "").upper()[:2],
        "objeto": str(raw.get("objetoCompra") or ""),
        "data_publicacao": raw.get("dataPublicacaoPncp"),
        "abertura": raw.get("dataAberturaProposta"),
        "encerramento": raw.get("dataEncerramentoProposta"),
        "link": f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}",
    }


async def fetch_items(client: httpx.AsyncClient, tender: dict) -> list[dict]:
    url = f"{ITENS_BASE}/{tender['cnpj']}/compras/{tender['ano']}/{tender['sequencial']}/itens"
    collected: list[dict] = []
    for page in range(1, MAX_ITEM_PAGES + 1):
        raw = await _json(client, url, {"pagina": page, "tamanhoPagina": 100})
        if isinstance(raw, list):
            current = raw
            total_pages = None
        else:
            current = raw.get("itens")
            total_pages = raw.get("totalPaginas")
        if not isinstance(current, list):
            raise PNCPError("Itens ausentes ou incompletos.")
        if any(not isinstance(item, dict) for item in current):
            raise PNCPError("Formato de item inválido.")
        collected.extend(current)
        if total_pages is not None and page >= int(total_pages):
            return collected
        if len(current) < 100:
            return collected
    raise PNCPError("Mais de 500 itens: importação interrompida para não salvar dados parciais.")


async def sync_pncp(path: str, start: date, end: date, uf: str, modality: int,
                    transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if end < start or (end - start).days > 6:
        raise ValueError("Período permitido: até 7 dias.")
    if uf and not re.fullmatch("[A-Z]{2}", uf):
        raise ValueError("UF inválida.")
    if modality not in (6, 8):
        raise ValueError("Modalidade inválida.")
    fetched, products, errors = 0, 0, 0
    seen: set[str] = set()
    detail = "Concluído."
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=False,
                                 transport=transport) as client:
        try:
            for page in range(1, MAX_PUBLICATION_PAGES + 1):
                params = {
                    "dataInicial": start.strftime("%Y%m%d"),
                    "dataFinal": end.strftime("%Y%m%d"),
                    "codigoModalidadeContratacao": modality,
                    "pagina": page,
                    "tamanhoPagina": 10,
                }
                if uf:
                    params["uf"] = uf
                payload = await _json(client, CONSULTA, params)
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise PNCPError("Resposta de publicações sem a lista 'data'.")
                rows = payload["data"]
                for raw in rows:
                    fetched += 1
                    try:
                        if not isinstance(raw, dict):
                            raise PNCPError("Contratação inválida.")
                        tender = normalize_tender(raw)
                        if tender["id"] in seen:
                            continue
                        seen.add(tender["id"])
                        items = await fetch_items(client, tender)
                        products += upsert_tender(path, tender, items)
                    except (PNCPError, ValueError, TypeError, KeyError, OverflowError) as exc:
                        errors += 1
                        detail = "Alguns registros não puderam ser importados: " + str(exc)[:140]
                if len(rows) < 10 or payload.get("paginasRestantes") == 0:
                    break
        except PNCPError as exc:
            errors += 1
            detail = str(exc)
    record_sync(path, fetched, products, errors, detail)
    return {"fetched": fetched, "items": products, "errors": errors, "detail": detail}
