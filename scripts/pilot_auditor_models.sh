#!/bin/bash
# Пилот: одинаковая задача аудита на всех 4 моделях NVIDIA (владелец, 22.11.2026).
set -o pipefail
DIR=/home/thomas/LivingCode/orchestration/scripts
PROMPT=$(cat "$DIR/wrappers/prompts/pilot_auditor.txt")
unset LIVING_CODE_TELEGRAM
export LIVING_CODE_ROLE="Аудитор"
export LIVING_CODE_PILOT=1
export LIVING_CODE_PILOT_REPORT=/home/thomas/LivingCode/reports/pilot-auditor.md
export LIVING_CODE_CRON_BUDGET=2700
for M in ${PILOT_MODELS:-poolside/laguna-xs-2.1 mistralai/mistral-large-4-1t-a52b stepfun-ai/step-5-preview minimaxai/minimax-m3.1-flash}; do
  echo "===== ПИЛОТ: $M ====="
  START=$(date +%s)
  timeout 2700 /usr/bin/python3 "$DIR/living_code_agent_wrapper.py" "$PROMPT" "None" "$M" "nvidia" 2>&1 | tail -25
  echo "----- $M: $(( $(date +%s) - START )) с"
  cp /home/thomas/LivingCode/reports/pilot-auditor.md "/home/thomas/.hermes/cache/scratch/pilot-auditor-${M##*/}.md" 2>/dev/null
done
echo "ПИЛОТ ГОТОВ"
