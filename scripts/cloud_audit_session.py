#!/usr/bin/env python3
"""Полный цикл облачного аудита через веб-UI: подъём сессии + загрузка + промпт + ответ.

Проверенный путь (23.11.2026):
  1) Chrome поднимается САМ с разрешёнными сторонними куками — иначе Google даёт
     «CookieMismatch» (Electron-превью работает иначе, чем headless-Chrome).
  2) Куки берём из живой сессии Chromium (Hermes preview-партишен) и ставим поштучно:
     `cookies set --curl <file>` из JSON НЕ работает (тихо кладёт одну мусорную куку).
  3) Файл грузится прямо в input[type=file] — Gemini zip принимает, но видит только
     метаданные; содержимое отдаём текстовым бандлом (.txt).

Использование:
    python3 cloud_audit_session.py --provider gemini \
        --cookies-db /home/thomas/.config/Hermes/Partitions/hermes-preview/Cookies \
        --domains .google.com accounts.google.com \
        --bundle /home/thomas/.hermes/cache/scratch/audit/livingcode-bundle.txt \
        --prompt  /home/thomas/LivingCode/orchestration/prompts/cloud_audit_prompt.md \
        --out     /home/thomas/.hermes/cache/scratch/audit/gemini_audit.md
"""
import argparse, json, os, sqlite3, subprocess, sys, time

CHROME = "/home/thomas/.local/bin/google-chrome"
AB = os.path.expanduser("~/build/npm-global/bin")


def sh(args, timeout=90, check=False):
    env = dict(os.environ)
    env["PATH"] = AB + ":" + env["PATH"]
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout, check=check)


def ab(session, *args, timeout=90):
    return sh(["agent-browser", "--session", session, *args], timeout=timeout)


def js(session, expr, timeout=60):
    r = ab(session, "eval", expr, timeout=timeout)
    v = r.stdout.strip()
    try:
        return json.loads(v) if v.startswith('"') else v
    except Exception:
        return v


def lift_cookies(db, domains, out_json):
    """Chromium Cookies -> JSON (значения в Electron-партишене открытым текстом)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "select host_key,name,value,path,expires_utc,is_secure,is_httponly from cookies").fetchall()
    def exp_us(v):
        return int((v - 11644473600000000) / 1000000) if v else -1
    keep = []
    for h, n, v, p, e, s, htt in rows:
        if any(d in h for d in domains):
            keep.append({"name": n, "value": v, "domain": h, "path": p or "/",
                         "expires": exp_us(e), "secure": bool(s), "httpOnly": bool(htt),
                         "sameSite": "Lax"})
    json.dump(keep, open(out_json, "w"), ensure_ascii=False)
    return len(keep)


def set_cookies(session, cookies_json):
    cookies = json.load(open(cookies_json))
    ok = 0
    for c in cookies:
        cmd = ["agent-browser", "--session", session, "cookies", "set", c["name"], c["value"],
               "--domain", c["domain"], "--path", c.get("path", "/")]
        if c.get("secure"):
            cmd.append("--secure")
        if c.get("httpOnly"):
            cmd.append("--http-only")
        if c.get("expires", -1) > 0:
            cmd += ["--expires", str(int(c["expires"]))]
        try:
            if sh(cmd, timeout=30).returncode == 0:
                ok += 1
        except subprocess.TimeoutExpired:
            pass
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="gemini")
    ap.add_argument("--cookies-db", required=True)
    ap.add_argument("--domains", nargs="+", required=True)
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=9340)
    ap.add_argument("--session", default="audit")
    ap.add_argument("--profile", default="/home/thomas/.hermes/cache/scratch/audit/chrome-profile")
    ap.add_argument("--wait", type=int, default=540)
    ap.add_argument("--skip-upload", action="store_true")
    args = ap.parse_args()

    urls = {"gemini": "https://gemini.google.com/app",
            "claude": "https://claude.ai/new",
            "grok": "https://grok.com/"}

    # 1) Chrome с разрешёнными 3P-куками
    sh(["agent-browser", "close", "--all"], timeout=60)
    subprocess.run(["pkill", "-f", f"remote-debugging-port={args.port}"], capture_output=True)
    os.makedirs(args.profile, exist_ok=True)
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={args.port}", "--remote-allow-origins=*",
         f"--user-data-dir={args.profile}", "--no-sandbox", "--disable-dev-shm-usage",
         "--no-first-run", "--no-default-browser-check",
         "--disable-features=ThirdPartyStoragePartitioning,TrackingProtection3pcd,IsolateOrigins,site-per-process",
         "--test-third-party-cookie-phaseout=0", "--disable-blink-features=AutomationControlled",
         "--lang=ru-RU", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    ab(args.session, "connect", str(args.port), timeout=60)

    # 2) куки
    cj = args.out + ".cookies.json"
    n = lift_cookies(args.cookies_db, args.domains, cj)
    print(f"поднято кук: {n}")
    ok = set_cookies(args.session, cj)
    print(f"установлено кук: {ok}")

    # 3) страница + загрузка
    ab(args.session, "open", urls[args.provider], timeout=90)
    time.sleep(8)
    if not args.skip_upload:
        ab(args.session, "upload", "input[type=file]", args.bundle, timeout=120)
        for _ in range(20):
            time.sleep(3)
            if os.path.basename(args.bundle)[:18] in (js(args.session, "(document.body.innerText||'')") or ""):
                break
        print("файл прикреплён")

    # 4) промпт
    prompt = ("К аудиту прикреплён текстовый бандл: там содержимое файлов проекта, "
              "между файлами маркеры '===== FILE: путь ====='. Читай ИХ, а не только имена.\n\n"
              + open(args.prompt, encoding="utf-8").read())
    ab(args.session, "fill", "div.ql-editor[contenteditable=\"true\"]", prompt, timeout=120)
    time.sleep(2)
    ab(args.session, "press", "Enter", timeout=60)
    time.sleep(10)
    print("чат:", js(args.session, "location.href"))

    # 5) ждём ответ
    SEL = ("(() => {const c=['model-response','.model-response-text','message-content',"
           "'[data-test-id=\"model-response\"]'];for(const s of c){const e=document.querySelector(s);"
           "if(e&&e.innerText.trim().length>200)return e.innerText;}"
           "const a=document.querySelectorAll('div[role=\"paragraph\"],p');let b='';"
           "a.forEach(x=>{if(x.innerText&&x.innerText.length>b.length)b=x.innerText});"
           "return b||(document.body.innerText||'')})()")
    last, stable, deadline = "", 0, time.time() + args.wait
    while time.time() < deadline:
        body = js(args.session, "(document.body.innerText||'')") or ""
        gen = bool(js(args.session, "!!document.querySelector('button[aria-label*=\"стоп\" i],"
                                   "button[aria-label*=\"stop\" i]')"))
        resp = js(args.session, SEL) or ""
        print(f"[{int(time.time()%1000):3}] gen={gen} len={len(resp)}", flush=True)
        if resp and resp == last:
            stable += 1
            if stable >= 3 and not gen:
                break
        else:
            stable = 0
        last = resp
        time.sleep(12)
    resp = js(args.session, SEL) or ""
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(
        f"# Cloud audit — {args.provider}\n# bundle: {args.bundle}\n\n{resp}\n")
    print("СОХРАНЕНО:", args.out, len(resp), "символов")
    chrome.terminate()


if __name__ == "__main__":
    main()
