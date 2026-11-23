#!/usr/bin/env python3
"""Telegram Bot API без токена в argv.

Токен передаётся curl через stdin (--config -), поэтому он НЕ виден в `ps`,
в `auditd` и в истории процессов. Раньше URL собирался аргументом:
    curl ... "https://api.telegram.org/bot{TOKEN}/sendMessage"   ← утечка в argv
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SECRETS_FILE = Path("~/.hermes/secrets/cathedral_bot_token").expanduser()


def get_token() -> str:
    tok = os.environ.get("CATHEDRAL_BOT_TOKEN")
    if tok:
        return tok.strip()
    if SECRETS_FILE.exists():
        return SECRETS_FILE.read_text(encoding="utf-8").strip()
    raise RuntimeError("нет токена: CATHEDRAL_BOT_TOKEN или ~/.hermes/secrets/cathedral_bot_token")


def run_api(method: str, args: list[str] | None = None, timeout: int = 60) -> tuple[int, str, str]:
    """Формат как у локального run(): (rc, stdout, stderr)."""
    try:
        p = curl_api(method, args, timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:  # noqa: BLE001 — доставка отчёта не должна ронять цикл
        return 125, "", f"{type(exc).__name__}: {exc}"


def curl_api(method: str, args: list[str] | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """Вызвать метод Bot API. Токен уходит через stdin, не через argv."""
    token = get_token()
    if any(ch in token for ch in '"\''):
        raise RuntimeError("токен содержит недопустимые символы")
    cfg = f'url = "https://api.telegram.org/bot{token}/{method}"\n'
    cmd = ["curl", "-s", "--config", "-", "-X", "POST"] + list(args or [])
    return subprocess.run(cmd, input=cfg, capture_output=True, text=True, timeout=timeout)
