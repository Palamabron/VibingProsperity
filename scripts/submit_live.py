from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv
from loguru import logger
from prosperity_token import ensure_prosperity_id_token, try_refresh_token_from_env_credentials

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_BASE = "https://3dzqiahkw1.execute-api.eu-west-1.amazonaws.com/prod"
_SUBMIT = f"{_BASE}/submission/algo"

POLL_INTERVAL = 10
POLL_TIMEOUT = 600

SUBMISSIONS_DIR = ROOT / "reports" / "submissions_live"
SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _prompt_new_token() -> str:
    logger.warning("401 — token expired or rejected by API")
    t = try_refresh_token_from_env_credentials()
    if t:
        logger.info("Refreshed PROSPERITY_ID_TOKEN from saved credentials.")
        return t
    logger.info(
        "1. Go to https://prosperity.imc.com — log OUT then log IN again\n"
        "2. F12 → Console, paste:\n\n"
        "   const origFetch = window.fetch;\n"
        "   window.fetch = async (...args) => {\n"
        "     const req = args[0];\n"
        "     const opts = args[1] || {};\n"
        "     const auth = opts?.headers?.Authorization || opts?.headers?.authorization\n"
        "       || (opts?.headers instanceof Headers ? opts.headers.get('authorization') : null)\n"
        "       || (req instanceof Request ? req.headers.get('authorization') : null);\n"
        "     if(auth) console.log('TOKEN FOUND:', auth);\n"
        "     return origFetch(...args);\n"
        "   };\n\n"
        "3. Navigate the site until TOKEN FOUND appears in Console\n"
        "4. Copy value after 'Bearer ' → update .env: PROSPERITY_ID_TOKEN=eyJ..."
    )
    input("Press Enter when .env is updated...")
    load_dotenv(ROOT / ".env", override=True)
    return os.getenv("PROSPERITY_ID_TOKEN", "").strip()


def _hdrs(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Origin": "https://prosperity.imc.com",
    }


def _upload(client: httpx.Client, token: str, code: str, algo_name: str) -> tuple[str, str]:
    for _ in range(3):
        headers = {"Authorization": f"Bearer {token}", "Origin": "https://prosperity.imc.com"}
        files = {"file": (algo_name, code.encode(), "text/x-python")}
        r = client.post(_SUBMIT, headers=headers, files=files, timeout=30)
        if r.status_code == 401:
            token = _prompt_new_token()
            continue
        r.raise_for_status()
        d = r.json()
        data = d.get("data") or d
        sid = data.get("submissionId") or data.get("id") or data.get("submission_id")
        if not sid:
            raise RuntimeError(f"no submission ID in response: {d}")
        return str(sid), token
    logger.error("Too many 401 responses")
    sys.exit(1)


def _poll_status(client: httpx.Client, token: str, sub_id: str) -> dict[str, Any]:
    url = f"{_BASE}/submissions/algo/1?page=1&pageSize=50"
    r = client.get(url, headers=_hdrs(token), timeout=30)
    r.raise_for_status()
    items = (r.json().get("data") or {}).get("items") or []
    for item in items:
        if str(item.get("id")) == str(sub_id):
            return cast(dict[str, Any], item)
    return {}


def _fetch_graph_profit(client: httpx.Client, token: str, sub_id: str) -> int | None:
    try:
        r = client.get(f"{_BASE}/submissions/algo/{sub_id}/graph", headers=_hdrs(token), timeout=30)
        if r.status_code != 200:
            return None
        s3_url = (r.json().get("data") or {}).get("url")
        if not s3_url:
            return None
        r2 = client.get(s3_url, timeout=30)
        series = r2.json() if r2.status_code == 200 else None
        if isinstance(series, list) and series:
            return int(round(series[-1]["value"]))
    except Exception as e:
        logger.warning("graph fetch error: {}", e)
    return None


