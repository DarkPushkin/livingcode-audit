#!/bin/bash
# Владыка Кода — обёртка движка Живого Кода (переведена из агентного режима 02.10.2026).
# Агентные задачи шли мимо движка: получали HTTP 429 на выжженной модели и падали,
# поэтому модель не ротировалась. Теперь роль идёт через living_code_agent_wrapper.py,
# который сам обходит исчерпанные квоты (см. FREE_POOL в движке).
set -o pipefail
export LIVING_CODE_ROLE="Владыка Кода"
DIR=/home/thomas/LivingCode/orchestration/scripts
export LIVING_CODE_CRON_BUDGET=600  # Ψ-FIX 19.10.2026: слот 15 минут, дальше Продюсер
PROMPT=$(cat "$DIR/wrappers/prompts/lord_of_code.txt")

NEXT_JOB_ID="90f76ccbbdab"  # LV-producer — конец цепочки аудитор→владыка→продюсер

# 23.11.2026: решение о заморозке принимает ДЕТЕРМИНИРОВАННЫЙ скрипт, а не LLM.
# LLM-обёртка ниже пишет объяснение и не может «протащить» проект: гейт (тесты,
# план, дефекты) и заморозка делаются здесь, вердикт — в state/verdicts/<project>.json,
# а конвейер (lv_promote_check.sh, ежечасно) выпускает по машинному вердикту.
PROJECT=$(/usr/bin/python3 - <<'PYEOF'
import re, pathlib
j = pathlib.Path('/home/thomas/LivingCode/JOURNAL.md')
try:
    txt = j.read_text(encoding='utf-8', errors='replace')
except OSError:
    txt = ''
m = re.findall(r'\[TRIGGER_LORD\]\s*([\w-]+)', txt)
print(m[-1] if m else '')
PYEOF
)
if [ -n "$PROJECT" ]; then
  echo "[Lord] проект из журнала: $PROJECT — гейт и заморозка"
  timeout 900 /usr/bin/python3 "$DIR/lord_of_code.py" --project "$PROJECT" --no-send || true
fi

/usr/bin/python3 "$DIR/living_code_agent_wrapper.py" "$PROMPT" "$NEXT_JOB_ID" "ROTATE" "nvidia"
