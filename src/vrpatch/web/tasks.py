"""Single-lane task queue for extract/merge runs (frozen decision: one at a
time — 8K jobs are heavy enough that parallel runs only thrash).

Each task is the existing CLI run as a subprocess, stdout+stderr captured to a
file under logs/. That keeps one code path for console and web users, and the
captured stream doubles as the progress source: the dashboard polls
:meth:`TaskQueue.status` which tails the file.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from ..progress import logs_dir

_TAIL_BYTES = 8 * 1024


class Task:
    def __init__(self, kind: str, case: str, argv: list[str]):
        self.kind = kind          # "extract" | "merge"
        self.case = case
        self.argv = argv
        self.state = "queued"     # queued -> running -> done | failed
        self.returncode: int | None = None
        self.started = 0.0
        self.out_path: Path | None = None
        self.proc: subprocess.Popen | None = None

    def _run(self):
        self.out_path = logs_dir() / f"web_{self.kind}_{self.case}_{time.strftime('%Y%m%d-%H%M%S')}.log"
        with open(self.out_path, "w", encoding="utf-8", newline="") as fh:
            self.proc = subprocess.Popen(
                self.argv, stdout=fh, stderr=subprocess.STDOUT,
                cwd=str(Path(__file__).resolve().parents[3]))  # repo root
            self.state = "running"
            self.started = time.time()
            self.returncode = self.proc.wait()
        self.state = "done" if self.returncode == 0 else "failed"

    def tail(self, max_lines: int = 14) -> list[str]:
        if not self.out_path or not self.out_path.exists():
            return []
        with open(self.out_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return lines[-max_lines:]


class TaskQueue:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.current: Task | None = None
        self.pending: list[Task] = []
        self.history: list[Task] = []

    def submit(self, kind: str, case: str, argv: list[str]) -> Task:
        with self._lock:
            task = Task(kind, case, argv)
            self.pending.append(task)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._drain, daemon=True)
                self._thread.start()
            return task

    def _drain(self):
        while True:
            with self._lock:
                if not self.pending:
                    return
                task = self.pending.pop(0)
                self.current = task
            task._run()
            with self._lock:
                self.history.append(task)
                self.current = None

    def status(self) -> dict:
        with self._lock:
            cur = self.current
            return {
                "current": None if cur is None else {
                    "kind": cur.kind, "case": cur.case, "state": cur.state,
                    "tail": cur.tail(),
                },
                "queued": [{"kind": t.kind, "case": t.case} for t in self.pending],
                "last": ([{"kind": t.kind, "case": t.case, "state": t.state,
                           "returncode": t.returncode} for t in self.history[-3:]]),
            }


QUEUE = TaskQueue()
