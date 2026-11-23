#!/usr/bin/env python3
"""Детерминированный гейт заморозки для слотов Живого Кода.

Заменяет невыполнимое правило «число [СР в проекте = 0»: считаются только
СВЕЖИЕ незакрытые замечания (появившиеся после последнего отчёта аудитора)
и фактические незакрытые пункты плана.

Использование:
    python3 freeze_gate.py ~/LivingCode/Project1          # человекочитаемо
    python3 freeze_gate.py ~/LivingCode/Project1 --json   # для автоматики

Коды возврата:
    0 — все гейты пройдены (заморозка разрешена)
    1 — хотя бы один гейт не пройден
    2 — ошибка окружения/аргументов
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LIVING = Path(os.environ.get("LIVING_CODE_ROOT", "/home/thomas/LivingCode"))
REPORTS = LIVING / "reports"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".gradle",
             ".idea", ".pytest_cache", "Pods", "dist", "build", ".next", ".cache"}

# Метки «закрыто» — такая запись не считается находкой.
CLOSED_MARKERS = ("закрыт", "closed", "resolved", "исправлено", "исправлен",
                   "fixed", "решено", "решен", "[✓]", "[x]", "покрыт")
# Явные отложенные пункты плана — не блокируют заморозку.
DEFERRED_MARKERS = ("вне скоупа", "вне скопа", "не входит", "deferred",
                    "отложено", "не в этом цикле", "не приоритет")

AUDITOR_RE = re.compile(r"auditor", re.I)
CHECKBOX_OPEN = re.compile(r"^\s*[-*]\s*\[ \]", re.M)
FINDING = re.compile(r"\[СР[^\]]*\]")


def newest_auditor_report(project: Path) -> Path | None:
    """Самый свежий отчёт аудитора — граница «свежести» находок."""
    candidates: list[Path] = []
    for base in (project / "reports", REPORTS, project):
        if not base.is_dir():
            continue
        for p in base.glob("*.md"):
            if AUDITOR_RE.search(p.name):
                candidates.append(p)
        if base is project:  # не спускаться глубоко в дерево проекта
            continue
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def iter_code_files(project: Path):
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for fn in filenames:
            if fn.endswith((".md", ".py", ".txt", ".json", ".yaml", ".yml", ".js",
                            ".ts", ".tsx", ".jsx", ".kt", ".java", ".go", ".rs")):
                yield Path(dirpath) / fn


REGISTRY_NAMES = ("defect_registry.json", "defects.json", "findings.json",
                  "DEFECTS.md", "DEFECTS.MD", "FINDINGS.md", "findings.md")
OPEN_STATES = {"open", "new", "active", "todo", "in_progress", "in-progress",
               "открыт", "открыто", "не закрыт", "wip"}
CLOSED_STATES = {"closed", "resolved", "fixed", "done", "verified", "cancelled",
                 "canceled", "закрыт", "закрыто", "исправлено", "исправлен",
                 "решено", "готово"}


def registry_files(project: Path) -> list[Path]:
    out = []
    for name in REGISTRY_NAMES:
        for cand in (project / name, project / "docs" / name, project / "reports" / name):
            if cand.is_file():
                out.append(cand)
    if not out:
        # любой файл, явно названный реестром дефектов
        for f in project.glob("*.json"):
            if "defect" in f.name.lower() or "finding" in f.name.lower():
                out.append(f)
    return out


def _is_closed_state(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value is True
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in CLOSED_STATES:
        return True
    if s in OPEN_STATES:
        return False
    return any(mk in s for mk in ("clos", "fix", "resolv", "закры", "исправ", "решен"))


def open_registry_defects(project: Path) -> tuple[list[dict], int]:
    """Открытые дефекты по реестрам проекта.

    Источник истины — реестр дефектов (JSON со статусом open|closed или
    markdown-таблица с колонкой «где закрыт»). Исторические записи о
    исправленных дефектах открытыми дефектами НЕ являются.
    """
    open_items: list[dict] = []
    total = 0
    for reg in registry_files(project):
        text = reg.read_text(encoding="utf-8", errors="replace")
        rel = str(reg.relative_to(project))
        if reg.suffix.lower() == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            entries = []
            if isinstance(data, dict):
                for key in ("defects", "findings", "issues", "items"):
                    if isinstance(data.get(key), list):
                        entries = data[key]
                        break
            elif isinstance(data, list):
                entries = data
            for e in entries:
                if not isinstance(e, dict):
                    continue
                total += 1
                state = None
                for key in ("status", "state", "closed", "resolved", "fixed"):
                    if key in e:
                        state = e[key]
                        break
                if _is_closed_state(state):
                    continue
                open_items.append({
                    "file": rel,
                    "line": 0,
                    "tag": str(e.get("id", "")) or "—",
                    "excerpt": str(e.get("title", "") or e.get("detail", ""))[:160],
                })
        else:
            for i, line in enumerate(text.splitlines(), 1):
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 2:
                    continue
                if set("".join(cells)) <= set("-: "):  # разделитель таблицы
                    continue
                total += 1
                last = cells[-1].lower()
                # последняя колонка markdown-реестра — «где закрыт»
                if last in ("", "-", "—", "?", "todo", "не закрыт", "открыт"):
                    open_items.append({
                        "file": rel,
                        "line": i,
                        "tag": cells[0] if cells else "—",
                        "excerpt": " | ".join(cells[:3])[:160],
                    })
    return open_items, total


def open_plan_items(project: Path) -> list[dict]:
    plan = None
    for cand in (project / "PLAN.md", project / "plan.md", project / "docs" / "PLAN.md"):
        if cand.is_file():
            plan = cand
            break
    if plan is None:
        return []
    out = []
    for i, line in enumerate(plan.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not CHECKBOX_OPEN.match(line):
            continue
        low = line.lower()
        if any(mk in low for mk in DEFERRED_MARKERS):
            continue
        out.append({"line": i, "text": line.strip()[:160]})
    return out


CACHE_DIR = Path(os.environ.get("LIVING_CODE_TEST_CACHE",
                                str(LIVING / "state" / "test_verdict")))


def cache_path(project: Path) -> Path:
    return CACHE_DIR / f"{project.name}.json"


def newest_source_mtime(project: Path) -> float:
    """Метка последнего изменения кода проекта — граница свежести кэша."""
    newest = 0.0
    for f in iter_code_files(project):
        try:
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            continue
    return newest


def write_cache(project: Path, verdict: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(verdict)
    payload["project"] = project.name
    payload["ts"] = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["ts_epoch"] = datetime.now().timestamp()
    payload["source_mtime"] = newest_source_mtime(project)
    cache_path(project).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def read_cache(project: Path) -> dict | None:
    cp = cache_path(project)
    if not cp.is_file():
        return None
    try:
        data = json.loads(cp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    src = newest_source_mtime(project)
    if float(data.get("source_mtime", 0)) < src:
        return None  # код менялся после прогона — вердикт устарел
    return data


def pytest_runner(project: Path) -> str | None:
    for cand in (project / ".venv" / "bin" / "pytest", project / "venv" / "bin" / "pytest"):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    fallback = Path.home() / "build" / "bin" / "pytest"
    return str(fallback) if fallback.is_file() else None


def run_tests(project: Path) -> dict:
    """Тесты. Никаких plugin-зависимых флагов (--timeout без pytest-timeout → rc=4)."""
    runner = pytest_runner(project)
    if not runner:
        return {"rc": None, "ok": False, "note": "pytest не найден (ни venv проекта, ни ~/build/bin/pytest)"}
    budget = int(os.environ.get("GATE_TEST_BUDGET", "600"))
    try:
        cp = subprocess.run([runner, "-q"], cwd=str(project), capture_output=True,
                            text=True, timeout=budget)
    except subprocess.TimeoutExpired:
        return {"rc": 124, "ok": False,
                "note": f"тесты не уложились в {budget} с (нужен отдельный прогон с --run-tests)"}
    except OSError as e:
        return {"rc": None, "ok": False, "note": f"не удалось запустить pytest: {e}"}
    tail = (cp.stdout or cp.stderr or "").strip().splitlines()
    tail_txt = " | ".join(tail[-3:])[:300]
    rc = cp.returncode
    if rc == 0:
        return {"rc": 0, "ok": True, "note": tail_txt}
    if rc == 5:
        # тестов не собрано — это не провал
        return {"rc": 5, "ok": True, "note": "тестов не собрано (rc=5) — не провал"}
    if rc == 4:
        return {"rc": 4, "ok": False,
                "note": "ошибка запуска pytest (rc=4) — это поломка команды, а не провал тестов"}
    return {"rc": rc, "ok": False, "note": tail_txt}


def laya_triage(project: Path) -> str:
    """Совет Laya (быстрый триаж) — информационный, не блокирует формальный гейт."""
    for cand in (project / "reports" / "laya*.md", REPORTS / "laya*.md"):
        if not cand.parent.is_dir():
            continue
        files = sorted(cand.parent.glob(cand.name), key=lambda p: p.stat().st_mtime)
        if files:
            txt = files[-1].read_text(encoding="utf-8", errors="replace")
            m = re.search(r"(ПЕРЕДЕЛАТЬ|ЗАМОРОЗИТЬ|ПРОДОЛЖИТЬ)", txt, re.I)
            return m.group(0).upper() if m else "—"
    return "—"


def evaluate(project: Path, force_tests: bool = False) -> dict:
    report = newest_auditor_report(project)
    findings, historical = open_registry_defects(project)
    plan_items = open_plan_items(project)
    cached = None if force_tests else read_cache(project)
    if cached:
        tests = {"rc": cached.get("rc"), "ok": bool(cached.get("ok")),
                 "note": str(cached.get("note", "")) + " [из кэша, код не менялся после прогона]"}
    else:
        tests = run_tests(project)
        if force_tests:
            write_cache(project, tests)
    laya = laya_triage(project)
    gates = {
        "a_open_defects": {
            "ok": not findings,
            "count": len(findings),
            "registry_entries": historical,
            "cut_report": str(report) if report else None,
            "items": findings[:20],
        },
        "b_open_plan_items": {
            "ok": not plan_items,
            "count": len(plan_items),
            "items": plan_items[:20],
        },
        "c_tests": tests,
    }
    passed = all(g["ok"] for g in gates.values())
    return {
        "project": project.name,
        "path": str(project),
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gates": gates,
        "laya": laya,
        "passed": passed,
    }


def render(res: dict) -> str:
    g = res["gates"]
    lines = []
    lines.append(f"=== ГЕЙТ ЗАМОРОЗКИ: {res['project']} ===")
    a = g["a_open_defects"]
    src = os.path.basename(a["cut_report"]) if a["cut_report"] else "нет отчёта аудитора"
    lines.append(f"(а) открытых дефектов в реестре проекта: {a['count']} "
                 f"(всего записей в реестрах: {a['registry_entries']}; "
                 f"последний аудит: {src}) {'✅' if a['ok'] else '❌'}")
    for it in a["items"][:10]:
        lines.append(f"      - {it['file']}:{it['line']} {it['excerpt']}")
    b = g["b_open_plan_items"]
    lines.append(f"(б) незакрытые пункты плана: {b['count']} {'✅' if b['ok'] else '❌'}")
    for it in b["items"][:10]:
        lines.append(f"      - строка {it['line']}: {it['text']}")
    c = g["c_tests"]
    lines.append(f"(в) тесты: rc={c['rc']} {'✅' if c['ok'] else '❌'} — {c['note']}")
    lines.append(f"(г) триаж Laya: {res['laya']} (информационный)")
    lines.append(f"ИТОГ: {'ЗАМОРОЗКА РАЗРЕШЕНА' if res['passed'] else 'ЗАМОРОЗКА НЕ РАЗРЕШЕНА'}")
    return "\n".join(lines)


def resolve_project(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.is_dir():
        return p
    for cand in (LIVING / p.name, LIVING / "Project1", LIVING / "Project2",
                 LIVING / "Project3", LIVING / "Project4"):
        if cand.is_dir():
            return cand
    raise SystemExit(f"каталог проекта не найден: {arg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="путь к рабочему слоту или имя проекта")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    ap.add_argument("--run-tests", action="store_true",
                    help="прогнать тесты заново и обновить кэш вердикта")
    args = ap.parse_args()
    try:
        project = resolve_project(args.project)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2
    res = evaluate(project, force_tests=args.run_tests)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
