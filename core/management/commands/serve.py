"""uv run manage.py serve – run Veggohandla for real: web server + automatic daily refresh.

One process does everything, which keeps hosting simple (one systemd service, one container):
  * applies database migrations and seeds an empty database,
  * starts the scheduler that refreshes the product index every morning,
  * serves the app with waitress (a production WSGI server, pure Python, works on a Raspberry Pi).
"""

import os

from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.models import Category
from core.services import scheduler


def prepare(stdout=None) -> None:
    """Bring the database up to date, and fill it with seed data the first time."""
    call_command("migrate", interactive=False, verbosity=0)
    if not Category.objects.exists():
        call_command("seed", stdout=stdout)


class Command(BaseCommand):
    help = "Kör Veggohandla: webbserver och automatisk uppdatering av sortimentet varje morgon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            default=os.environ.get("VEGGOHANDLA_HOST", "127.0.0.1"),
            help="Adress att lyssna på (0.0.0.0 = alla nätverk). Standard: 127.0.0.1",
        )
        parser.add_argument(
            "--port", type=int, default=int(os.environ.get("VEGGOHANDLA_PORT", "8000")), help="Port. Standard: 8000"
        )
        parser.add_argument("--threads", type=int, default=4, help="Antal trådar för webbservern.")
        parser.add_argument(
            "--no-refresh", action="store_true", help="Stäng av den automatiska uppdateringen av sortimentet."
        )

    def handle(self, *args, **opts):
        from waitress import serve

        from config.wsgi import application

        prepare(self.stdout)
        if not opts["no_refresh"]:
            scheduler.start()
        host, port = opts["host"], opts["port"]
        shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
        self.stdout.write(self.style.SUCCESS(f"Veggohandla kör på http://{shown}:{port}/"))
        if not opts["no_refresh"]:
            self.stdout.write("Sortimentet uppdateras automatiskt varje morgon inom kedjornas tidsfönster.")
        self.stdout.flush()  # show the messages right away, also when output goes to a log
        serve(application, host=host, port=port, threads=opts["threads"], ident="Veggohandla")
