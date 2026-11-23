#!/usr/bin/env python3
"""Покрывающий аудит через Gemini: код режется на чанки, каждый — отдельный чат.
Причина: веб-Gemini читает прикреплённый .txt только частично (~19 файлов),
и не умеет ходить на GitHub. Чанки по ~110 КБ читаются целиком.
"""
import json, os, subprocess, sys, time, pathlib, urllib.request

SRC = pathlib.Path('/home/thomas/LivingCode/orchestration')
OUT = pathlib.Path('/home/thomas/.hermes/cache/scratch/audit')
BUNDLE = OUT / 'livingcode-bundle.txt'
CHUNKS = OUT / 'chunks'
CHUNKS.mkdir(parents=True, exist_ok=True)
env = dict(os.environ); env['PATH'] = os.path.expanduser('~/build/npm-global/bin') + ':' + env['PATH']
S = ['agent-browser', '--session', 'audit']
PROMPT_FILE = SRC / 'prompts/cloud_audit_prompt.md'


def run(args, t=120):
    return subprocess.run(S + args, capture_output=True, text=True, env=env, timeout=t)


def js(expr, t=60):
    r = run(['eval', expr], t); v = r.stdout.strip()
    try:
        return json.loads(v) if v.startswith('"') else v
    except Exception:
        return v


def build_chunks(max_chars=115000):
    """Режем бандл по маркерам '===== FILE:'."""
    text = BUNDLE.read_text(encoding='utf-8')
    parts, cur = [], []
    for block in text.split('\n\n===== FILE: ')[1:]:
        b = '\n\n===== FILE: ' + block
        if sum(len(x) for x in cur) + len(b) > max_chars and cur:
            parts.append(cur); cur = []
        cur.append(b)
    if cur:
        parts.append(cur)
    files = []
    for i, group in enumerate(parts, 1):
        p = CHUNKS / f'chunk_{i:02d}.txt'
        p.write_text(''.join(group), encoding='utf-8')
        names = [g.split(' ', 1)[0].split(' (')[0] for g in group]
        files.append({'n': i, 'path': str(p), 'bytes': p.stat().st_size,
                      'count': len(group), 'names': names})
    return files


CHROME = "/home/thomas/.local/bin/google-chrome"
PROFILE = "/home/thomas/.hermes/cache/scratch/audit/chrome-profile"
PORT = 9334
COOKIE_DB = "/home/thomas/.config/Hermes/Partitions/hermes-preview/Cookies"


def _cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_browser() -> bool:
    """Поднять headless-Chrome с разрешёнными 3P-куками и подключить сессию.

    Без этого скрипт молча опрашивает мёртвый браузер и получает len=0.
    """
    if not _cdp_alive():
        subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"], capture_output=True)
        os.makedirs(PROFILE, exist_ok=True)
        subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={PROFILE}", "--no-sandbox", "--disable-dev-shm-usage",
             "--no-first-run", "--no-default-browser-check",
             "--disable-features=ThirdPartyStoragePartitioning,TrackingProtection3pcd,IsolateOrigins,site-per-process",
             "--test-third-party-cookie-phaseout=0", "--disable-blink-features=AutomationControlled",
             "--lang=ru-RU", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(2)
            if _cdp_alive():
                break
        print("[browser] chrome поднят", flush=True)
    run(["connect", str(PORT)], 90)
    return _cdp_alive()


