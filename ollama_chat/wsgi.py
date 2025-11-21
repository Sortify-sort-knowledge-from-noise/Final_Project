"""
WSGI config for ollama_chat project.

This runs Django and optionally runs migrations on startup when
RUN_MIGRATIONS_ON_STARTUP=True is set in environment (useful when
you cannot access a remote shell).
"""

import os
import logging

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ollama_chat.settings")

logger = logging.getLogger(__name__)

# Optionally run migrations at startup. Set RUN_MIGRATIONS_ON_STARTUP=True in env to enable.
if os.environ.get("RUN_MIGRATIONS_ON_STARTUP", "False") == "True":
    try:
        # Import Django and run migrations
        import django
        django.setup()
        from django.core import management

        # Log which DATABASE_URL is in use (masked)
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            logger.info("RUNNING MIGRATIONS ON STARTUP — using DATABASE_URL (masked): %s", db_url[:50] + "...")
        else:
            logger.info("RUNNING MIGRATIONS ON STARTUP — no DATABASE_URL found, using sqlite fallback.")

        management.call_command("migrate", "--noinput")
        logger.info("MIGRATIONS APPLIED on startup successfully.")
    except Exception:
        logger.exception("Error running migrations on startup")

application = get_wsgi_application()
