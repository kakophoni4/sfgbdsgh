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
ENRICH_PAUSE=10
ENRICH_JITTER=8
ENRICH_LIMIT=40
```

Между запросами **~10–18 сек**. При капче → `ENRICH_PAUSE=20` и пауза на час.

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

## 7. Linux-скрипты

`deploy/setup_server.sh` и systemd — запасной вариант, для Windows не нужны.
