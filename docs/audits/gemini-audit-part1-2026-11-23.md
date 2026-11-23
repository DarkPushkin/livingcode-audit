# Cloud audit — Gemini (sportclass@gmail.com, free tier)
# bundle: livingcode-bundle.txt (61 файла протокола «Живой Код»)

Ответ Gemini

Примечание по объёму бандла: в прикреплённом фрагменте livingcode-bundle.txt приведены 19 файлов (от scripts/_secrets.py до обрезанного на scripts/prof_graph_update.py). Все ссылки на строки и функции ниже даны по содержимому этих файлов.   
livingcode-bundle.txt
Ещё 1

Топ-10 дефектов по severity
severity	файл:строка	суть	как чинить
P0	scripts/cycle_close.py:168-174 и scripts/lord_of_code.py:310-316	Секрет CATHEDRAL_BOT_TOKEN читается и передаётся аргументом f"[https://api.telegram.org/bot](https://api.telegram.org/bot){_tok}/..." в subprocess.run(["curl", ...]) — токен попадает в командную строку процесса (/proc/<pid>/cmdline, ps) и в сообщения об ошибках при парсинге ответа	Использовать urllib.request / requests / httpx в Python вместо curl с токеном в URL; маскировать токен в логах/ошибках
P0	scripts/conveyor.py:422-424 и scripts/conveyor.py:482-484	Копирование и удаление проектов в очереди (shutil.move(str(slot), str(target)) и shutil.rmtree(queued, ignore_errors=True)) выполняются без проверки path traversal / нормализации путей и без атомарного журнала операций (ignore_errors=True скрывает ошибки удаления очереди)	Проверять resolve().is_relative_to(ROOT) для slot, target, queued; убрать ignore_errors=True и логировать ошибки удаления
P0	scripts/living_code_agent_wrapper.py:114-149	ALLOWED_PAIRS и HISTORICALLY_DEAD одновременно содержат minimaxai/minimax-m3.1-flash (nvidia) в ALLOWED_PAIRS (строка 121) и в HISTORICALLY_DEAD (строка 166), но assert not (ALLOWED_PAIRS & HISTORICALLY_DEAD) (строка 171) почему-то не падает — либо список устарел/рассинхронизирован, плюс BANNED_MODEL_SUBSTRINGS имеет противоречивый комментарий о снятии бана над жёстким баном (строки 151-160)	Синхронизировать ALLOWED_PAIRS, HISTORICALLY_DEAD и BANNED_MODEL_SUBSTRINGS с единым источником истины (roster.json / конфиг), убрать противоречивые блоки
P1	scripts/cycle_start_cron.py:34-38 и scripts/l3_critic.py:85-92 и scripts/l3_critic.py:121-128	Вызов внешних команд через subprocess.run(..., shell=True) с подстановкой строк (`f'df -h /tmp	tail -n1
P1	scripts/living_code_agent_wrapper.py:482-537	В run_hermes_agent используется глобальный межпроцессный fcntl.flock на /home/thomas/LivingCode/orchestration/.locks/model-call.lock, но при обрыве процесса (SIGKILL от systemd/cron) или конкурентном доступе к state/role_runs.jsonl / journal.md отсутствует атомарность записи и защита от гонок	Использовать flock при записи в общие файлы (journal.md, role_runs.jsonl, CONVEYOR.json) и проверять stale/мертвые блокировки
P1	scripts/freeze_gate.py:258-277 и scripts/freeze_gate.py:310-335	Кэш результатов тестов (read_cache / write_cache) проверяет только newest_source_mtime(project) и не учитывает изменение тестов, конфигов, зависимостей или окружения (GATE_TEST_BUDGET), а при force_tests=False молча запускает run_tests и не обновляет кэш	Включать в ключ кэша хеш файлов проекта/тестов/конфигов и явно разделять политику использования кэша
P1	scripts/evidence_gate.py:16-143	Множество опечаток и сломанных регулярных выражений в METADATA_NUMBER_PATTERNS и HOLLOW_PATTERNS (например, \\w вместо \w, `	$/
P2	scripts/musician_entry.py:29 и scripts/node_health.py:21,50,62,74	UNSLOTH_API имеет плейсхолдер [http://100.](http://100.)x.y.z:8000/v1 (строка 29), а в node_health.py голые except: глушат ошибки nvidia-smi, rocm-smi, ollama и requests.get	Заменить плейсхолдер на валидный URL/конфиг, заменить голые except: на конкретные исключения с логированием
P2	scripts/conveyor.py:345-351 и scripts/guard_action.py:92-97	В record_outcome (строка 349) и _audit (строка 95) ошибки записи в outcomes.jsonl и journal.md глушатся (print / pass), что ведёт к потере телеметрии и аудита	Логировать в stderr и возвращать/фиксировать статус ошибки записи
P2	scripts/lord_of_code.py:173-179 и scripts/media_contract.py:30-42	В lord_of_code.py update_file_markers имеет except Exception: pass (строка 178), а в media_contract.py run() принимает список команд, но в get_producer_contract (строка 185) передаёт ["find", ".", "-name", "*.apk", "-type", "f"] без валидации proj_dir	Логировать ошибки чтения/записи файлов и проверять существование proj_dir до запуска subprocess.run
1. Безопасность
Реально эксплуатируемые / высокорисковые векторы

Утечка секрета в аргументы процесса (cmdline) и логи:

scripts/cycle_close.py:168-174 (do_release) и scripts/lord_of_code.py:310-316 (main): токен _tok (CATHEDRAL_BOT_TOKEN / ~/.hermes/secrets/cathedral_bot_token) подставляется прямо в URL f"[https://api.telegram.org/bot](https://api.telegram.org/bot){_tok}/sendMessage" / .../sendDocument в subprocess.run(["curl", ...]). Аргументы командной строки дочерних процессов видны локальным процессам в /proc/<pid>/cmdline и ps, а при ошибке парсинга ответа логируются строки proc.stdout[:200] (scripts/cycle_close.py:179, scripts/lord_of_code.py:322).   
livingcode-bundle.txt
Ещё 1

Command injection через shell=True:

scripts/cycle_start_cron.py:34-38 (sh): вызывает subprocess.run(cmd, shell=True, ...). В health() строка 106 туда передаётся конкатенация с awk.   
livingcode-bundle.txt
Ещё 1

scripts/l3_critic.py:85-92 (_run_tests) и scripts/l3_critic.py:121-128 (_run_cli_smoke): запускают test_cmd и check.get('command') из словаря criteria через shell=True. Если criteria приходит из внешнего/LLM-источника без жёсткой санитизации, это прямое выполнение произвольных shell-команд.   
livingcode-bundle.txt
Ещё 1

Небезопасные операции с файлами и путями (path traversal / разрушительное удаление):

scripts/conveyor.py:422-424 (finalize): shutil.move(str(slot), str(target)) и shutil.rmtree(queued, ignore_errors=True) при project из внешнего источника (например, .queue_source, STATE.json или журнала) не проверяют выход за пределы ROOT / QUEUE_DIR.   
livingcode-bundle.txt

scripts/intake_pick.py:127-146 (copy_project): src = SOURCE / name, dst = DEST / name — name берётся из sys.argv[2] без проверки на .. или разделители пути.   
livingcode-bundle.txt

Теоретические / условные векторы

SSRF / невалидный endpoint в сетевых вызовах:

scripts/musician_entry.py:29 (UNSLOTH_API = "[http://100.](http://100.)x.y.z:8000/v1"): захардкожен невалидный IP-шаблон по умолчанию; при переопределении через env запросы уходят в unsloth_musicgen / unsloth_tts / unsloth_stt (строки 54-112) без проверки целевого хоста.   
livingcode-bundle.txt

scripts/l3_critic.py:157-162 (_check_ui_render): делает urllib.request.urlopen на check.get('url') из criteria.   
livingcode-bundle.txt

scripts/prof_gh_check.py:14-18: ходит на [https://api.github.com/repos/](https://api.github.com/repos/) по фиксированному списку REPOS без аутентификации (быстро упрётся в rate limit GitHub API).   
livingcode-bundle.txt

Права на файлы и секреты:

scripts/_secrets.py:10-24 (_read, load_cathedral_token): читает ~/.hermes/secrets/cathedral_bot_token и кладёт в os.environ["CATHEDRAL_BOT_TOKEN"], но сам модуль не проверяет права доступа (0600) к файлу секрета.   
livingcode-bundle.txt

scripts/guard_action.py:30-66 (_approved, check, approve): маркер одобрения state/owner_approval.json и переменная LIVING_CODE_OWNER_APPROVED=1 дают обход гейта любому процессу в том же пользователе ОС, который может записать файл или выставить env.   
livingcode-bundle.txt

2. Корректность

Гонки и конкурентный доступ:

scripts/living_code_agent_wrapper.py:482-537 (run_hermes_agent): использует fcntl.flock на model-call.lock, но record_role_run (строки 834-891) пишет в state/role_runs.jsonl обычным open(..., "a") без flock, а _journal_append (строки 565-573) дописывает в agents/journal.md без блокировки — при параллельных слотах строки могут перемешиваться.   
livingcode-bundle.txt

scripts/conveyor.py:410-455 (finalize) и scripts/conveyor.py:50-58 (load_manifest / save_manifest): чтение/изменение/запись CONVEYOR.json не защищены lock-файлом.   
livingcode-bundle.txt

scripts/laya_service.py:55-57 и scripts/laya_service.py:124-135 (_idle_watchdog, load_router, unload_router): STATE защищён LOCK в load_router/unload_router и handle_call, но в _idle_watchdog (строка 127) чтение STATE["router"] is not None и idle = time.time() - STATE["last_use"] происходит до захвата LOCK.   
livingcode-bundle.txt

Потеря данных при kill / таймауте:

scripts/living_code_agent_wrapper.py:390-427 (_run_group_timeout): убивает группу процессов через os.killpg(..., signal.SIGKILL) при TimeoutExpired. Любой дочерний процесс, пишущий файл неатомарно, может оставить усечённый/битый файл (например, STATE.json в generate_state.py:86-94, где запись идёт напрямую через write_text, а не через .tmp + rename, в отличие от artist_entry.py:29-31).   
livingcode-bundle.txt
Ещё 1

scripts/compact_state_db.py:56-60 (main): запускает hermes sessions optimize-storage --yes без проверки, действительно ли остановлен gateway (только печатает предупреждение).   
livingcode-bundle.txt

Глушение ошибок (except: pass / проглатывание исключений):

scripts/node_health.py:21, 35, 50, 62, 74: голые except: в get_gpu_info, get_ollama_models, get_lemonade_models.   
livingcode-bundle.txt

scripts/lord_of_code.py:56 (update_file_markers), scripts/lord_of_code.py:137 (laya_run), scripts/lord_of_code.py:163 (build_hot_summary): except Exception: pass / continue.   
livingcode-bundle.txt

scripts/guard_action.py:95 (_audit), scripts/laya_bridge.py:203 (_fallback_marker), scripts/laya_service.py:118 (unload_router): except ...: pass.   
livingcode-bundle.txt

Неверные / спорные коды возврата:

scripts/laya_service.py:265-270 (Handler.do_POST): при ошибке handle_call (out.get("ok") ложно) всё равно возвращает HTTP 200 (self._send(200 if out.get("ok") else 200, out)).   
livingcode-bundle.txt

scripts/freeze_gate.py:292-293 (run_tests): при rc == 5 (тестов не собрано) возвращает "ok": True, что при пустом/сломанном наборе тестов разрешает заморозку, если остальные гейты зелёные.   
livingcode-bundle.txt

scripts/living_code_agent_wrapper.py:725-728 (main): при rc == 0 у run_hermes_agent, но невалидном usage_file (строки 522-526) всё равно считает слот успешным (return subprocess.CompletedProcess(cmd, 0, ...)), даже если Hermes упал/не записал чек.   
livingcode-bundle.txt

3. Мёртвый и незастроенный код
Мёртвый / неподключённый код (dead)

scripts/living_code_agent_wrapper.py:194-239 (call_llama_cpp_direct): в docstring и комментариях (строки 67-69, 639-641) явно указано, что локальный llama.cpp в движке отключён и не используется.   
livingcode-bundle.txt

scripts/living_code_agent_wrapper.py:813-819 (_report_html): функция-заглушка возвращает "", помечена как удалённая (04.11.2026), вызовов нет.   
livingcode-bundle.txt

scripts/meta_evolver.py:224-225 (apply_improvements): цикл for analysis in []: pass — явная пустая заглушка.   
livingcode-bundle.txt

scripts/media_contract.py:285: переменная role_filter = sys.argv[2] if len(sys.argv) > 2 else None считывается в main(), но нигде не используется.   
livingcode-bundle.txt

scripts/conveyor.py:553 и scripts/conveyor.py:604: slot_meta собирается в cmd_scan и cmd_run, но далее в этих функциях не используется.   
livingcode-bundle.txt

Недостроенное / задуманное (unbuilt)

scripts/l3_critic.py:26, 200: поле recommendations: List[str] в CriticVerdict всегда создаётся пустым (self.recommendations = [] в run_verification, строка 61), логика формирования рекомендаций не реализована.   
livingcode-bundle.txt

scripts/media_contract.py:130-163 (get_musician_contract) и scripts/musician_entry.py: контракты/очереди медиа и аудио описаны для artist, dj-musician, producer, но автоматическая склейка и прикрепление медиа-вложений в Telegram в deliver_media_report (scripts/media_contract.py:249-275) сводится к отправке одного .md-файла.   
livingcode-bundle.txt

scripts/meta_evolver.py:216-243 (apply_improvements): автоматические правки сводятся только к regex-замене строк C:/... на Linux-пути и созданию ветки meta-evolver-layer3.   
livingcode-bundle.txt

Регрессии и рассогласования (broken)

scripts/living_code_agent_wrapper.py:114-171: minimaxai/minimax-m3.1-flash (nvidia) присутствует одновременно в ALLOWED_PAIRS (строка 121) и в HISTORICALLY_DEAD (строка 166), при этом assert not (ALLOWED_PAIRS & HISTORICALLY_DEAD) (строка 171) не срабатывает только если множества не пересекаются — но они пересекаются (("minimaxai/minimax-m3.1-flash", "nvidia") есть в обоих), что указывает на рассинхрон/ошибку логики или данных.   
livingcode-bundle.txt

scripts/musician_entry.py:29: UNSLOTH_API по умолчанию указывает на несуществующий адрес [http://100.](http://100.)x.y.z:8000/v1.   
livingcode-bundle.txt

scripts/evidence_gate.py:21-143: экранирование в строках паттернов (\\w вместо \w, неэкранированные | в METADATA_NUMBER_PATTERNS и HOLLOW_PATTERNS, например строки 34, 35, 36, 48, 128, 129, 134, 136) ломает часть регулярных выражений.   
livingcode-bundle.txt

scripts/conveyor.py:258 (slot_ready): вызывает machine_verdict(project, also=slot.name) с also=slot.name, а в finalize (строка 417) вызывает lord_verdict(project) без also=slot_name.   
livingcode-bundle.txt

4. Протокол-специфика

Может ли модель обойти гейт?

В scripts/lord_of_code.py:239-256 (main) решение о заморозке (gate_ok) формально берётся из freeze_gate.evaluate(Path(project_path)), а не из текста LLM.   
livingcode-bundle.txt

Однако сам freeze_gate.py читает артефакты внутри репозитория/проекта: open_registry_defects (scripts/freeze_gate.py:124-184) читает defect_registry.json / DEFECTS.md и считает закрытыми записи по CLOSED_STATES / колонке статуса; open_plan_items (scripts/freeze_gate.py:187-203) пропускает строки с DEFERRED_MARKERS ("вне скоупа", "отложено", "не в этом цикле" и др.). Агент-кодер с доступом к файлам проекта может пометить пункты в PLAN.md как «отложено» или закрыть/изменить записи в реестре дефектов.   
livingcode-bundle.txt

В scripts/cycle_close.py:72-97 (find_last_markers) и scripts/lord_of_code.py:194-213 (parse_last_trigger) разбор состояния идёт по текстовым маркерам в agents/journal.md ([TRIGGER_PRODUCER], [COLD_RELEASE], [TRIGGER_LORD]) — при записи в общий журнал возможны ложные срабатывания или подмена контекста.   
livingcode-bundle.txt

Может ли модель «нарисовать» вердикт?

В scripts/lord_of_code.py:287-305 (main + write_machine_verdict) машинный вердикт (ГОРЯЧИЙ / ВЕРНУТЬ) пишется в state/verdicts/<project>.json на основе gate_ok, а в .md-отчёт пишется строка ВЕРДИКТ: ....   
livingcode-bundle.txt

В scripts/conveyor.py:165-186 (machine_verdict) приоритет отдан state/verdicts/<project>.json, а при его отсутствии используется прозаический парсер lord_verdict (строки 215-237) по reports/lord*.md. Если машинный вердикт отсутствует, текст отчёта влияет на решение конвейера.   
livingcode-bundle.txt

В scripts/evidence_gate.py (validate, строки 260-322) проверка artifacts_checked ищет паттерн artifacts_checked\s*[:=]\s*(\d+) в тексте отчёта (строка 290) и receipt_regex по совпадению числа в найденных строках/блоках (has_receipt_for_number, строки 205-213) — формальное присутствие числа в кодовом блоке удовлетворяет проверке числа без семантической проверки истинности.   
livingcode-bundle.txt

Где граница доверия между LLM-слоем и машинным слоем?

Граница проходит между выводом агента (stdout / .md-отчёты / записи в journal.md) и детерминированными скриптами (freeze_gate.py, cycle_close.py, lord_of_code.py, conveyor.py, evidence_gate.py).   
livingcode-bundle.txt

Эта граница неоднородна: в lord_of_code.py заморозка и запись state/verdicts/*.json привязаны к freeze_gate.evaluate(...) (строки 239-256, 297-305), но journal.md используется как триггерный канал (parse_last_trigger, find_last_markers, _deliverables_changed в living_code_agent_wrapper.py:617-648) и при этом помечен в journal_lint.py:3-4 как недоверенный вход.   
livingcode-bundle.txt

5. Схема ролей

Какие роли дублируют друг друга (по коду и контрактам):

Запуск следующих задач / оркестрация переходов: living_code_agent_wrapper.py (trigger_next_cron_job, строки 651-691), lord_of_code.py (trigger_next_cron_job, строки 105-110 и main, строки 324-327) и cycle_start_cron.py (promotion_check, строки 117-143).   
livingcode-bundle.txt

Закрытие/промоушен/релиз: cycle_close.py (do_release, git_cycle_push, cold_gates_ok, строки 153-372) и conveyor.py (finalize, slot_ready, write_final_docs, строки 258-460), а также lord_of_code.py (freeze_project, строки 216-256).   
livingcode-bundle.txt

Оценка качества/стабильности: laya_bridge.py (verdict, triage, ui_gate), logprobs_decider.py (decide, score), l3_critic.py (L3Critic) и evidence_gate.py (EvidenceGate).   
livingcode-bundle.txt

Каких ролей не хватает (по следам в коде):

В коде фигурируют роли/сущности: кодеры (coder-project1- в living_code_agent_wrapper.py:577), аудитор (auditor в freeze_gate.py:42, living_code_agent_wrapper.py:577), профессор (Профессор в check_roster.py:86, 159, prof_gh_check.py, prof_graph_update.py), Владыка кода (lord_of_code.py, lord-of-code- в living_code_agent_wrapper.py:577), продюсер (cycle_close.py, media_contract.py), Вербовщик (intake_pick.py:3-6), художник (artist_entry.py, media_contract.py), музыкант (musician_entry.py, media_contract.py), мета-эволюционер (meta_evolver.py).   
livingcode-bundle.txt

Явного детерминированного арбитра/разрешителя конфликтов по общим ресурсам (journal.md, CONVEYOR.json, слоты Project1..4) и роли релиза/отката с проверкой целостности state/ в прикреплённом коде нет.   
livingcode-bundle.txt

Где роли конфликтуют за один и тот же файл:

agents/journal.md: пишут living_code_agent_wrapper.py (_journal_append, строки 565-573), guard_action.py (_audit, строки 88-96), laya_bridge.py (_fallback_marker, строки 195-204), cycle_start_cron.py (journal_ping, строки 157-164), media_contract.py (main, строки 304-311), meta_evolver.py (main, строки 332-336), conveyor.py (finalize, строки 446-451); читают и парсят cycle_close.py, lord_of_code.py, journal_lint.py, living_code_agent_wrapper.py.   
livingcode-bundle.txt

Файлы внутри Project1..Project4 / Projects/<project>: lord_of_code.py (freeze_project, update_hot_cold_markers) меняет первую строку файлов (# HOT / # COLD) и STATE.json, generate_state.py перезаписывает STATE.json, conveyor.py перемещает/удаляет каталоги слотов и очереди, cycle_close.py делает git add -A / git commit / git push и копирует в Releases/<project>.   
livingcode-bundle.txt

reports/*.md: общая директория REPORTS_DIR для всех ролей (living_code_agent_wrapper.py:576-578 вынужден фильтровать отчёты по префиксу имени файла и mtime и переносить лишние в reports/_superseded/, строки 722-755).   
livingcode-bundle.txt
