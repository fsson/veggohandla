"""uv run manage.py index – build/update the local vegan index from Willys and Hemköp."""

from django.core.management.base import BaseCommand

from core.services import index


class Command(BaseCommand):
    help = "Fetch products and prices from Willys and Hemköp and vet new products (vegan check)."

    def add_arguments(self, parser):
        parser.add_argument("--prices-only", action="store_true", help="Skip vetting new products.")
        parser.add_argument("--reclassify", action="store_true", help="Only re-run the vegan check locally.")
        parser.add_argument(
            "--refresh-listings", action="store_true", help="Fetch listings and prices again even if they are fresh."
        )

    def handle(self, *args, **opts):
        if opts["reclassify"]:
            self.stdout.write(f"Changed: {index.reclassify()}")
            return
        from django.utils import timezone

        from core.stores import axfood

        if not axfood.in_visit_time():
            nxt = timezone.localtime(axfood.next_visit_time())
            self.stderr.write(
                "Willys and Hemköp ask (robots.txt) to be visited only 04:00–08:45 UTC. "
                f"Next opportunity: {nxt:%Y-%m-%d %H:%M}. Tip: schedule the command with cron."
            )
            return
        try:
            summary = index.run(
                progress=lambda t: self.stdout.write(t),
                details=not opts["prices_only"],
                force_listings=opts["refresh_listings"],
            )
        except index.AlreadyRunning:
            self.stderr.write("An update is already running (e.g. the automatic one in `manage.py serve`).")
            return
        self.stdout.write(self.style.SUCCESS(summary))