def _fetch_zip_log(
    client: httpx.Client, token: str, sub_id: str, ts: str
) -> tuple[str | None, str | None]:
    try:
        r = client.get(f"{_BASE}/submissions/algo/{sub_id}/zip", headers=_hdrs(token), timeout=30)
        if r.status_code != 200:
            return None, None
        s3_url = (r.json().get("data") or {}).get("url")
        if not s3_url:
            return None, None
        r2 = client.get(s3_url, timeout=120)
        if r2.status_code != 200:
            return None, None
        with zipfile.ZipFile(io.BytesIO(r2.content)) as zf:
            parts = []
            for name in sorted(zf.namelist()):
                try:
                    raw = zf.read(name).decode("utf-8", errors="replace")
                    if name.endswith(".txt") or name.endswith(".json"):
                        try:
                            obj = json.loads(raw)
                            graph = obj.get("graphLog", "")
                            if graph:
                                lines = graph.strip().split("\n")
                                tail = lines[-50:] if len(lines) > 50 else lines[1:]
                                parts.append(
                                    "=== PnL timeseries (last 50 points) ===\n"
                                    + lines[0]
                                    + "\n"
                                    + "\n".join(tail)
                                )
                            positions = obj.get("positions", [])
                            if positions:
                                parts.append(
                                    "=== Final positions ===\n" + json.dumps(positions, indent=2)
                                )
                            activities = obj.get("activitiesLog", "")
                            if activities:
                                alines = activities.strip().split("\n")
                                atail = alines[-200:] if len(alines) > 200 else alines[1:]
                                parts.append(
                                    "=== Activities log (last 200 rows) ===\n"
                                    + alines[0]
                                    + "\n"
                                    + "\n".join(atail)
                                )
                        except json.JSONDecodeError:
                            parts.append(f"=== {name} ===\n{raw[:2000]}")
                    else:
                        parts.append(f"=== {name} ===\n{raw[:500]}")
                except Exception:
                    pass
            log_text = "\n\n".join(parts) if parts else None
        if log_text:
            lp = SUBMISSIONS_DIR / f"{ts}_{sub_id}.log"
            lp.write_text(log_text, encoding="utf-8")
            logger.info("log → {}", lp.relative_to(ROOT))
            return log_text, str(lp)
    except Exception as e:
        logger.warning("zip fetch error: {}", e)
    return None, None


def _parse_log_profit(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {"total_profit": None, "per_product": {}}
    for match in re.finditer(r"^\s*([A-Z_]{3,})\s+([\+\-]?\d[\d,]*\.?\d*)\s*$", text, re.MULTILINE):
        out["per_product"][match.group(1)] = float(match.group(2).replace(",", ""))
    total_m = re.search(r"(?i)total[^\d\-\+]*([\+\-]?\d[\d,]*\.?\d*)", text)
    if total_m:
        out["total_profit"] = int(round(float(total_m.group(1).replace(",", ""))))
    elif out["per_product"]:
        out["total_profit"] = int(round(sum(out["per_product"].values())))
    return out


def submit_and_wait(algo_path: Path | None = None) -> dict[str, Any]:
    if algo_path is None:
        algo_path = ROOT / "algorithm.py"

    token = ensure_prosperity_id_token()
    code = algo_path.read_text(encoding="utf-8")
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    result: dict[str, Any] = {
        "submission_id": None,
        "status": "unknown",
        "total_profit": None,
        "per_product": {},
        "log_text": None,
        "log_path": None,
        "timestamp": ts,
        "error": None,
    }

    logger.info("uploading {} …", algo_path.name)

    with httpx.Client() as client:
        try:
            sub_id, token = _upload(client, token, code, algo_path.name)
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            return result

        result["submission_id"] = sub_id
        logger.info("submission_id={}", sub_id)

        deadline = time.monotonic() + POLL_TIMEOUT
        status_item: dict[str, Any] = {}

        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL)
            try:
                status_item = _poll_status(client, token, sub_id)
            except Exception as exc:
                logger.warning("poll error (retry): {}", exc)
                continue

            state = (status_item.get("status") or "").lower()
            logger.info("state={!r}", state)

            if state in {"done", "success", "finished", "completed"}:
                result["status"] = "success"
                break
            if state in {"error", "failed", "failure", "invalid", "error_finished"}:
                result["status"] = "error"
                result["error"] = "simulation failed"
                return result
        else:
            result["status"] = "timeout"
            result["error"] = f"no result after {POLL_TIMEOUT}s"
            return result

        profit = _fetch_graph_profit(client, token, sub_id)
        if profit is not None:
            result["total_profit"] = profit

        log_text, log_path = _fetch_zip_log(client, token, sub_id, ts)
        result["log_text"] = log_text
        result["log_path"] = log_path

        if log_text and not result["per_product"]:
            parsed = _parse_log_profit(log_text)
            result["per_product"] = parsed.get("per_product", {})
            if result["total_profit"] is None:
                result["total_profit"] = parsed.get("total_profit")

    profit = result["total_profit"]
    logger.info("{}", "═" * 52)
    logger.info("LIVE RESULT")
    logger.info("{}", "═" * 52)
    if profit is not None:
        logger.info("total_profit: {:+,}", profit)
    else:
        logger.info("total_profit: (not parsed)")
    for p, v in sorted(result["per_product"].items()):
        logger.info("{:<26} {:+,.0f}", p, v)
    logger.info("{}", "═" * 52)

    return result


if __name__ == "__main__":
    algo = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out = submit_and_wait(algo)
    out_print = {k: v for k, v in out.items() if k != "log_text"}
    sys.stdout.write(json.dumps(out_print, indent=2) + "\n")
    sys.exit(0 if out["status"] == "success" else 1)
