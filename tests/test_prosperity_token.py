"""Unit tests for JWT helpers in scripts/prosperity_token.py."""

from __future__ import annotations

import base64
import json
import time

from prosperity_token import jwt_exp_unix, normalize_bearer_token, token_needs_refresh


def _fake_jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_normalize_bearer_strips_prefix() -> None:
    assert normalize_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert normalize_bearer_token("  eyJx  ") == "eyJx"


def test_jwt_exp_roundtrip() -> None:
    exp = 1_700_000_000
    t = _fake_jwt(exp)
    assert jwt_exp_unix(t) == exp


def test_token_needs_refresh_empty() -> None:
    assert token_needs_refresh("") is True


def test_token_needs_refresh_future() -> None:
    t = _fake_jwt(int(time.time()) + 3600)
    assert token_needs_refresh(t, leeway_seconds=60) is False


def test_token_needs_refresh_past() -> None:
    t = _fake_jwt(int(time.time()) - 3600)
    assert token_needs_refresh(t, leeway_seconds=60) is True
