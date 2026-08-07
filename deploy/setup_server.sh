#!/usr/bin/env bash
# Установка на Linux-сервер (Ubuntu/Debian).
# Запуск из корня проекта: bash deploy/setup_server.sh

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> Каталог: $ROOT"

if ! command -v python3 >/dev/null; then
  echo "Нужен python3. Установи: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

mkdir -p data
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Создан .env — проверь TELEGRAM_PHONE и паузы."
fi

echo ""
echo "==> Smoke-check сайтов ФНС"
python smoke_check.py || true

echo ""
echo "Дальше:"
echo "  source .venv/bin/activate"
echo "  python telegram_login.py          # один раз (или скопируй .session с ПК)"
echo "  python run_parser.py --limit 200"
echo "  python run_parser.py --enrich-only --enrich-limit 20"
echo "  # cron / systemd: см. deploy/firm-parser.service"
