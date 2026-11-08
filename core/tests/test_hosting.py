"""Hosting: the `serve` command, automatic daily refresh and the index runner's robustness."""

import datetime as dt
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from core.models import AppSettings, Category, Product
from core.services import index, scheduler
from core.stores import axfood
from core.stores.axfood import Details, ProductData

UTC = dt.timezone.utc
MORNING = dt.datetime(2026, 11, 9, 5, 0, tzinfo=UTC)  # inside the window (04:00–08:45 UTC)
EVENING = dt.datetime(2026, 11, 9, 18, 0, tzinfo=UTC)
ROOT = Path(settings.BASE_DIR)


# Tests using fake_store need `transactional_db`: the plain `db` fixture wraps each test in a
# transaction, which would hide whether the crawler waits for the network inside one.
def fake_store(monkeypatch, details_calls=None):
    tree = [{"url": "vegetariskt", "title": "Vegetariskt",
             "children": [{"url": "vegetariskt/tofu", "title": "Tofu"}]}]

    def list_category(retailer, slug):
        # The crawler must not hold a database transaction while it waits for the store.
        assert not connection.in_atomic_block, "network request inside a transaction"
        if retailer == "willys":
            yield ProductData("willys", "1_ST", "Tofu Naturell", size_text="400g", size_amount=400, size_unit="g", price=25)
            yield ProductData("willys", "2_ST", "Tofu Rökt", size_text="200g", size_amount=200, size_unit="g", price=20)

    def fetch_details(retailer, code):
        assert not connection.in_atomic_block, "network request inside a transaction"
        if details_calls is not None:
            details_calls.append((code, AppSettings.load().index_heartbeat))
        return Details("", "Sojabönor, vatten", "")

    monkeypatch.setattr(axfood, "category_tree", lambda r: tree)
    monkeypatch.setattr(axfood, "list_category", list_category)
    monkeypatch.setattr(axfood, "fetch_details", fetch_details)
    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: True)
    monkeypatch.setattr(index, "WILLYS_SECTIONS", {"vegetariskt": None})
    monkeypatch.setattr(index, "HEMKOP_SECTIONS", {"vegetariskt": None})


# ------------------------------------------------------------ index runner


def test_only_one_run_at_a_time(transactional_db, monkeypatch):
    fake_store(monkeypatch)
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(index_running=True, index_heartbeat=timezone.now())
    with pytest.raises(index.AlreadyRunning):
        index.run()
    # A run whose heartbeat stopped (its process died) no longer blocks.
    AppSettings.objects.filter(pk=1).update(index_heartbeat=timezone.now() - dt.timedelta(minutes=11))
    assert "veganska" in index.run()
    assert not AppSettings.load().index_running


def test_heartbeat_for_every_product(transactional_db, monkeypatch):
    calls = []
    fake_store(monkeypatch, calls)
    index.run()
    assert len(calls) == 2
    assert all(beat is not None for _, beat in calls)
    # Each product's request happens with a fresh heartbeat (well within the timeout).
    assert all(timezone.now() - beat < index.HEARTBEAT_TIMEOUT for _, beat in calls)


def test_listings_are_fresh_for_the_calendar_day_not_20_hours(db):
    s = AppSettings.load()
    s.listed_at = dt.datetime(2026, 11, 8, 8, 40, tzinfo=UTC)  # yesterday, late in the window
    assert index.listings_fresh(s, dt.datetime(2026, 11, 8, 23, 0, tzinfo=UTC))
    # Next morning only ~19 h later: still a new day, so prices are due again.
    assert not index.listings_fresh(s, dt.datetime(2026, 11, 9, 4, 0, tzinfo=UTC))
    s.listed_at = None
    assert not index.listings_fresh(s, MORNING)


def test_pending_work(transactional_db, monkeypatch):
    fake_store(monkeypatch)
    assert index.has_pending_work(timezone.now())  # never indexed
    index.run()
    assert not index.has_pending_work(timezone.now())  # prices today, everything vetted
    Product.objects.filter(code="2_ST").update(checked_at=None)
    assert index.has_pending_work(timezone.now())  # a product left to vet
    assert index.has_pending_work(timezone.now() + dt.timedelta(days=1))  # tomorrow's prices


# ------------------------------------------------------------ scheduler


