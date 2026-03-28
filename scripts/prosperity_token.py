"""Prosperity Cognito JWT: persist to .env, detect expiry, optional Playwright refresh."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def normalize_bearer_token(raw: str) -> str:
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def jwt_exp_unix(token: str) -> int | None:
    """Return JWT `exp` claim (unix seconds) or None if missing/unparseable."""
    token = normalize_bearer_token(token)
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    pad = (-len(payload_b64)) % 4
    if pad:
        payload_b64 += "=" * pad
    try:
        raw_payload = base64.urlsafe_b64decode(payload_b64)
        data = json.loads(raw_payload)
        exp = data.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def token_needs_refresh(token: str, leeway_seconds: int = 120) -> bool:
    """True if missing, malformed, or expiring within leeway_seconds."""
    token = normalize_bearer_token(token)
    if not token:
        return True
    exp = jwt_exp_unix(token)
    if exp is None:
        return True
    return time.time() >= float(exp) - leeway_seconds


def write_prosperity_token_to_env(token: str) -> None:
    token = normalize_bearer_token(token)
    if not token:
        logger.warning("Empty token — nothing saved.")
        return
    if ENV_FILE.exists():
        txt = ENV_FILE.read_text(encoding="utf-8")
        if "PROSPERITY_ID_TOKEN" in txt:
            txt = re.sub(
                r"^PROSPERITY_ID_TOKEN=.*$",
                f"PROSPERITY_ID_TOKEN={token}",
                txt,
                flags=re.MULTILINE,
            )
        else:
            txt += f"\nPROSPERITY_ID_TOKEN={token}\n"
    else:
        txt = f"PROSPERITY_ID_TOKEN={token}\n"
    ENV_FILE.write_text(txt, encoding="utf-8")
    os.environ["PROSPERITY_ID_TOKEN"] = token
    logger.info("Token saved to {}", ENV_FILE.relative_to(ROOT))


def fetch_token_via_playwright(email: str, password: str) -> str:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        logger.error(
            "Playwright not installed. Run: uv add playwright && uv run playwright install chromium"
        )
        raise

    logger.info("Launching browser for Prosperity login …")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://prosperity.imc.com/login")
        page.wait_for_load_state("networkidle")

        try:
            page.fill('input[type="email"], input[name="email"], #email', email)
            page.fill('input[type="password"], input[name="password"], #password', password)
            page.click('button[type="submit"]')
            page.wait_for_url("**/dashboard**", timeout=30_000)
        except Exception as exc:
            browser.close()
            logger.error("Login failed: {}", exc)
            raise

        keys: list[str] = page.evaluate(
            "() => Object.keys(localStorage).filter(k => k.includes('idToken'))"
        )
        token: str | None = None
        for k in keys:
            val = page.evaluate(f"() => localStorage.getItem('{k}')")
            if val and len(val) > 100:
                token = val
                logger.info("Found token under localStorage key: {}", k)
                break

        browser.close()

    if not token:
        logger.error("Could not find idToken in localStorage.")
        raise RuntimeError("idToken not found after login")
    return token


def try_refresh_token_from_env_credentials() -> str | None:
    """
    If PROSPERITY_EMAIL and PROSPERITY_PASSWORD are set, log in via Playwright,
    write PROSPERITY_ID_TOKEN to .env, and return the new token. Otherwise None.
    """
    load_dotenv(ENV_FILE, override=True)
    email = os.getenv("PROSPERITY_EMAIL", "").strip()
    password = os.getenv("PROSPERITY_PASSWORD", "").strip()
    if not email or not password:
        return None
    try:
        token = fetch_token_via_playwright(email, password)
    except Exception:
        return None
    write_prosperity_token_to_env(token)
    load_dotenv(ENV_FILE, override=True)
    return normalize_bearer_token(os.getenv("PROSPERITY_ID_TOKEN", ""))


def ensure_prosperity_id_token() -> str:
    """
    Return a usable PROSPERITY_ID_TOKEN: load .env, refresh if missing/expired when
    PROSPERITY_EMAIL + PROSPERITY_PASSWORD are set; otherwise exit with instructions.
    """
    load_dotenv(ENV_FILE, override=True)
    raw = os.getenv("PROSPERITY_ID_TOKEN", "")
    token = normalize_bearer_token(raw)
    if token and not token_needs_refresh(token):
        return token

    refreshed = try_refresh_token_from_env_credentials()
    if refreshed:
        return refreshed

    logger.error(
        "PROSPERITY_ID_TOKEN is missing or expired.\n"
        "  • Add PROSPERITY_EMAIL and PROSPERITY_PASSWORD to .env for automatic refresh, or\n"
        "  • Run: uv run python scripts/get_token.py"
    )
    sys.exit(1)
