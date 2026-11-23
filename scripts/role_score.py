#!/usr/bin/env python3
"""Подбор лучшей схемы ролей по замерам (владелец, 22.11.2026).

Читает state/role_runs.jsonl (замеры каждого прогона роли), считает по паре
(роль, модель): успешность, длительность, размер отчёта. Печатает таблицу и
рекомендует лучшую модель для каждой роли.

  python3 role_score.py             # таблица + рекомендации
  python3 role_score.py --json      # машинный вывод
  python3 role_score.py --apply     # записать рекомендации в rotation.json (scheme)
"""
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/home/thomas/LivingCode")
RUNS = ROOT / "state" / "role_runs.jsonl"
ROT = ROOT / "orchestration" / "rotation.json"


def load_rows():
    if not RUNS.is_file():
        return []
    rows = []
    for line in RUNS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def score(rows):
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r.get("role") or "?", r.get("model") or "?")].append(r)
    table = {}
    for (role, model), rs in buckets.items():
        ok = [x for x in rs if x.get("rc") == 0]
        durs = [x.get("duration_s") or 0 for x in ok]
        sizes = [x.get("report_bytes") or 0 for x in ok]
        acs = [int((x.get("quality") or {}).get("artifacts_checked") or 0) for x in ok]
        verdicts = sum(1 for x in ok if (x.get("quality") or {}).get("has_verdict"))
        receipts = sum(1 for x in ok if (x.get("quality") or {}).get("has_receipts"))
        finds = [int((x.get("quality") or {}).get("findings") or 0) for x in ok]
        n = max(len(ok), 1)
        table[(role, model)] = {
            "runs": len(rs),
            "ok": len(ok),
            "ok_rate": round(len(ok) / len(rs), 3) if rs else 0.0,
            "med_duration_s": round(statistics.median(durs), 1) if durs else None,
            "med_report_bytes": int(statistics.median(sizes)) if sizes else 0,
            "med_artifacts_checked": int(statistics.median(acs)) if acs else 0,
            "verdict_rate": round(verdicts / n, 3),
            "receipt_rate": round(receipts / n, 3),
            "med_findings": int(statistics.median(finds)) if finds else 0,
            "pilot_runs": sum(1 for x in rs if x.get("pilot")),
        }
    return table


# 23.11.2026: окна слотов ролей (из обёрток). Модель, чьё замеренное время
# не влезает в окно с запасом, в роль не ставится: «глубже» бесполезно, если
# слот убивают по таймауту. Именно так minimax (1163 с) не попал в Аудитора
# (900 с), а step-5 (2665 с) не попал ни в одну роль с окном ≤1200 с.
ROLE_SLOT_BUDGET = {
    "Аудитор": 900, "L3-Критик": 600, "Владыка Кода": 600, "Продюсер": 600,
    "Super-Supervisor": 600, "UI-Гейт": 600, "Профессор": 900,
    "Proposer протокола": 1200, "Искатель": 2700, "Искатель Дайджест": 2700,
    "Топик 252": 900,
    "Кодер Project1": 1200, "Кодер Project2": 1200, "Кодер Project3": 1200,
    "Кодер Project4": 1200, "Кодер Elemental Life": 1200,
    "Кодер Elemental Life 2": 1200, "Профессор Учебник": 900,
    "Судья Laya": 600,
}
FIT_HEADROOM_S = 120   # запас на отчёт, коммит и доставку