def test_scheduler_runs_only_when_due(db, monkeypatch):
    ran = []
    monkeypatch.setattr(index, "run", lambda **kw: ran.append(1) or "klart")
    state = scheduler.State()

    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: False)
    assert scheduler.tick(state, EVENING) is None and not ran  # outside the window

    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: True)
    monkeypatch.setattr(index, "has_pending_work", lambda now=None: False)
    assert scheduler.tick(state, MORNING) is None and not ran  # nothing to do

    monkeypatch.setattr(index, "has_pending_work", lambda now=None: True)
    monkeypatch.setattr(index, "is_running", lambda: True)
    assert scheduler.tick(state, MORNING) is None and not ran  # a run is already going

    monkeypatch.setattr(index, "is_running", lambda: False)
    assert scheduler.tick(state, MORNING) == "klart" and ran == [1]


def test_scheduler_backs_off_after_a_failure(db, monkeypatch):
    attempts = []

    def failing_run(**kw):
        attempts.append(1)
        raise axfood.StoreError("nere")

    monkeypatch.setattr(index, "run", failing_run)
    monkeypatch.setattr(axfood, "in_visit_time", lambda now=None: True)
    monkeypatch.setattr(index, "has_pending_work", lambda now=None: True)
    monkeypatch.setattr(index, "is_running", lambda: False)
    state = scheduler.State()
    assert scheduler.tick(state, MORNING) is None and len(attempts) == 1
    assert scheduler.tick(state, MORNING + dt.timedelta(minutes=10)) is None and len(attempts) == 1
    scheduler.tick(state, MORNING + scheduler.RETRY_AFTER)
    assert len(attempts) == 2


def test_scheduler_does_a_real_run(transactional_db, monkeypatch):
    fake_store(monkeypatch)
    summary = scheduler.tick(scheduler.State(), timezone.now())
    assert summary and Product.objects.filter(vegan=True).count() == 2


# ------------------------------------------------------------ serve


def test_serve_prepares_the_database_and_starts_everything(db, monkeypatch):
    import waitress

    started, served = [], {}
    monkeypatch.setattr(scheduler, "start", lambda: started.append(1))
    monkeypatch.setattr(waitress, "serve", lambda app, **kw: served.update(kw))
    assert not Category.objects.exists()
    call_command("serve", "--host", "0.0.0.0", "--port", "8123", stdout=open("/dev/null", "w"))
    assert Category.objects.exists()  # seeded on first start
    assert started == [1] and served["host"] == "0.0.0.0" and served["port"] == 8123

    started.clear()
    n = Category.objects.count()
    call_command("serve", "--no-refresh", stdout=open("/dev/null", "w"))
    assert started == [] and Category.objects.count() == n  # no reseeding, no scheduler


def test_status_page_says_whether_refresh_is_automatic(db, client, monkeypatch):
    monkeypatch.setattr(scheduler, "is_active", lambda: True)
    assert "Uppdateras automatiskt varje morgon" in client.get("/sortiment/status/").content.decode()
    monkeypatch.setattr(scheduler, "is_active", lambda: False)
    assert "Automatisk uppdatering är av" in client.get("/sortiment/status/").content.decode()


def test_static_files_and_images_are_served_without_debug(db, client, settings, tmp_path):
    assert not settings.DEBUG
    r = client.get("/static/core/app.css")
    assert r.status_code == 200 and b"Veggohandla" in b"".join(r.streaming_content)
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "recept").mkdir()
    (tmp_path / "recept" / "bild.webp").write_bytes(b"RIFF")
    assert client.get("/media/recept/bild.webp").status_code == 200
    from django.test import Client

    # Path traversal is refused (400 in production; the test client would otherwise re-raise).
    assert Client(raise_request_exception=False).get("/media/../config/settings.py").status_code in (400, 404)


# ------------------------------------------------------------ install script


def test_install_script_unit():
    out = subprocess.run(["bash", str(ROOT / "deploy" / "install.sh"), "--print-unit"],
                         capture_output=True, text=True, check=True, env={"PORT": "8080", "PATH": "/usr/bin:/bin"}).stdout
    assert f"WorkingDirectory={ROOT}" in out
    assert f"ExecStart={ROOT}/.venv/bin/python manage.py serve --host 0.0.0.0 --port 8080" in out
    assert "Restart=on-failure" in out and "WantedBy=multi-user.target" in out


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd not available")
def test_install_script_unit_is_valid_systemd(tmp_path):
    out = subprocess.run(["bash", str(ROOT / "deploy" / "install.sh"), "--print-unit"],
                         capture_output=True, text=True, check=True).stdout
    unit = tmp_path / "veggohandla.service"
    unit.write_text(out)
    r = subprocess.run(["systemd-analyze", "verify", str(unit)], capture_output=True, text=True)
    problems = [ln for ln in (r.stdout + r.stderr).splitlines() if "veggohandla.service" in ln]
    assert r.returncode == 0 and not problems, r.stdout + r.stderr
