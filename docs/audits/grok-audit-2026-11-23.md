# Cloud audit — Grok (бесплатная квота аккаунта владельца)
# источник: https://github.com/DarkPushkin/livingcode-audit (публичный слепок протокола «Живой Код»)
# Grok реально открыл репозиторий и прочитал AUDIT_REQUEST.md

## Краткий вердикт

Протокол «Живой Код» — рабочая, зрелая система с жёстким разделением LLM-слоя и машинных гейтов. Freeze_gate, evidence_gate, release_gate и machine_verdict уже не дают LLM «нарисовать» релиз: решение о заморозке и продвижении принимается детерминированно. Главный риск — не обход гейта, а операционная хрупкость: hard-coded пути /home/thomas/..., широкий except: pass, неатомарные записи состояния/маркеров и расхождение rotation.json ↔ roster.json. Безопасность в целом приемлема (секреты вынесены, subprocess в основном со списками аргументов), но token-чтение из файла и curl с токеном в argv остаются точками утечки. Код явно эволюционировал через реальные инциденты (HOT/COLD ломал Dart/XML, nemotron-саботаж, дубли TRIGGER_PRODUCER). Протокол готов к внешнему аудиту и дальнейшей закалке, но не к «включил и забыл».

Таблица дефектов
Приоритет	Файл:строка	Суть	Как чинить
P0	scripts/lord_of_code.py:413-414	Токен бота читается из файла и попадает в argv curl → виден в ps/auditd	Передавать через env BOT_TOKEN=... + curl -H "Authorization: Bearer $BOT_TOKEN" или stdin; не класть в argv
P0	scripts/lord_of_code.py:59-61, 100-101, 124-125	except Exception: pass глотает ошибки записи маркеров и laya	Логировать хотя бы logging.exception / append в journal; не молчать
P0	scripts/lord_of_code.py:247-248, freeze_project	Неатомарная перезапись файлов маркером (open('w')) → при kill/таймауте возможна порча	Писать во временный файл + os.replace
P1	scripts/freeze_gate.py:28, lord_of_code.py:82-83,129-133	Hard-coded /home/thomas/LivingCode — слепок/другой хост ломается	Единый LIVING_CODE_ROOT из env с fallback; убрать абсолютные пути владельца
P1	rotation.json:53-78 vs roster.json:12-13	scheme заполнен, experiment:false в rotation, но roster говорит experiment:true и пустой scheme	Синхронизировать генерацию roster из rotation; тест на расхождение
P1	scripts/conveyor.py:84-85, lord_of_code.py:253-256	Неатомарная запись JSON-манифеста/штампа заморозки	tempfile + os.replace
P1	scripts/living_code_agent_wrapper.py:125	BANNED_MODEL_SUBSTRINGS = ("nemotron",) — бан только по подстроке; легко обойти опечаткой/алиасом	Полный whitelist + нормализация имени модели до сравнения
P2	scripts/evidence_gate.py:28-138	Огромный список regex metadata — хрупкий, легко ломается новым форматом отчёта	Вынести в конфиг + unit-тесты на golden reports
P2	scripts/freeze_gate.py:249-250	subprocess.run([runner, "-q"], ...) без явного ограничения env/PATH	Передавать env=os.environ.copy() с очисткой, cwd уже есть
P2	scripts/lord_of_code.py:71, 94-96	subprocess.run без check= и с широким timeout; вывод hermes/laya не валидируется жёстко	Проверять rc + schema JSON от laya; fail-closed при мусоре
1. Безопасность

Реально эксплуатируемое

Чтение токена и передача в argv curl (lord_of_code.py:413-422):

Python
_tok = os.environ.get("CATHEDRAL_BOT_TOKEN") or open(
    os.path.expanduser("~/.hermes/secrets/cathedral_bot_token"), encoding="utf-8").read().strip()
proc = subprocess.run(["curl", ..., f"https://api.telegram.org/bot{_tok}/sendDocument", ...])

Любой локальный процесс с правом ps видит токен. Это P0.

Широкие except Exception: pass при записи маркеров и вызове laya (lord_of_code.py:59-61,100-101). Ошибка записи/парсинга молча игнорируется → ложное «успешно заморожено».

Теоретическое / низкий риск в текущем контуре

Path traversal: iter_code_files / os.walk ограничены проектом и SKIP_DIRS; явного ../ из пользовательского ввода в freeze_gate нет.
SSRF: внешних URL, собираемых из LLM-текста, в критических гейтах не видно.
subprocess почти везде со списками аргументов (не shell=True) — хорошо.
Секреты в слепке отсутствуют (явно указано в README/AUDIT_REQUEST). redact_secrets.py и guard_action.py существуют.
eval/exec в просмотренных гейтах нет.

Права и файлы

