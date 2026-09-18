"""Progress reporting for the long-running stages.

On a 6K segment the paste-back loop runs for minutes with nothing to show for
it, which reads as a hang. These helpers make that loop report where it is.

The subtlety worth encoding: `\\r` single-line updates are right on a terminal and
wrong when stdout is a file. `> run.log` with `\\r` produces one enormous
unreadable line, so `Log` switches to periodic complete lines when not attached
to a TTY.
"""

import os
import sys
import time
from pathlib import Path


def logs_dir() -> Path:
    """<project root>/logs — the repo root in a source checkout, cwd/logs as a
    fallback for exotic installs."""
    root = Path(__file__).resolve().parents[2]
    d = root / "logs" if (root / "pyproject.toml").exists() else Path.cwd() / "logs"
    d.mkdir(exist_ok=True)
    return d


def open_log_file(stem: str):
    """Create logs/<stem>_<timestamp>.log and return an open text handle."""
    path = logs_dir() / f"{stem}_{time.strftime('%Y%m%d-%H%M%S')}.log"
    fh = open(path, "w", encoding="utf-8")
    return fh, path


def format_duration(seconds):
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(round(seconds)), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def clock():
    return time.strftime("%H:%M:%S")


class RateMeter:
    """Frame counter + throughput + ETA."""

    def __init__(self, total, unit="frames"):
        self.total = total
        self.unit = unit
        self.start = time.time()
        self.count = 0

    def tick(self, k=1):
        self.count += k

    @property
    def elapsed(self):
        return time.time() - self.start

    def eta(self):
        """Seconds remaining, or None until there is enough signal to guess."""
        if self.count <= 0 or self.count >= self.total:
            return 0.0
        rate = self.count / self.elapsed if self.elapsed > 0 else 0.0
        if rate <= 0:
            return None
        return (self.total - self.count) / rate

    def line(self, prefix):
        pct = 100.0 * self.count / self.total if self.total else 100.0
        rate = self.count / self.elapsed if self.elapsed > 0 else 0.0
        eta = self.eta()
        eta_s = "?" if eta is None else format_duration(eta)
        return (f"{prefix} {self.count}/{self.total} ({pct:5.1f}%) "
                f"{rate:5.1f} {self.unit}/s  elapsed "
                f"{format_duration(self.elapsed)}  ETA {eta_s}")


class Log:
    """Phase lines plus a live progress line that behaves when redirected.

    `every=0` (the default) picks the interval automatically: on a terminal the
    status line is rewritten in place, and when redirected it emits roughly 20
    lines per phase, so `> run.log` stays readable without being a firehose.

    `fh`: an optional log file opened by :func:`open_log_file`. Everything that
    reaches the console is mirrored there — one run, one timestamped file — so
    a run stays auditable after the terminal scrollback is gone.
    """

    def __init__(self, every=0, quiet=False, lines_per_phase=20, fh=None):
        self.tty = sys.stdout.isatty()
        self.every = every
        self.lines_per_phase = lines_per_phase
        self.quiet = quiet
        self.fh = fh

    def _interval(self, meter):
        if self.every > 0:
            return self.every
        return max(1, meter.total // self.lines_per_phase)

    def _to_file(self, line):
        if self.fh:
            self.fh.write(line + "\n")
            self.fh.flush()

    def phase(self, msg):
        self._end_line()
        line = f"[{clock()}] {msg}"
        print(line, flush=True)
        self._to_file(line)

    def info(self, msg):
        self._end_line()
        line = f"          {msg}"
        print(line, flush=True)
        self._to_file(line)

    def progress(self, meter, prefix):
        self._to_file(meter.line(prefix))
        if self.quiet:
            return
        if self.tty:
            sys.stdout.write("\r" + meter.line(prefix))
            sys.stdout.flush()
        elif meter.count % self._interval(meter) == 0 or meter.count >= meter.total:
            print(meter.line(prefix), flush=True)

    def _end_line(self):
        if self.tty:
            sys.stdout.write("\r" + " " * 100 + "\r")
            sys.stdout.flush()

    def done(self):
        self._end_line()
