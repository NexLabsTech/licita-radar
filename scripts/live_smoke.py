"""Smoke test real, somente leitura e de escopo mínimo, sem credenciais."""
import asyncio
import sys
from datetime import date, timedelta

import httpx

from app.pncp import CONSULTA, PNCPError, _json, fetch_items, normalize_tender


async def main() -> None:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=2)
    params = {
        "dataInicial": start.strftime("%Y%m%d"),
        "dataFinal": end.strftime("%Y%m%d"),
        "codigoModalidadeContratacao": 6,
        "pagina": 1,
        "tamanhoPagina": 10,
        "uf": "SP",
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        payload = await _json(client, CONSULTA, params)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PNCPError("Publicações: esquema inesperado.")
        rows = payload["data"]
        if not rows:
            raise PNCPError("Nenhuma publicação para a amostra, teste inconclusivo.")
        print("PNCP publicações OK. Registros de amostra:", len(rows))
        failures: list[str] = []
        for row in rows[:3]:
            try:
                tender = normalize_tender(row)
                items = await fetch_items(client, tender)
                print("PNCP itens OK. Amostra:", tender["id"],
                      "itens=", len(items),
                      "materiais=", sum(i.get("materialOuServico") == "M" for i in items))
                return
            except (PNCPError, ValueError, TypeError, KeyError) as exc:
                failures.append(str(exc))
        raise PNCPError("Nenhuma leitura de itens bem-sucedida: " + "; ".join(failures))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (PNCPError, httpx.HTTPError, ValueError) as exc:
        print("PNCP LIVE SMOKE INCONCLUSIVO/FALHA:", exc, file=sys.stderr)
        sys.exit(2)
