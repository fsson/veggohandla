"""Settings for Veggohandla – a local, personal app.

All data lives in the `data/` directory (SQLite database + uploaded images).
Back up by copying that directory.

The defaults are production-safe, so hosting needs no configuration: `manage.py serve`.
Environment variables (all optional):
  VEGGOHANDLA_DATA_DIR         where data is stored (default: data/ in the project)
  VEGGOHANDLA_DEBUG=1          Django debug mode, for development only
  VEGGOHANDLA_HOST / _PORT     where `serve` listens (default 127.0.0.1:8000)
  VEGGOHANDLA_TRUSTED_ORIGINS  comma-separated https origins when served behind an HTTPS
                               proxy, e.g. https://veggohandla.example.ts.net
  VEGGOHANDLA_SECRET_KEY       otherwise generated once into data/secret_key
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VEGGOHANDLA_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key() -> str:
    path = DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50))
    return path.read_text().strip()


SECRET_KEY = os.environ.get("VEGGOHANDLA_SECRET_KEY") or _secret_key()
DEBUG = os.environ.get("VEGGOHANDLA_DEBUG", "0") == "1"
# Personal app on a home network: it is reached by whatever name or address the host has
# (localhost, raspberrypi.local, 192.168.x.y …), so any Host header is accepted.
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("VEGGOHANDLA_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves /static/ in production, no collectstatic step
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context.nav",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "veggohandla.sqlite3",
        # WAL lets the web app read while the index writes; the timeout covers short write overlaps.
        "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL;", "timeout": 20},
    }
}

# The interface is Swedish only (no translation catalogue). USE_I18N stays on so Django's own
# Swedish month/weekday names and form messages are used.
LANGUAGE_CODE = "sv"
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Serve static files straight from the apps' static directories (no collectstatic needed).
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

# Log to stdout: the terminal, or the systemd journal when run as a service.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "core": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "waitress": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
