#!/bin/bash
# Отчёт по замерам ролей: кто какую модель играет и кто лучше (владелец, 22.11.2026).
set -o pipefail
DIR=/home/thomas/LivingCode/orchestration/scripts
OUT=/home/thomas/LivingCode/reports/role-score-$(date +%Y%m%d-%H%M).md
{
  echo "# Замеры ролей — $(date '+%d.%m.%Y %H:%M')"
  echo
  python3 "$DIR/role_score.py"
} > "$OUT" 2>&1
echo "$OUT"
