"""Painel privado de execução comercial, independente dos status oficiais PNCP."""
from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

from .storage import STATUSES, connection

STAGES = {
    "avaliar": "Avaliar",
    "cotando": "Solicitando cotações",
    "documentos": "Conferindo documentação",
    "pronto": "Pronto para decidir",
    "inscrito": "Inscrição marcada manualmente",
    "ganho": "Ganho (marcado manualmente)",
    "perdido": "Não ganho (marcado manualmente)",
    "arquivado": "Arquivado",
}
PRIORITIES = {
    "baixa": "Baixa", "normal": "Normal", "alta": "Alta",
}
MAX_CASES = 200
MAX_TASKS = 20
MAX_NOTES = 1200


class WorkspaceError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _time() -> str:
    return datetime.now(UTC).isoformat()


def init_workspace(path: str) -> None:
    with connection(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS opportunity_cases (
            tender_id TEXT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            stage TEXT NOT NULL DEFAULT 'avaliar'
                CHECK(stage IN ('avaliar','cotando','documentos','pronto',
                                'inscrito','ganho','perdido','arquivado')),
            priority TEXT NOT NULL DEFAULT 'normal'
                CHECK(priority IN ('baixa','normal','alta')),
            deadline TEXT,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(tender_id,numero)
        );
        CREATE TABLE IF NOT EXISTS opportunity_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id TEXT NOT NULL,
            numero INTEGER NOT NULL,
            label TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(tender_id,numero)
                REFERENCES opportunity_cases(tender_id,numero) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_opportunity_tasks_case
            ON opportunity_tasks(tender_id,numero,id);
        CREATE TABLE IF NOT EXISTS opportunity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id TEXT NOT NULL,
            numero INTEGER NOT NULL,
            old_stage TEXT,
            new_stage TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            FOREIGN KEY(tender_id,numero)
                REFERENCES opportunity_cases(tender_id,numero) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_opportunity_events_case
            ON opportunity_events(tender_id,numero,id DESC);
        """)


def _validate_ref(tender_id: str, number: int) -> None:
    if not 1 <= len(tender_id) <= 180 or not 1 <= number <= 100000:
        raise WorkspaceError("Item inválido.")


def _validate_deadline(deadline: str) -> str | None:
    if not deadline.strip():
        return None
    if len(deadline) != 10:
        raise WorkspaceError("Data de prazo inválida.")
    try:
        parsed = date.fromisoformat(deadline)
    except ValueError:
        raise WorkspaceError("Data de prazo inválida.") from None
    if not 2021 <= parsed.year <= 2100:
        raise WorkspaceError("Prazo fora do intervalo válido.")
    return parsed.isoformat()


def save_case(
    path: str, tender_id: str, number: int, stage: str, priority: str,
    deadline: str = "", notes: str = "",
) -> dict:
    _validate_ref(tender_id, number)
    if stage not in STAGES or priority not in PRIORITIES:
        raise WorkspaceError("Etapa ou prioridade inválida.")
    if len(notes) > MAX_NOTES:
        raise WorkspaceError("As notas não podem ultrapassar 1.200 caracteres.")
    normalized_deadline = _validate_deadline(deadline)
    moment = _time()
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute("""
            SELECT 1 FROM items WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
        if not item:
            raise WorkspaceError("Item não disponível na base local.", 404)
        previous = db.execute("""
            SELECT stage FROM opportunity_cases WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
        if previous is None:
            count = db.execute("SELECT COUNT(*) FROM opportunity_cases").fetchone()[0]
            if count >= MAX_CASES:
                raise WorkspaceError("Limite de 200 oportunidades atingido.")
            db.execute("""
                INSERT INTO opportunity_cases
                  (tender_id,numero,stage,priority,deadline,notes,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (tender_id, number, stage, priority, normalized_deadline,
                  notes.strip(), moment, moment))
        else:
            db.execute("""
                UPDATE opportunity_cases
                SET stage=?,priority=?,deadline=?,notes=?,updated_at=?
                WHERE tender_id=? AND numero=?
            """, (stage, priority, normalized_deadline, notes.strip(), moment,
                  tender_id, number))
        if previous is None or previous["stage"] != stage:
            db.execute("""
                INSERT INTO opportunity_events
                (tender_id,numero,old_stage,new_stage,changed_at)
                VALUES (?,?,?,?,?)
            """, (tender_id, number, previous["stage"] if previous else None,
                  stage, moment))
    found = get_case(path, tender_id, number)
    assert found is not None
    return found


def get_case(path: str, tender_id: str, number: int) -> dict | None:
    _validate_ref(tender_id, number)
    with connection(path) as db:
        row = db.execute("""
            SELECT c.*, i.descricao, i.status AS pncp_status,
                   t.objeto,t.orgao,t.uf,t.municipio,t.link,t.encerramento
            FROM opportunity_cases c
            JOIN tenders t ON t.id=c.tender_id
            LEFT JOIN items i ON i.tender_id=c.tender_id AND i.numero=c.numero
            WHERE c.tender_id=? AND c.numero=?
        """, (tender_id, number)).fetchone()
    return dict(row) if row else None


def list_cases(path: str, limit: int = 200) -> list[dict]:
    limit = max(1, min(MAX_CASES, limit))
    with connection(path) as db:
        rows = db.execute("""
            SELECT c.*,i.descricao,i.status AS pncp_status,
                   t.orgao,t.municipio,t.uf,t.objeto,t.link,t.encerramento,
                   (SELECT COUNT(*) FROM opportunity_tasks task
                    WHERE task.tender_id=c.tender_id AND task.numero=c.numero)
                       AS tasks_total,
                   (SELECT COUNT(*) FROM opportunity_tasks task
                    WHERE task.tender_id=c.tender_id AND task.numero=c.numero
                      AND task.done=1) AS tasks_done
            FROM opportunity_cases c
            JOIN tenders t ON t.id=c.tender_id
            LEFT JOIN items i ON i.tender_id=c.tender_id AND i.numero=c.numero
            ORDER BY CASE c.priority WHEN 'alta' THEN 0
                        WHEN 'normal' THEN 1 ELSE 2 END,
                     CASE WHEN c.stage='arquivado' THEN 1 ELSE 0 END,
                     CASE WHEN c.deadline IS NULL THEN 1 ELSE 0 END,
                     c.deadline,c.updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(row) for row in rows]


def case_tasks(path: str, tender_id: str, number: int) -> list[dict]:
    with connection(path) as db:
        rows = db.execute("""
            SELECT * FROM opportunity_tasks
            WHERE tender_id=? AND numero=?
            ORDER BY done ASC,id ASC LIMIT ?
        """, (tender_id, number, MAX_TASKS)).fetchall()
    return [dict(row) for row in rows]


def case_events(path: str, tender_id: str, number: int) -> list[dict]:
    with connection(path) as db:
        rows = db.execute("""
            SELECT * FROM opportunity_events
            WHERE tender_id=? AND numero=? ORDER BY id DESC LIMIT 30
        """, (tender_id, number)).fetchall()
    return [dict(row) for row in rows]


def add_task(path: str, tender_id: str, number: int, label: str) -> int:
    _validate_ref(tender_id, number)
    label = " ".join(label.split())
    if not 3 <= len(label) <= 120:
        raise WorkspaceError("Tarefa deve ter entre 3 e 120 caracteres.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        owner = db.execute("""
            SELECT 1 FROM opportunity_cases WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()
        if owner is None:
            raise WorkspaceError("Salve a oportunidade antes de adicionar tarefas.", 404)
        count = db.execute("""
            SELECT COUNT(*) FROM opportunity_tasks WHERE tender_id=? AND numero=?
        """, (tender_id, number)).fetchone()[0]
        if count >= MAX_TASKS:
            raise WorkspaceError("Limite de 20 tarefas por oportunidade atingido.")
        moment = _time()
        cursor = db.execute("""
            INSERT INTO opportunity_tasks
              (tender_id,numero,label,created_at,updated_at)
            VALUES (?,?,?,?,?)
        """, (tender_id, number, label, moment, moment))
        return int(cursor.lastrowid)


def toggle_task(path: str, task_id: int) -> None:
    if task_id <= 0:
        raise WorkspaceError("Tarefa inválida.")
    with connection(path) as db:
        db.execute("""
            UPDATE opportunity_tasks
            SET done=CASE done WHEN 1 THEN 0 ELSE 1 END, updated_at=?
            WHERE id=?
        """, (_time(), task_id))


def delete_task(path: str, task_id: int) -> None:
    if task_id <= 0:
        raise WorkspaceError("Tarefa inválida.")
    with connection(path) as db:
        db.execute("DELETE FROM opportunity_tasks WHERE id=?", (task_id,))


def safe_excel_text(value: object) -> str:
    """Formula injection: nenhuma célula livre pode executar fórmula de planilha."""
    raw = str(value or "")
    if raw.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + raw
    return raw


def export_csv(rows: list[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow([
        "Origem", "Item", "Descrição", "Órgão", "Município", "UF",
        "Status PNCP", "Etapa manual", "Prioridade", "Prazo",
        "Notas privadas", "Checklist concluído", "Checklist total", "Link PNCP",
    ])
    for row in rows:
        writer.writerow([
            safe_excel_text(row["tender_id"]),
            row["numero"],
            safe_excel_text(row.get("descricao") or row.get("objeto") or ""),
            safe_excel_text(row.get("orgao") or ""),
            safe_excel_text(row.get("municipio") or ""),
            safe_excel_text(row.get("uf") or ""),
            STATUSES.get(row.get("pncp_status"), "Não identificado"),
            STAGES.get(row["stage"], "Não definido"),
            PRIORITIES.get(row["priority"], "Não definido"),
            row.get("deadline") or "",
            safe_excel_text(row.get("notes") or ""),
            row.get("tasks_done", 0), row.get("tasks_total", 0),
            safe_excel_text(row.get("link") or ""),
        ])
    return "\ufeff" + stream.getvalue()
