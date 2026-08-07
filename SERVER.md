# Деплой на Windows Server

Проект рассчитан на **Windows Server**, где открываются `egrul.nalog.ru` / `bo.nalog.ru`.  
Паузы между запросами большие — капчу ЕГРЮЛ не дёргаем.

## 0. Обновления через Git (рекомендуется)

На ПК (после правок):

```powershell
cd "C:\Users\FagotBlade\Downloads\фирмы"
git add -A
git commit -m "fix buh for gov.ru"
git push
```

На сервере:

```powershell
cd C:\firmy   # или путь к клону
git pull
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python smoke_check.py
```

Первый раз на сервере (вместо zip):

```powershell
cd C:\
git clone <URL_РЕПО> firmy
cd C:\firmy
.\deploy\setup_server.ps1
# .env и telegram_session.session — скопировать вручную один раз (в git не кладём)
```

Секреты в git **не** идут: `.env`, `*.session`.

## 1. Залить проект (если без git — zip)

На своём ПК уже есть архив `firmy_server_*.zip` (или собери снова):

```powershell
cd "C:\Users\FagotBlade\Downloads\фирмы"
powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
```

Скопируй zip на сервер (RDP / SMB / scp), распакуй, например в:

`C:\firmy`

## 2. Установка на сервере

Нужен **Python 3.11+** (галочка Add to PATH).

```powershell
cd C:\firmy
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\setup_server.ps1
```

Скрипт создаст `.venv`, поставит зависимости и прогонит `smoke_check.py`.

## 3. Telegram + первый прогон

```powershell
cd C:\firmy
.\.venv\Scripts\Activate.ps1

# если .session уже в архиве — логин не нужен
python telegram_login.py

python smoke_check.py
python run_parser.py --limit 300
python run_parser.py --enrich-only --enrich-limit 20
```

Excel: `C:\firmy\data\checklist_export.xlsx`

## 4. Паузы (не торопимся)

В `.env`:

```env
ENRICH_PAUSE=2.5
ENRICH_JITTER=1
ENRICH_LIMIT=40
```

Между запросами **~2.5–3.5 сек**. При капче → `ENRICH_PAUSE=10` / `20` и пауза на час.

## 5. По расписанию (Планировщик заданий)

От администратора:

```powershell
cd C:\firmy
.\deploy\register_task.ps1
```

- задание `FirmParser` каждые 6 часов + при старте ОС  
- логи: `C:\firmy\data\logs\`  
- ручной запуск: `Start-ScheduledTask -TaskName FirmParser`

## 6. Критерий «сервер подходит»

`python smoke_check.py` должен показать **OK** по ЕГРЮЛ и БФО.

| Хост | Зачем |
|------|--------|
| egrul.nalog.ru | статус, адрес, M/N |
| bo.nalog.ru | K / R / U |
| kad.arbitr.ru | P арбитраж |
| fssp.gov.ru | L долги/ИЛ (часто капча → ПРОВЕРИТЬ) |
| service.nalog.ru | дальше (дисквал) |

После обновления кода на сервере:

```powershell
python run_parser.py --rescore
python run_parser.py --enrich-kad --enrich-fssp --enrich-limit 20
python run_parser.py --enrich-fedresurs --enrich-limit 20
python run_parser.py --export-only
```

## Проверка всех источников

```powershell
python check_sources.py
```

Цепочки: P/L — Companium→Checko→КАД/ФССП; I — Companium→Checko→Saby→ЕГРЮЛ; O — Федресурс.

## Companium (P / L / I без КАД)

Обход заблокированного КАД/ФССП: карточка `https://companium.ru/id/{ОГРН}`.

```powershell
python -c "from parser.enrich.companium import fetch_companium; print(fetch_companium(ogrn='1057747184648'))"
python run_parser.py --enrich-companium --enrich-limit 40
# или всё ядро:
python run_parser.py --enrich-core --enrich-limit 85
```

Нужен ОГРН (после ЕГРЮЛ). При капче модуль сам пробует Playwright + клик по checkbox.

## КАД через Playwright

Голый HTTP → часто `blocked_451`. Playwright открывает сайт как Chrome.

```powershell
cd C:\firmy
.\.venv\Scripts\Activate.ps1
pip install playwright
python -m playwright install chromium

$env:KAD_BROWSER = "always"
python -c "from parser.enrich.kad import fetch_kad; print(fetch_kad('9728144340'))"
```

Если в ответе `error='pravocaptcha'` или `blocked_451*` — поиск КАД требует капчу PravoCaptcha / режет IP. Тогда колонка P остаётся **ПРОВЕРИТЬ** (вручную на kad.arbitr.ru).

```powershell
$env:KAD_BROWSER = "auto"
python run_parser.py --enrich-kad --enrich-limit 20
```

- `KAD_BROWSER=auto` — HTTP, при 451 → Playwright  
- `KAD_BROWSER=always` — сразу браузер  
- `KAD_HEADLESS=0` — показать окно (иногда легче проходит)

## 7. Linux-скрипты

`deploy/setup_server.sh` и systemd — запасной вариант, для Windows не нужны.
