#!/usr/bin/env python3
"""Облачный аудит через веб-UI: загрузка zip-архива + промпт + сохранение ответа.

Работает в окружении browser_exec (helpers: js, fill_input, click_at_xy, cdp).
Требует авторизованной сессии в браузере — вход делает владелец один раз,
дальше скрипт повторяемый.

Использование (в browser_exec / browser-harness):
    exec(open('/home/thomas/LivingCode/orchestration/scripts/cloud_audit.py').read())
    audit(provider='gemini', zip_path='/path/archive.zip',
          prompt_file='/path/prompt.md', out='/path/gemini_audit.md')
"""
# pyright: reportUndefinedVariable=false
# js/cdp/fill_input/goto_url — хелперы, которые подставляет browser_exec/browser-harness
import base64, json, os, time

PROVIDERS = {
    "gemini": ("https://gemini.google.com/app", "Загрузить файл"),
    "claude": ("https://claude.ai/new", "Attach"),
    "grok":  ("https://grok.com/", "Upload"),
}


def _wait_ready(seconds=30):
    for _ in range(seconds * 2):
        try:
            if js("document.readyState") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _find_file_input():
    return js("""(() => {
        const i = document.querySelector('input[type=file]');
        return i ? (i.id || i.name || 'file-input') : '';
    })()""")


def attach_zip(zip_path, timeout=60):
    """Вешает архив на file-input через CDP DOM.setFileInputFiles."""
    path = os.path.abspath(zip_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    node = None
    for _ in range(int(timeout * 2)):
        try:
            doc = cdp("DOM.getDocument")
            q = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"],
                    selector="input[type=file]")
            if q.get("nodeId"):
                node = q["nodeId"]
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not node:
        raise RuntimeError("file-input не найден — открой диалог загрузки вручную")
    cdp("DOM.setFileInputFiles", nodeId=node, files=[path])
    return path


def submit_prompt(text, timeout=180):
    box = js("""(() => {
        const c = [...document.querySelectorAll('textarea, [contenteditable="true"]')]
          .filter(e => e.offsetParent !== null);
        return c.length ? (c[0].id || c[0].getAttribute('aria-label') || 'prompt-box') : '';
    })()""")
    if not box:
        raise RuntimeError("поле ввода не найдено")
    try:
        fill_input(f"#{box}" if box.startswith("prompt-box") else box, text)
    except Exception:
        js("""(() => {
            const c = [...document.querySelectorAll('textarea, [contenteditable="true"]')]
              .filter(e => e.offsetParent !== null);
            if (c[0]) { c[0].focus(); }
        })()""")
        fill_input("textarea, [contenteditable='true']", text)
    time.sleep(1)
    js("""(() => {
        const b = [...document.querySelectorAll('button')].find(x =>
            /send|отправ|submit|arrow_up/i.test((x.getAttribute('aria-label')||x.innerText||'')));
        if (b) { b.click(); return true; }
        return false;
    })()""")
    time.sleep(3)
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        body = js("(document.body.innerText||'')") or ""
        if body != last and len(body) > len(text) + 400:
            last = body
            time.sleep(8)
            continue
        if body != last:
            last = body
            break
    return last


def audit(provider, zip_path, prompt_file, out, wait=240):
    url, _ = PROVIDERS[provider]
    goto_url(url)
    _wait_ready()
    time.sleep(4)
    attach_zip(zip_path)
    time.sleep(6)
    prompt = open(prompt_file, encoding="utf-8").read()
    text = submit_prompt(prompt)
    deadline = time.time() + wait
    while time.time() < deadline:
        body = js("(document.body.innerText||'')") or ""
        if len(body) > len(text) + 200:
            time.sleep(10)
            continue
        break
    body = js("(document.body.innerText||'')") or ""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Cloud audit — {provider}\n# zip: {zip_path}\n\n{body}\n")
    return out, len(body)
