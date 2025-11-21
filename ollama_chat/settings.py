"""
Django settings for ollama_chat project.

This settings file reads configuration from environment variables so you
don't need to edit the file for Render deployment.

Required environment variables (on Render):
  - SECRET_KEY
  - DATABASE_URL (if using Postgres on Render; otherwise it falls back to sqlite)
  - DEBUG (set to "True" or "False")
  - ALLOWED_HOSTS (comma-separated, e.g. "sortify-ovdv.onrender.com")

Make sure your requirements.txt includes:
  dj-database-url
  psycopg2-binary
  whitenoise
"""

from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------------------
# Basic config from environment
# ------------------------------------------------------------------------------
# SECRET_KEY: must be set in production (Render). A default dev key is provided
# for local development only.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "dev-secret-key-replace-this-in-production"  # dev fallback
)

# DEBUG: "True" string enables debug, otherwise False
DEBUG = os.environ.get("DEBUG", "False") == "True"

# ALLOWED_HOSTS: comma-separated list in env. If empty, defaults to localhosts.
_allowed = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]

# ------------------------------------------------------------------------------
# CSRF trusted origins (auto-derived from ALLOWED_HOSTS for HTTPS domains)
# ------------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = []
for host in ALLOWED_HOSTS:
    if host and host not in ("localhost", "127.0.0.1"):
        # Add https scheme for production hosts
        CSRF_TRUSTED_ORIGINS.append(f"https://{host}")

# include local development origins (useful when testing with ports)
CSRF_TRUSTED_ORIGINS += [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# ------------------------------------------------------------------------------
# Application definition
# ------------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chatapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise should come as early as possible after SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ollama_chat.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],  # add project-level template dirs here if needed
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ollama_chat.wsgi.application"

# ------------------------------------------------------------------------------
# Database
# ------------------------------------------------------------------------------
# Prefer DATABASE_URL (Render will inject this when DB is linked). If not present,
# fall back to local sqlite for development.
# Allows forcing sqlite regardless of DATABASE_URL (useful when you cannot edit Render links)
FORCE_SQLITE = os.environ.get("FORCE_SQLITE", "False") == "True"

DATABASE_URL = os.environ.get("DATABASE_URL")

if FORCE_SQLITE:
    # Use local sqlite (ephemeral on Render) when forced
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    # Prefer DATABASE_URL (Postgres) when present, otherwise fallback to sqlite for local dev
    if DATABASE_URL:
        DATABASES = {
            "default": dj_database_url.parse(
                DATABASE_URL, conn_max_age=600, ssl_require=not (os.environ.get("DEBUG", "False") == "True")
            )
        }
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
# ------------------------------------------------------------------------------
# Password validation
# ------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------------------
# Authentication & Session settings
# ------------------------------------------------------------------------------
LOGIN_URL = "login_view"
LOGIN_REDIRECT_URL = "index_view"
LOGOUT_REDIRECT_URL = "login_view"

SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# In production (HTTPS) these should be True. We set them based on DEBUG.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False  # keep False so JS can read CSRF token if needed

# ------------------------------------------------------------------------------
# Internationalization & timezone
# ------------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------------------
# Static files (WhiteNoise)
# ------------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Use Manifest storage in production to enable long-term caching
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ------------------------------------------------------------------------------
# Security headers (behind proxy like Render)
# ------------------------------------------------------------------------------
# If you're behind a proxy (Render terminates TLS), allow Django to recognize https:
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Extra security settings that are safe when DEBUG=False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ------------------------------------------------------------------------------
# Default primary key field type
# ------------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------------------
# Logging (basic) - prints errors to console which Render will capture
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# ------------------------------------------------------------------------------
# Final safety: print useful info to logs when running management commands
# (useful in Render Shell to quickly verify env)
# ------------------------------------------------------------------------------
if os.environ.get("RUNNING_IN_CONTAINER") or os.environ.get("RENDER"):
    # This block will run on Render; keep minimal to avoid noisy logs.
    import logging
    logging.getLogger("django").info("Settings loaded: DEBUG=%s, ALLOWED_HOSTS=%s", DEBUG, ALLOWED_HOSTS)
