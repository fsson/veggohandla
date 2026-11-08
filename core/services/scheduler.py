"""Automatic refresh of the product index, running inside `manage.py serve`.

Once a minute it checks whether a run is due: inside the chains' visiting hours, no run in
progress, and something to do (today's prices not fetched yet, or products not vetted yet).
A run pauses by itself when the window closes and the next morning continues where it
stopped. After a failed run (e.g. the stores don't respond) it waits before trying again.

This makes a single always-on process enough for hosting: no cron job and no separate worker.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass

from django.db import close_old_connections
from django.utils import timezone

from core.services import index
from core.stores import axfood

log = logging.getLogger(__name__)

POLL_SECONDS = 60
RETRY_AFTER = dt.timedelta(minutes=30)

_thread: threading.Thread | None = None
_stop = threading.Event()


@dataclass
class State:
    last_failure: dt.datetime | None = None


def due(now: dt.datetime, state: State) -> bool:
    if not axfood.in_visit_time(now):
        return False
    if state.last_failure and now - state.last_failure < RETRY_AFTER:
        return False
    if index.is_running():
        return False
    return index.has_pending_work(now)


def tick(state: State, now: dt.datetime | None = None) -> str | None:
    """Run the index if it is due. Returns the run's summary, or None if nothing ran."""
    now = now or timezone.now()
    if not due(now, state):
        return None
    log.info("Startar automatisk uppdatering av sortimentet")
    try:
        summary = index.run()
    except (axfood.OutsideVisitTime, index.AlreadyRunning):
        return None
    except Exception:
        # Store errors and anything unexpected: log, back off, try again later.
        log.exception("Automatisk uppdatering misslyckades")
        state.last_failure = now
        return None
    state.last_failure = None
    log.info("Automatisk uppdatering klar: %s", summary)
    return summary


def _loop() -> None:
    state = State()
    while not _stop.is_set():
        try:
            tick(state)
        finally:
            close_old_connections()
        _stop.wait(POLL_SECONDS)


def start() -> None:
    """Start the scheduler thread (once per process)."""
    global _thread
    if is_active():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="veggohandla-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def is_active() -> bool:
    return bool(_thread and _thread.is_alive())
