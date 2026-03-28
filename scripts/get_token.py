from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

_INSTRUCTIONS = """
╔══════════════════════════════════════════════════════════════════════╗
║              GET YOUR PROSPERITY ID TOKEN                           ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  1. Open Chrome → https://prosperity.imc.com  and log in           ║
║  2. Press F12 → Console tab                                          ║
║  3. Paste the interceptor below and press Enter:                     ║
║                                                                      ║
║     const origFetch = window.fetch;                                  ║
║     window.fetch = async (...args) => {                              ║
║       const req = args[0]; const opts = args[1] || {};              ║
║       const auth = opts?.headers?.Authorization                      ║
║         || opts?.headers?.authorization                              ║
║         || (opts?.headers instanceof Headers                         ║
║              ? opts.headers.get('authorization') : null)            ║
║         || (req instanceof Request                                   ║
║              ? req.headers.get('authorization') : null);            ║
║       if(auth) console.log('TOKEN FOUND:', auth);                   ║
║       return origFetch(...args);                                     ║
║     };                                                               ║
║                                                                      ║
║  4. Navigate the site — TOKEN FOUND will appear in Console          ║
║  5. Copy value after 'Bearer ' (starts with eyJ...)                 ║
║                                                                      ║
║  Token is valid ~1h. Re-run when you get 401 errors.               ║
╚══════════════════════════════════════════════════════════════════════╝
"""


def _write(token: str) -> None:
    token = token.strip()
    if not token:
        print("❌  Empty token — nothing saved.")
        return
    if ENV_FILE.exists():
        txt = ENV_FILE.read_text(encoding="utf-8")
        if "PROSPERITY_ID_TOKEN" in txt:
            txt = re.sub(
                r"^PROSPERITY_ID_TOKEN=.*$",
                f"PROSPERITY_ID_TOKEN={token}",
                txt, flags=re.MULTILINE,
            )
        else:
            txt += f"\nPROSPERITY_ID_TOKEN={token}\n"
    else:
        txt = f"PROSPERITY_ID_TOKEN={token}\n"
    ENV_FILE.write_text(txt, encoding="utf-8")
    print(f"✅  Token saved to {ENV_FILE.relative_to(ROOT)}")


def manual() -> None:
    print(_INSTRUCTIONS)
    token = input("Paste token here: ").strip()
    _write(token)


def auto(email: str, password: str) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "❌  Playwright not installed.\n"
            "    Run: uv add playwright && uv run playwright install chromium"
        )

    print("[get_token] launching browser …")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page    = browser.new_page()
        page.goto("https://prosperity.imc.com/login")
        page.wait_for_load_state("networkidle")

        try:
            page.fill('input[type="email"], input[name="email"], #email', email)
            page.fill('input[type="password"], input[name="password"], #password', password)
            page.click('button[type="submit"]')
            page.wait_for_url("**/dashboard**", timeout=30_000)
        except Exception as exc:
            browser.close()
            sys.exit(f"❌  Login failed: {exc}\n    Try manual mode instead.")

        keys: list[str] = page.evaluate(
            "() => Object.keys(localStorage).filter(k => k.includes('idToken'))"
        )
        token = None
        for k in keys:
            val = page.evaluate(f"() => localStorage.getItem('{k}')")
            if val and len(val) > 100:
                token = val
                print(f"[get_token] found token under: {k}")
                break

        browser.close()

    if not token:
        sys.exit("❌  Could not find idToken in localStorage. Try manual mode.")
    _write(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Prosperity Cognito ID token")
    parser.add_argument("--auto",     action="store_true")
    parser.add_argument("--email",    default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    if args.auto:
        email    = args.email    or os.getenv("PROSPERITY_EMAIL",    "")
        password = args.password or os.getenv("PROSPERITY_PASSWORD", "")
        if not email or not password:
            sys.exit("❌  --auto needs --email and --password (or PROSPERITY_EMAIL/PASSWORD in .env)")
        auto(email, password)
    else:
        manual()
