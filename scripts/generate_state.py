#!/usr/bin/env python3
"""Генератор STATE.json для проектов Живого Кода.

21.11.2026: у Project1–4 (рабочие проекты кодеров) STATE.json не было
вообще — конвейер промоушена не видел их работы, поэтому релизов не было
ни за месяц. Метрики берём из PLAN.md (чекбоксы) и git status (hot_files).

completion_pct = выполненные чекбоксы / все чекбоксы * 100
hot_files      = число изменённых отслеживаемых файлов (git status --porcelain)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _plan_completion(plan: Path) -> tuple[int, str]:
    try:
        txt = plan.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, "нет PLAN.md"
    done = len(re.findall(r"^\s*[-*]\s*\[[xX✓✅]\]", txt, re.M))
    todo = len(re.findall(r"^\s*[-*]\s*\[\s?\]", txt, re.M))
    total = done + todo
    if total == 0:
        return 0, "в PLAN.md нет чекбоксов"
    return int(round(done * 100 / total)), f"{done}/{total} чекбоксов"


FREEZE_DIR = Path("/home/thomas/LivingCode/state/freeze")
CODE_EXT = {".py", ".pyw", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go",
            ".rs", ".rb", ".php", ".pl", ".lua", ".r", ".jl", ".ex", ".exs",
            ".erl", ".scala", ".swift", ".sh", ".bash", ".md", ".rst", ".txt"}


def _freeze_ts(project: Path) -> float | None:
    f = FREEZE_DIR / f"{project.name}.json"
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["frozen_at"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _hot_files(project: Path) -> int:
    """Горячие файлы = не заморожено.

    23.11.2026: раньше здесь считался `git status --porcelain`, то есть любая
    незакоммиченная правка кодера. В активной разработке это всегда > 0 →
    ready_for_publish было всегда false → релиз не случился ни разу.
    Теперь семантика та же, что в конвейере: горячее = маркер '# HOT' или
    изменение ПОСЛЕ штампа заморозки; без заморозки — правка за 48 ч.
    """
    fts = _freeze_ts(project)
    hot = 0
    now = datetime.now().timestamp()
    for f in project.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in CODE_EXT:
            continue
        if any(p in ('.git', '__pycache__', 'node_modules', 'venv', '.venv')
               for p in f.parts):
            continue
        try:
            st = f.stat()
            with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                first = fh.readline().strip()
        except OSError:
            continue
        if first == '# HOT':
            hot += 1
        elif fts is not None:
            if st.st_mtime > fts:
                hot += 1
        elif first != '# COLD' and (now - st.st_mtime) < 48 * 3600:
            hot += 1
    return hot


def generate(project: Path) -> dict:
    pct, basis = _plan_completion(project / "PLAN.md")
    hot = _hot_files(project)
    state = {
        "project": project.name,
        "completion_pct": pct,
        "hot_files": hot,
        "ready_for_publish": pct >= 100 and hot == 0,
        "basis": basis,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (project / "STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            print(json.dumps(generate(p), ensure_ascii=False))
        else:
            print(f"нет такого проекта: {arg}", file=sys.stderr)
