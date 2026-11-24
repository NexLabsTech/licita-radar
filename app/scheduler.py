"""Varredura agendada no processo do aplicativo (somente 1 worker)."""
import asyncio
import logging
from datetime import date, timedelta

from .pncp import sync_pncp

logger = logging.getLogger(__name__)


async def scan_cycle(db_path: str, uf: str = "SP", today: date | None = None) -> list[dict]:
    """Consulta hoje/ontem em duas modalidades, respeitando os limites do PNCP client."""
    day = today or date.today()
    results = []
    for modality in (6, 8):
        try:
            result = await sync_pncp(db_path, day - timedelta(days=1), day, uf, modality)
        except Exception:  # Resiliência do worker; falha fica nos logs.
            logger.exception("Falha no ciclo de varredura PNCP, modalidade %s", modality)
            result = {"fetched": 0, "items": 0, "errors": 1, "detail": "Falha do worker"}
        results.append({"modality": modality, **result})
    return results


async def periodic_scan_loop(db_path: str, uf: str, interval_minutes: int,
                             lock: asyncio.Lock) -> None:
    """Ativo apenas enquanto o servidor estiver em execução; cancelável no shutdown."""
    while True:
        async with lock:
            results = await scan_cycle(db_path, uf)
            logger.info("LicitaRadar ciclo automático concluído: %s", results)
        await asyncio.sleep(interval_minutes * 60)
