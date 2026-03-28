from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass

import tyro
from loguru import logger
from prosperity_token import fetch_token_via_playwright, write_prosperity_token_to_env

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


def manual() -> None:
    logger.info("{}", _INSTRUCTIONS)
    token = input("Paste token here: ").strip()
    write_prosperity_token_to_env(token)


def auto(email: str, password: str) -> None:
    token = fetch_token_via_playwright(email, password)
    write_prosperity_token_to_env(token)


@dataclass
class GetTokenArgs:
    """Fetch Prosperity Cognito ID token (manual paste or Playwright auto-login)."""

    auto: bool = False
    """Use Playwright to log in and read token from localStorage."""

    email: str = ""
    """Email (or set PROSPERITY_EMAIL). Required with --auto if env unset."""

    password: str = ""
    """Password (or PROSPERITY_PASSWORD). If empty with --auto, prompt once."""


def main() -> None:
    args = tyro.cli(GetTokenArgs)
    if args.auto:
        email = args.email or os.getenv("PROSPERITY_EMAIL", "")
        password = args.password or os.getenv("PROSPERITY_PASSWORD", "")
        if not email:
            logger.error("--auto needs --email (or PROSPERITY_EMAIL in .env)")
            sys.exit(1)
        if not password:
            password = getpass.getpass(
                "Prosperity password (hidden; set PROSPERITY_PASSWORD in .env to skip): "
            )
        if not password:
            logger.error("Password required for --auto.")
            sys.exit(1)
        auto(email, password)
    else:
        manual()


if __name__ == "__main__":
    main()
