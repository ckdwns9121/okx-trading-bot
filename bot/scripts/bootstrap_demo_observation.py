#!/usr/bin/env python3
"""Bootstrap safe OKX demo forward-observation strategy configs.

Default mode is dry-run. Use --apply to write configs through the running API,
and --start only when you explicitly want to start the demo trading engine.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from app.config import settings  # noqa: E402
from app.core.demo_observation import (  # noqa: E402
    DEFAULT_DEMO_OBSERVATION_PAIRS,
    build_demo_observation_configs,
    validate_demo_observation_settings,
)


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc
    return json.loads(body) if body else {}


def _parse_pairs(raw: str) -> list[str]:
    return [pair.strip() for pair in raw.split(",") if pair.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000",
        help="Running Bot API base URL",
    )
    parser.add_argument(
        "--pairs",
        default=",".join(DEFAULT_DEMO_OBSERVATION_PAIRS),
        help="Comma-separated OKX SWAP instruments",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write configs through PUT /api/config. Without this flag only prints a plan.",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="After applying configs, POST /api/trading/start. Requires --apply.",
    )
    args = parser.parse_args(argv)

    if args.start and not args.apply:
        parser.error("--start requires --apply")

    problems = validate_demo_observation_settings(settings)
    if problems:
        print("Refusing to continue because demo safety settings are not ready:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 2

    payloads = build_demo_observation_configs(_parse_pairs(args.pairs), is_active=True)
    print(json.dumps({"planned_configs": payloads}, indent=2, sort_keys=True))

    if not args.apply:
        print("Dry-run only. Re-run with --apply to write configs; add --start to start demo trading.")
        return 0

    api_url = args.api_url.rstrip("/")
    health = _request_json("GET", f"{api_url}/api/health")
    api_mode = (health.get("okx_api") or {}).get("mode")
    if api_mode != "demo":
        raise RuntimeError(f"Running API reports OKX mode {api_mode!r}; expected 'demo'")
    if health.get("db") != "ok":
        raise RuntimeError(f"Running API database health is not ok: {health.get('db')!r}")
    if args.start and (health.get("okx_api") or {}).get("status") != "ok":
        raise RuntimeError("OKX API health must be ok before starting demo trading")

    applied = []
    for payload in payloads:
        applied.append(_request_json("PUT", f"{api_url}/api/config", payload))
    print(json.dumps({"applied_configs": applied}, indent=2, sort_keys=True))

    if args.start:
        started = _request_json("POST", f"{api_url}/api/trading/start")
        print(json.dumps({"trading_start": started}, indent=2, sort_keys=True))
    else:
        print("Configs applied. Trading engine not started; add --start when ready for demo observation.")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