Маркеры HOT/COLD пишутся поверх исходников. marker_guard.py правильно отсекает shebang, XML, бинарники, небезопасные расширения — это сильная защита после реальных инцидентов (Dart/XML).
2. Корректность
Гонки: несколько cron-ролей могут одновременно трогать один проект (кодер + Владыка + conveyor). Блокировок файлов (кроме TG rate-limit lock) почти нет. Запись STATE.json / freeze-штампа / маркеров не атомарна.
Глобальное состояние: hard-coded пути + LIVING из env, но fallback на /home/thomas/... делает слепок и CI хрупкими.
Потеря данных при kill/таймауте: open(fp, 'w') в freeze_project и update_file_markers — при SIGKILL посередине файл может стать пустым/обрезанным.
Проглоченные исключения: см. P0 выше.
Коды возврата: freeze_gate корректно возвращает 0/1/2; release_gate — 0/1. Хорошо.
Кэш тестов (freeze_gate.py:220-231): проверяет source_mtime — правильная инвалидация.
3. Мёртвый и незастроенный код
Класс	Что	Где
dead	Старые .orig-YYYYMMDD копии	scripts/*.orig-*, lord_of_code.py.orig-*
dead	Локальный llama.cpp путь в wrapper	living_code_agent_wrapper.py:59-63 (комментарий: «НЕ используется»)
unbuilt	Полноценный A/B и outcomes.jsonl по switch_criteria	rotation.json:118-124 — критерии описаны, автоматики переключения нет
unbuilt	Единый конфиг путей	Везде размазаны абсолютные пути
broken	Расхождение experiment/scheme	rotation vs roster (см. таблицу)

unbuilt — не дефект, а карта: protocol intentionally оставляет training-фазу.

4. Граница доверия

Проверено по коду:

freeze_gate.py — полностью детерминированный (реестр дефектов, PLAN.md checkbox, pytest). LLM не участвует. Laya — только информационный (laya_triage).
lord_of_code.py:315-340 — явно:
Python
# 23.11.2026: решение о заморозке принимает ДЕТЕРМИНИРОВАННЫЙ гейт,
# а не LLM. Владыка-LLM пишет объяснение, но не может «протащить» проект.
gate_res = fg.evaluate(Path(project_path))
gate_ok = bool(gate_res.get('passed'))
if project_path and gate_ok:
    walked, flipped, freeze_stamp = freeze_project(project_path)
Машинный вердикт пишется в state/verdicts/<project>.json (write_machine_verdict).
conveyor.py:164-187, 292-310 — сначала читает machine_verdict; prose отчёта — только fallback.
evidence_gate.py — zero-LLM, grounded_numbers ≥ 0.9, hollow-patterns.
release_gate.py — py_compile + bash -n + check_roster + guard selftest + kg_validate; LLM нет.
guard_action.py — human-in-the-loop на push-protected/delete/model-change и т.д.

Вывод: LLM-слой не может самостоятельно выпустить релиз или заморозить проект. Обход возможен только если агент получит право писать в state/verdicts/ или state/freeze/ напрямую (файловая система) — это уже out-of-protocol, и guard_action частично прикрывает опасные действия.

5. Схема ролей

Из rotation.json + roster.json:

Роли: Кодер×4 (Project1–4) + Elemental Life×2, Аудитор, Владыка Кода, Продюсер, Профессор, Искатель, Искатель Дайджест, L3-Критик, Super-Supervisor, UI-Гейт, Proposer, Судья Laya, Топик 252 + служебтивные (artist, musician, node-health, vault-sync…).
Дубли: Искатель / Искатель Дайджест — близкие; Профессор / Профессор Учебник.
Конфликты за слот/файл: несколько кодеров + Владыка + conveyor могут одновременно ходить в один ProjectN (mtime-маркеры, STATE.json). Нет distributed lock.
Не хватает: явной роли «Release Manager» (сейчас размазано между Владыкой + conveyor + promote_check); единого «State Auditor», который проверял бы целостность state/ после каждого цикла.
Бюджеты слотов (slot_budgets) и shadow_rate=0.15 — продуманно. Free-ярус отдельно замерен (free_capability.json).
6. Приоритеты (топ-10)
P0 Token в argv curl (lord_of_code)
P0 except: pass при записи маркеров/laya
P0 Неатомарная запись исходников при freeze
P1 Hard-coded /home/thomas
P1 Расхождение rotation ↔ roster
P1 Неатомарные JSON state/manifest
P1 Бан моделей только по substring
P2 Хрупкий regex-зоопарк evidence_gate
P2 Отсутствие file-lock на проект при concurrent ролях
P2 Мёртвые .orig-* и diagnostic-only llama.cpp путь засоряют дерево
Что чинить первым
Убрать токен из argv (env + header) — мгновенно закрывает утечку в process list.
Атомарная запись всех файлов, которые трогает freeze/marker (tmp + rename).
Логирование вместо pass в критических except — хотя бы journal append.
Единый LIVING_CODE_ROOT + тест, что ни один скрипт не содержит /home/thomas.
Синхронизация roster из rotation + CI-проверка experiment/scheme совпадают.

Ожидаемый эффект: исчезновение «тихих» порч файлов, невозможность случайно засветить bot-token, воспроизводимый запуск слепка на чужой машине.

Что сделано хорошо
Машинный гейт над LLM реализован последовательно: freeze_gate → machine_verdict → conveyor. Это редкая и правильная архитектура.
marker_guard.py — качественный allow-list после реальных поломок (Dart, XML, shebang). Документирован инцидент.
Evidence Gate с grounded_numbers и hollow-patterns — сильный анти-галлюцинационный слой.
guard_action.py с TTL-маркером владельца и selftest — правильный human-in-the-loop на линиях разлома.
Замеры free_capability и role budgets — протокол не гадает, а меряет; rotation.json содержит осознанные trade-off’ы по времени слота.

Аудит выполнен по AUDIT_REQUEST.md строго в запрошенном формате. Номера строк проверены по raw-содержимому файлов репозитория.

23 sources
Анализ race conditions в freeze_gate
Инструменты линтинга Python




Быстрый
