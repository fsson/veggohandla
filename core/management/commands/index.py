"""uv run manage.py index – build/update the local vegan index from Willys and Hemköp."""

from django.core.management.base import BaseCommand

from core.services import index


class Command(BaseCommand):
    help = "Hämtar sortiment och priser från Willys och Hemköp och granskar nya varor (veganskt)."

    def add_arguments(self, parser):
        parser.add_argument("--prices-only", action="store_true", help="Hoppa över granskning av nya varor.")
        parser.add_argument("--reclassify", action="store_true", help="Kör bara om vegankontrollen lokalt.")
        parser.add_argument("--refresh-listings", action="store_true",
                            help="Hämta listningar och priser igen även om de är färska.")

    def handle(self, *args, **opts):
        if opts["reclassify"]:
            self.stdout.write(f"Ändrade: {index.reclassify()}")
            return
        from django.utils import timezone

        from core.stores import axfood

        if not axfood.in_visit_time():
            nxt = timezone.localtime(axfood.next_visit_time())
            self.stderr.write(
                "Willys och Hemköp ber (robots.txt) om att bara bli besökta 04:00–08:45 UTC. "
                f"Nästa tillfälle: {nxt:%Y-%m-%d %H:%M}. Tips: schemalägg kommandot med cron."
            )
            return
        try:
            summary = index.run(progress=lambda t: self.stdout.write(t), details=not opts["prices_only"],
                                force_listings=opts["refresh_listings"])
        except index.AlreadyRunning:
            self.stderr.write("En uppdatering pågår redan (t.ex. den automatiska i `manage.py serve`).")
            return
        self.stdout.write(self.style.SUCCESS(summary))