def recommend(table):
    by_role = defaultdict(list)
    for (role, model), s in table.items():
        by_role[role].append((model, s))
    rec = {}
    for role, items in by_role.items():
        # успешность 60%, отчёт 25%, скорость 15% (нормируем по лучшей в роли)
        best_dur = min((s["med_duration_s"] or 1e9) for _, s in items) or 1
        best_size = max((s["med_report_bytes"] or 0) for _, s in items) or 1
        best_ac = max((s.get("med_artifacts_checked") or 0) for _, s in items) or 1
        best_fnd = max((s.get("med_findings") or 0) for _, s in items) or 1

        def val(model, s):
            speed = 1 - min(1.0, ((s["med_duration_s"] or best_dur) - best_dur) / max(best_dur, 1))
            size_q = min(1.0, (s["med_report_bytes"] or 0) / best_size) if best_size else 0
            evidence = min(1.0, (s.get("med_artifacts_checked") or 0) / best_ac) if best_ac else 0
            verdict_q = s.get("verdict_rate") or 0.0
            receipt_q = s.get("receipt_rate") or 0.0
            depth = min(1.0, (s.get("med_findings") or 0) / best_fnd) if best_fnd else 0
            return (0.35 * s["ok_rate"] + 0.15 * verdict_q + 0.10 * receipt_q
                    + 0.15 * evidence + 0.10 * depth + 0.10 * size_q + 0.05 * speed)
        budget = ROLE_SLOT_BUDGET.get(role)
        fits, too_slow, failed = [], [], []
        for m, s in items:
            runs = s.get("runs") or 0
            dur = s.get("med_duration_s")
            if runs and (s.get("ok_rate") or 0) == 0:
                # модель измерена и не дала ни одного успеха — это замер отказа,
                # а не кандидат (таймаут в слоте = «не влезает»)
                failed.append(m)
                continue
            if budget and dur and dur > budget - FIT_HEADROOM_S:
                too_slow.append((m, s, dur))
            else:
                fits.append((m, s))
        # если ни одна модель не влезает — честно оставляем роль без схемы
        pool = fits or items
        note = None
        if not fits:
            if failed:
                note = ("все измеренные модели провалились ("
                        + ", ".join(failed) + ") — роль без схемы")
            else:
                note = ("ни одна измеренная модель не влезает в окно слота "
                        f"{budget} с — роль без схемы")
        scored = sorted(((val(m, s), m, s) for m, s in pool), reverse=True)
        # нет кандидата, влезающего в окно слота → схему для роли НЕ назначаем
        best = scored[0] if (scored and fits) else None
        rec[role] = {"best_model": best[1] if best else None,
                     "score": round(best[0], 3) if best else 0.0,
                     "fits_slot": bool(fits),
                     "too_slow": [{"model": m, "duration_s": d} for m, s, d in too_slow],
                     "note": note,
                     "candidates": [{"model": m, "score": round(v, 3), **s} for v, m, s in scored]}
    return rec


def main():
    args = sys.argv[1:]
    rows = load_rows()
    if "--pilot-only" in args:
        rows = [r for r in rows if r.get("pilot")]
    elif "--live-only" in args:
        rows = [r for r in rows if not r.get("pilot")]
    table = score(rows)
    rec = recommend(table)
    if "--json" in args:
        print(json.dumps({"rows": len(rows),
                          "table": {f"{r}|{m}": s for (r, m), s in table.items()},
                          "recommend": rec}, ensure_ascii=False, indent=2))
        return 0
    print(f"замеров: {len(rows)}  (state/role_runs.jsonl)")
    if not rows:
        print("замеров пока нет — прогоны ещё не измерились")
        return 0
    print(f"\n{'роль':22} {'модель':30} {'прог':>4} {'ok':>3} {'ok%':>5} {'сек':>6} "
          f"{'арт':>4} {'верд':>5} {'receipt':>7} {'отчёт':>6}")
    print("-" * 108)
    for (role, model), s in sorted(table.items(), key=lambda kv: (kv[0][0], -kv[1]["ok_rate"])):
        print(f"{role[:21]:22} {model.split('/')[-1][:29]:30} {s['runs']:>4} {s['ok']:>3} "
              f"{s['ok_rate']*100:>4.0f}% {str(s['med_duration_s'] or '-'):>6} "
              f"{s.get('med_artifacts_checked', 0):>4} {s.get('verdict_rate', 0):>5.2f} "
              f"{s.get('receipt_rate', 0):>7.2f} {s['med_report_bytes']:>6}")
    print("\n=== рекомендация (схема) ===")
    for role, r in sorted(rec.items()):
        cands = " | ".join(f"{c['model'].split('/')[-1]}:{c['score']}" for c in r["candidates"])
        bm = r.get('best_model')
        if not bm:
            print(f"{role[:28]:30} → — без схемы: {r.get('note') or 'нет подходящей модели'}")
        else:
            print(f"{role[:28]:30} → {bm:38} [{cands}]")
    if "--apply" in args:
        rot = json.loads(ROT.read_text(encoding="utf-8")) if ROT.is_file() else {}
        rot.setdefault("models", [])
        scheme = rot.get("scheme") or {}
        for role, r in rec.items():
            if r["best_model"] in rot.get("models", []):
                scheme[role] = r["best_model"]
        rot["scheme"] = scheme
        rot["experiment"] = not scheme
        ROT.write_text(json.dumps(rot, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nscheme записан в {ROT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