def audit_chunk(meta):
    ensure_browser()
    n = meta['n']
    run(['open', 'https://gemini.google.com/app'], 120); time.sleep(9)
    # 1) гасим куки-баннер Google: на свежем профиле он перехватывает весь UI
    consent = js("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^(reject all|accept all|отклонить все|принять все)$/i.test((x.innerText||'').trim()));if(b){b.click();return 'clicked '+(b.innerText||'').trim()}return 'no-dialog'})()")
    print(f"[chunk {n}] куки-баннер: {consent}", flush=True)
    if 'clicked' in str(consent):
        time.sleep(4)
    # 2) если Google-сессии нет — поднимаем её из партишена (иначе композер есть, а отправки нет)
    if 'sign in' in str(js("(document.body.innerText||'').slice(0,600)")).lower() or 'войти' in str(js("(document.body.innerText||'').slice(0,600)")).lower():
        print(f"[chunk {n}] нет Google-сессии — поднимаю куки из партишена", flush=True)
        run(["close", "--all"], 60)
        ensure_browser()
        sys.path.insert(0, str(SRC / "scripts"))
        from cloud_audit_session import lift_cookies, set_cookies
        cj = str(OUT / "gemini_cookies.json")
        lift_cookies(COOKIE_DB, [".google.com", "accounts.google.com"], cj)
        set_cookies("audit", cj)
        run(['open', 'https://gemini.google.com/app'], 120); time.sleep(10)
    # прикрепление файла: input[type=file] появляется только после клика по кнопке
    try:
        nfiles = int(str(js("document.querySelectorAll('input[type=file]').length")).strip() or 0)
    except ValueError:
        nfiles = 0
    if not nfiles:
        print(f"[chunk {n}] ищу кнопку прикрепления...", flush=True)
        js("(()=>{const b=[...document.querySelectorAll('button,[role=button]')].find(x=>/attach|upload|file|прикреп|загруз/i.test((x.getAttribute('aria-label')||x.innerText||'')));if(b){b.click();return 'clicked'}return 'no-btn'})()")
        time.sleep(4)
        try:
            nfiles = int(str(js("document.querySelectorAll('input[type=file]').length")).strip() or 0)
        except ValueError:
            nfiles = 0
    print(f"[chunk {n}] input[type=file]: {nfiles}", flush=True)
    composer = str(js("!!document.querySelector('div.ql-editor[contenteditable=\"true\"]')")).strip().lower() == "true"
    if not composer:
        print(f"[chunk {n}] композера нет — поднимаю Google-сессию из партишена", flush=True)
        run(["close", "--all"], 60)
        ensure_browser()
        sys.path.insert(0, str(SRC / "scripts"))
        from cloud_audit_session import lift_cookies, set_cookies
        cj = str(OUT / "gemini_cookies.json")
        lift_cookies(COOKIE_DB, [".google.com", "accounts.google.com"], cj)
        set_cookies("audit", cj)
        run(['open', 'https://gemini.google.com/app'], 120); time.sleep(10)
        print(f"[chunk {n}] композер после подъёма: "
              f"{js(chr(33)+chr(33)+'document.querySelector(\'div.ql-editor[contenteditable=\\\"true\\\"]\')')}", flush=True)
    listed = '\n'.join('  - ' + x for x in meta['names'][:40])
    prompt = (
        f"Это часть {n} аудита протокола «Живой Код». Прикреплён текстовый бандл — "
        f"{meta['count']} файлов, {meta['bytes']//1024} КБ. Между файлами маркеры '===== FILE: путь ====='.\n"
        f"Файлы этой части:\n{listed}\n\n"
        "Аудитируй ИМЕННО эти файлы (читай их содержимое в приложении). "
        "Номера строк проверяй по приложенному тексту — не выдумывай.\n\n"
        + PROMPT_FILE.read_text(encoding='utf-8')
        + f"\n\nПОСЛЕДНИЙ БЛОК ОТВЕТА (это часть {n}, её конец):\n"
          "## Итог части\n"
          f"5–7 самых важных дефектов этой части с severity и ссылкой на проверенную строку, "
          f"и один абзац: что в этой части чинить первым."
    )
    chunk_bytes = pathlib.Path(meta['path']).stat().st_size
    use_upload = bool(nfiles) and chunk_bytes <= 50000
    if not use_upload and nfiles:
        print(f"[chunk {n}] файл {chunk_bytes//1024} КБ — загрузка в Gemini зависает, шлю текстом по частям",
              flush=True)
    if use_upload:
        run(['upload', 'input[type=file]', meta['path']], 240); time.sleep(10)
    if use_upload:
        run(['fill', 'div.ql-editor[contenteditable="true"]', prompt], 300); time.sleep(3)
    else:
        # файл не прикрепился — шлём содержимое несколькими сообщениями (контекст Gemini их держит)
        parts = [prompt]
        body = pathlib.Path(meta['path']).read_text(encoding='utf-8')
        pieces, cur = [], ""
        for block in body.split("\n\n===== FILE: ")[1:]:
            b = "\n\n===== FILE: " + block
            if len(cur) + len(b) > 22000:
                pieces.append(cur); cur = ""
            cur += b
        if cur:
            pieces.append(cur)
        for i, piece in enumerate(pieces, 1):
            head = (f"[chunk {n}, часть {i}/{len(pieces)}] ниже содержимое файлов чанка. "
                    f"Не анализируй пока, просто прими текст.\n\n" if i > 1 else
                    f"Аудит протокола «Живой Код». Ниже содержимое файлов чанка {n} "
                    f"({len(pieces)} сообщ.). В последнем сообщении будут выводы.\n\n")
            msg = head + piece
            run(['fill', 'div.ql-editor[contenteditable="true"]', msg], 300); time.sleep(2)
            run(['press', 'Enter'], 60); time.sleep(6)
            print(f"[chunk {n}] отправлено сообщение {i}/{len(pieces)} ({len(msg)} симв.)", flush=True)
        run(['fill', 'div.ql-editor[contenteditable="true"]', prompt], 300); time.sleep(3)
    run(['press', 'Enter'], 60); time.sleep(15)
    url = js('location.href')
    last, stable, deadline = '', 0, time.time() + 600
    resp = ''
    while time.time() < deadline:
        body = js("(document.body.innerText||'')") or ''
        gen = bool(js("!!document.querySelector('button[aria-label*=\"стоп\" i],button[aria-label*=\"stop\" i]')"))
        # ВАЖНО: на странице бывает несколько model-response, первые — пустые.
        # Берём последний НЕПУСТОЙ, иначе вечный len=0.
        resp = js("(()=>{const a=[...document.querySelectorAll('model-response')].map(e=>e.innerText||'').filter(t=>t.trim().length>0);return a.length?a[a.length-1]:''})()") or ''
        print(f"[chunk {n}] gen={gen} len={len(resp)}", flush=True)
        if resp and resp == last:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = resp
        time.sleep(15)
        # ВАЖНО: на странице бывает несколько model-response, первые — пустые.
        # Берём последний НЕПУСТОЙ, иначе вечный len=0.
        resp = js("(()=>{const a=[...document.querySelectorAll('model-response')].map(e=>e.innerText||'').filter(t=>t.trim().length>0);return a.length?a[a.length-1]:''})()") or ''
    f = OUT / f'gemini_chunk_{n:02d}.md'
    f.write_text(f'# Gemini audit — часть {n}/{meta["count"]} файлов\n# chat: {url}\n\n' + resp, encoding='utf-8')
    print(f'[chunk {n}] сохранено {len(resp)} символов -> {f}', flush=True)
    return len(resp)


if __name__ == '__main__':
    chunks = build_chunks()
    print('чанков:', len(chunks), [(c['n'], c['count'], c['bytes'] // 1024) for c in chunks], flush=True)
    for c in chunks:
        if (OUT / f'gemini_chunk_{c["n"]:02d}.md').exists():
            print(f"[chunk {c['n']}] уже сохранён — пропускаю", flush=True)
            continue
        try:
            audit_chunk(c)
        except Exception as e:
            print(f"[chunk {c['n']}] ОШИБКА: {type(e).__name__}: {e}", flush=True)
    print('ГОТОВО', flush=True)
