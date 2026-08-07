# Парсер продажи ООО (Telegram → чек-лист)

Сбор объявлений из профильных чатов (Telethon), обогащение ЕГРЮЛ/БФО, Excel-чек-лист.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python telegram_login.py
python smoke_check.py
python run_parser.py --limit 300
python run_parser.py --enrich-only --enrich-limit 20
```

Деплой на Windows Server: см. [SERVER.md](SERVER.md). План: [PLAN.md](PLAN.md).

Секреты (`.env`, `*.session`) в репозиторий не коммитятся.
