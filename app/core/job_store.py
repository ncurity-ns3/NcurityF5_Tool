from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.models import JobRecord, JobStatus


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists jobs (
                    job_id text primary key,
                    module text not null,
                    mode text not null,
                    status text not null,
                    payload text not null
                )
                """
            )

    def save(self, job: JobRecord) -> None:
        payload = job.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                """
                insert into jobs (job_id, module, mode, status, payload)
                values (?, ?, ?, ?, ?)
                on conflict(job_id) do update set
                    status=excluded.status,
                    payload=excluded.payload
                """,
                (job.job_id, job.module, job.mode.value, job.status.value, payload),
            )

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload from jobs where job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return JobRecord.model_validate_json(row["payload"])

    def update_status(self, job_id: str, status: JobStatus) -> None:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        job.status = status
        self.save(job)

    def list_all(self) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute("select payload from jobs order by rowid desc").fetchall()
        return [JobRecord.model_validate_json(r["payload"]) for r in rows]
