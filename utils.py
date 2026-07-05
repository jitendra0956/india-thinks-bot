"""Shared utilities: logging setup, retry decorator, slugify.

Centralized here so every module gets consistent, GitHub-Actions-friendly
logging and the same retry behavior for flaky network calls.
"""
import functools
import logging
import re
import sys
import time


def setup_logging() -> logging.Logger:
    """Configures root logging once. Safe to call from multiple entry points."""
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger("india_thinks")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return logging.getLogger("india_thinks")


logger = setup_logging()


def retry(times: int = 3, delay: float = 2.0, backoff: float = 2.0,
          exceptions: tuple = (Exception,)):
    """Retries a function on failure with exponential backoff.

    Logs each failed attempt. Re-raises the last exception if all attempts
    fail, so the caller (and GitHub Actions) sees a real error, not a
    silent None.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exc = None
            for attempt in range(1, times + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    logger.warning(
                        "%s failed on attempt %d/%d: %s",
                        fn.__name__, attempt, times, exc,
                    )
                    if attempt < times:
                        time.sleep(current_delay)
                        current_delay *= backoff
            logger.error("%s failed after %d attempts, giving up.", fn.__name__, times)
            raise last_exc
        return wrapper
    return decorator


def slugify(text: str, max_len: int = 60) -> str:
    """Converts arbitrary AI-generated text into a safe URL/filename/JS-string slug.

    Strips anything that isn't a-z, 0-9, or hyphen. This matters more than it
    looks: an unsanitized slug from the model can contain spaces, quotes, or
    unicode that breaks file paths, URLs, and the JS string literal it gets
    embedded into on the vote page.
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len] or "topic"


def require_env(name: str, value: str) -> str:
    """Fails fast with a clear message if a required secret/config is missing."""
    if not value:
        raise SystemExit(
            f"Missing required configuration: {name}. "
            f"Set it as a GitHub Actions secret/variable (see README.md)."
        )
    return value
