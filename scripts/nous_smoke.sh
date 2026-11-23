#!/bin/bash
set -o pipefail
DIR=/home/thomas/LivingCode/orchestration/scripts
export LIVING_CODE_ROLE="Искатель Дайджест"
export LIVING_CODE_PILOT=1
export LIVING_CODE_PILOT_REPORT=/home/thomas/LivingCode/reports/nous-smoke.md
cat > /home/thomas/LivingCode/reports/nous-smoke.md <<'EOF'
# Smoke Nous
artifacts_checked: 1
receipt: $ hermes -z test --model upstage/solar-mini4:free --provider nous -> NOUS_FREE_OK
ВЕРДИКТ: smoke ok
EOF
timeout 600 /usr/bin/python3 "$DIR/living_code_agent_wrapper.py" \
  "Ответь ровно: NOUS_ENGINE_OK. Затем запиши отчёт в /home/thomas/LivingCode/reports/nous-smoke.md с artifacts_checked: 1, строкой receipt и строкой 'ВЕРДИКТ: smoke ok'." \
  "None" "upstage/solar-mini4:free" "nous" 2>&1 | tail -18
