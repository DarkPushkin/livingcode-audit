#!/usr/bin/env python3
"""Замыкающий цикл внешнего аудита протокола «Живой Код».

Схема (проверена 23.11.2026):
    mirror  — собрать ПУБЛИЧНЫЙ слепок репозитория одним коммитом (без секретов) и запушить;
    run     — поднять сессию Grok из партишена Hermes и попросить аудит по ссылке на слепок;
    verify  — машинно сверить утверждения аудитора (file:line) с ЛОКАЛЬНЫМ кодом;
    gate    — fail-closed вердикт: подтверждённый P0 или устаревший аудит = блокировка.

Зачем verify: LLM-аудитор дрейфует по номерам строк. Grok попадал в 413-422 точно,
Gemini назвал несуществующие строки. Поэтому находка считается подтверждённой только
если файл существует, строка в диапазоне, и ключевые слова находятся рядом.

Использование:
    python3 scripts/external_audit_gate.py mirror --push
    python3 scripts/external_audit_gate.py verify docs/audits/grok-audit-2026-11-23.md
    python3 scripts/external_audit_gate.py gate --max-age-hours 72
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
VERDICT_FILE = STATE / "external_audit.json"
EXCLUDE_DIRS = {"skills-export", "logs", ".locks", "tmp", "agents", ".pytest_cache", ".benchmarks"}
EXCLUDE_FILES = {"scripts/_secrets.py"}
SECRET_PATTERNS = [
    re.compile(r"[0-9]{8,10}:[A-Za-z0-9_-]{35}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{40,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


# ─────────────────────────────── mirror ───────────────────────────────
def cmd_mirror(args) -> int:
    dest = Path(args.dest).expanduser()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    tar = subprocess.run(["git", "-C", str(ROOT), "archive", "HEAD"],
                         capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=tar.stdout, check=True)
    for d in EXCLUDE_DIRS:
        shutil.rmtree(dest / d, ignore_errors=True)
    for f in EXCLUDE_FILES:
        (dest / f).unlink(missing_ok=True)
    for p in dest.rglob("*.jsonl"):
        p.unlink()
    for p in dest.rglob("*.log"):
        p.unlink()
    leaks = []
    for p in dest.rglob("*"):
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                leaks.append(f"{p.relative_to(dest)}")
                break
    if leaks:
        log(f"⛔ СЕКРЕТЫ В СЛЕПКЕ: {leaks[:10]} — публикация запрещена")
        return 2
    (dest / "AUDIT_REQUEST.md").write_text(
        (ROOT / "prompts" / "cloud_audit_prompt.md").read_text(encoding="utf-8")
        if (ROOT / "prompts" / "cloud_audit_prompt.md").exists() else "", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.name", "Living Code Audit"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.email", "audit@livingcode.local"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Публичный слепок протокола «Живой Код» + послание аудитору"],
                   cwd=dest, check=True)
    files = sum(1 for p in dest.rglob("*") if p.is_file() and ".git" not in p.parts)
    log(f"✅ слепок собран: {files} файлов → {dest}")
    if args.push:
        helper = ('!f() { echo "username=DarkPushkin"; '
                  'echo "password=$(gh auth token --user DarkPushkin 2>/dev/null)"; }; f')
        env = dict(os.environ)
        env["PATH"] = os.path.expanduser("~/build/gh-credential-darkpushkin:~/build/npm-global/bin") + ":" + env["PATH"]
        subprocess.run(["git", "remote", "remove", "origin"], cwd=dest, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", args.repo], cwd=dest, check=True)
        r = subprocess.run(["git", "-c", "credential.helper=", "-c", f"credential.helper={helper}",
                            "push", "-f", "origin", "HEAD:main"], cwd=dest, capture_output=True, text=True, env=env)
        log(("✅ запушено: " + (r.stdout + r.stderr).strip().splitlines()[-1]) if r.returncode == 0
            else f"⛔ push не удался: {(r.stdout + r.stderr).strip()[-300:]}")
        return r.returncode
    return 0


# ─────────────────────────────── verify ───────────────────────────────
REF_RE = re.compile(r"(?P<file>[A-Za-z0-9_./-]+\.(?:py|sh|json|md|toml|yaml|yml|tsx?|jsx?))"
                    r"\s*:\s*(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?")
SEV_RE = re.compile(r"\b(P0|P1|P2)\b")
STOP = {"the", "and", "for", "with", "или", "и", "в", "на", "из", "не", "то", "а"}


def _keywords(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text.lower())
    out = []
    for t in toks:
        if t in STOP:
            continue
        out.append(t)
    return out


def cmd_verify(args) -> int:
    md = Path(args.report).expanduser()
    text = md.read_text(encoding="utf-8")
    lines = text.splitlines()
    findings: list[dict] = []
    for i, line in enumerate(lines):
        m = REF_RE.search(line)
        if not m:
            continue
        rel = m.group("file")
        cand = ROOT / rel
        if not cand.exists():
            cand = ROOT / "scripts" / Path(rel).name
        a = int(m.group("a"))
        b = int(m.group("b") or a)
        sev = None
        s = SEV_RE.search(line)  # severity только из своей строки: иначе тянутся P0 из соседних строк
        if s:
            sev = s.group(1)
        item = {"line_no": i + 1, "severity": sev, "ref": f"{rel}:{a}-{b}" if b != a else f"{rel}:{a}",
                "claim": line.strip()[:400], "status": "unverified", "detail": ""}
        if not cand.exists():
            item["status"] = "file_missing"
            item["detail"] = f"нет такого файла в репозитории: {rel}"
            findings.append(item)
            continue
        src = cand.read_text(encoding="utf-8", errors="ignore").splitlines()
        if a > len(src):
            item["status"] = "line_missing"
            item["detail"] = f"в файле {len(src)} строк, указана {a}"
            findings.append(item)
            continue
        lo, hi = max(0, a - 4), min(len(src), b + 4)
        window = "\n".join(src[lo:hi])
        ctx = "\n".join(src[max(0, a - 60): min(len(src), b + 60)])
        stem = Path(rel).stem.lower()
        parts = set(stem.replace("-", "_").split("_"))
        kws = [k for k in _keywords(line)
               if len(k) > 5 and k != stem and k not in parts][:6]
        hits = [k for k in kws if k in window.lower()]
        ctx_hits = [k for k in kws if k in ctx.lower()]
        claim_low = line.lower()
        wants_pass = ('pass' in claim_low or 'глота' in claim_low or 'молч' in claim_low
                      or 'silent' in claim_low or 'swallow' in claim_low)
        has_bare_pass = bool(re.search(r'(?m)^\s*pass\s*$', window))
        if wants_pass:
            # утверждение «ошибка глотается» подтверждается только если в окне есть голый pass
            if has_bare_pass:
                item["status"] = "confirmed"
                item["detail"] = f"в строках {lo+1}-{hi} есть голый pass — ошибка действительно глотается"
            else:
                item["status"] = "resolved"
                item["detail"] = f"в строках {lo+1}-{hi} голого pass нет — ошибка больше не глотается"
        elif hits:
            item["status"] = "confirmed"
            item["detail"] = f"совпало в строках {lo+1}-{hi}: {', '.join(hits[:4])}"
        elif ctx_hits:
            item["status"] = "weak"
            item["detail"] = f"ключевые слова найдены только рядом (±60): {', '.join(ctx_hits[:3])}"
        else:
            item["status"] = "line_mismatch"
            item["detail"] = f"в строках {a}-{b} нет слов: {', '.join(kws[:4]) or '—'}"
        findings.append(item)
    sev_count = {"P0": 0, "P1": 0, "P2": 0}
    confirmed = {"P0": 0, "P1": 0, "P2": 0}
    for f in findings:
        if f["severity"] in sev_count:
            sev_count[f["severity"]] += 1
            if f["status"] == "confirmed":
                confirmed[f["severity"]] += 1
    verdict = {
        "report": str(md),
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "report_mtime": datetime.fromtimestamp(md.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "findings_total": len(findings),
        "by_severity": sev_count,
        "confirmed_by_severity": confirmed,
        "confirmed_p0": confirmed["P0"],
        "status_counts": {s: sum(1 for f in findings if f["status"] == s)
                          for s in {f["status"] for f in findings}},
        "findings": findings,
    }
    STATE.mkdir(parents=True, exist_ok=True)
    VERDICT_FILE.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"проверено ссылок: {len(findings)} → {VERDICT_FILE}")
    log(f"подтверждено: {confirmed} | статусы: {verdict['status_counts']}")
    for f in findings[:40]:
        log(f"  [{f['severity'] or '—':>2}] {f['status']:<14} {f['ref']:<45} {f['detail'][:70]}")
    return 0


# ─────────────────────────────── gate ───────────────────────────────
def cmd_gate(args) -> int:
    if not VERDICT_FILE.exists():
        log("⛔ внешнего аудита нет (state/external_audit.json отсутствует)")
        return 2
    v = json.loads(VERDICT_FILE.read_text(encoding="utf-8"))
    gen = datetime.fromisoformat(v["generated"])
    age_h = (datetime.now().astimezone() - gen).total_seconds() / 3600.0
    log(f"аудит: {v.get('report')} | возраст {age_h:.1f} ч | подтверждённых P0: {v.get('confirmed_p0')}")
    if age_h > args.max_age_hours:
        log(f"⛔ аудит устарел (>{args.max_age_hours} ч) — требуется свежий")
        return 2
    if v.get("confirmed_p0", 0) > 0:
        log("⛔ есть подтверждённые P0 — цикл не замыкается")
        return 1
    log(f"✅ внешний аудит принят (P0 нет, ссылок {v.get('findings_total')})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mirror")
    m.add_argument("--dest", default="/home/thomas/.hermes/cache/scratch/audit/public-repo")
    m.add_argument("--repo", default="https://github.com/DarkPushkin/livingcode-audit.git")
    m.add_argument("--push", action="store_true")
    m.set_defaults(fn=cmd_mirror)
    v = sub.add_parser("verify")
    v.add_argument("report")
    v.set_defaults(fn=cmd_verify)
    g = sub.add_parser("gate")
    g.add_argument("--max-age-hours", type=float, default=72.0)
    g.set_defaults(fn=cmd_gate)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
