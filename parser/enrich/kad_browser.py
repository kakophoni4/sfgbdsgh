"""
КАД через Playwright.

Установка:
  pip install playwright
  python -m playwright install chromium

Переменные:
  KAD_BROWSER=auto|always|never
  KAD_HEADLESS=1|0

Важно: SearchInstances часто требует PravoCaptcha / отдаёт 451.
Модуль не подставляет ложный «0 дел» — только JSON ответа или явная ошибка.
"""

from __future__ import annotations

import atexit
import os
from typing import Any

from .kad import KadReport

_pw = None
_browser = None
_context = None


def browser_mode() -> str:
    return (os.getenv("KAD_BROWSER") or "auto").strip().lower()


def headless() -> bool:
    return (os.getenv("KAD_HEADLESS") or "1").strip() not in {"0", "false", "no"}


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def _close() -> None:
    global _pw, _browser, _context
    for obj, meth in ((_context, "close"), (_browser, "close"), (_pw, "stop")):
        try:
            if obj is not None:
                getattr(obj, meth)()
        except Exception:
            pass
    _pw = _browser = _context = None


atexit.register(_close)


def _ensure_context():
    global _pw, _browser, _context
    if _context is not None:
        return _context

    from playwright.sync_api import sync_playwright

    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(
        headless=headless(),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    _context = _browser.new_context(
        locale="ru-RU",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1365, "height": 900},
    )
    _context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return _context


def _parse_search_payload(data: Any) -> tuple[int, list[str]]:
    items: list = []
    total = None
    if isinstance(data, dict):
        items = (
            data.get("Result")
            or data.get("items")
            or data.get("Items")
            or data.get("data")
            or []
        )
        total = data.get("TotalCount") or data.get("totalCount") or data.get("Count")
    elif isinstance(data, list):
        items = data
        total = len(items)
    if total is None:
        total = len(items) if isinstance(items, list) else 0
    samples: list[str] = []
    if isinstance(items, list):
        for it in items[:5]:
            if isinstance(it, dict):
                num = (
                    it.get("CaseNumber")
                    or it.get("caseNumber")
                    or it.get("Number")
                    or ""
                )
                if num:
                    samples.append(str(num))
    return int(total), samples


def fetch_kad_browser(inn: str) -> KadReport:
    inn = (inn or "").strip()
    if not inn.isdigit():
        return KadReport(inn=inn, error="bad_inn")
    if not playwright_available():
        return KadReport(inn=inn, error="playwright_not_installed")

    try:
        ctx = _ensure_context()
        page = ctx.new_page()
        try:
            captured: dict[str, Any] = {}

            def on_response(resp) -> None:
                try:
                    if "SearchInstances" not in resp.url:
                        return
                    if resp.request.method != "POST":
                        return
                    text = resp.text()
                    low = text.lower()
                    if resp.status == 451 or "заблокирован" in low:
                        captured["error"] = "blocked_451"
                        return
                    if resp.status >= 400:
                        captured["error"] = f"http_{resp.status}"
                        return
                    if text.lstrip()[:1] not in ("{", "["):
                        captured["error"] = "non_json"
                        return
                    captured["data"] = resp.json()
                    captured["url"] = resp.url
                except Exception as e:  # noqa: BLE001
                    captured["error"] = str(e)

            page.on("response", on_response)
            page.goto(
                "https://kad.arbitr.ru/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(1500)

            body0 = page.content().lower()
            if "заблокирован" in body0 and "доступ" in body0:
                return KadReport(inn=inn, error="blocked_451_browser", source="playwright")

            # 1) попытка fetch из контекста страницы
            result = page.evaluate(
                """async (payload) => {
                    try {
                      const r = await fetch('https://kad.arbitr.ru/Kad/SearchInstances', {
                        method: 'POST',
                        headers: {
                          'Content-Type': 'application/json;charset=UTF-8',
                          'Accept': 'application/json, text/plain, */*',
                          'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(payload),
                        credentials: 'include'
                      });
                      const text = await r.text();
                      if (r.status === 451 || text.toLowerCase().includes('заблокирован')) {
                        return {ok:false, error:'blocked_451', status:r.status};
                      }
                      if (!r.ok) return {ok:false, error:'http_'+r.status, status:r.status};
                      return {ok:true, data: JSON.parse(text)};
                    } catch (e) {
                      return {ok:false, error: String(e)};
                    }
                }""",
                {
                    "Page": 1,
                    "Count": 25,
                    "Courts": [],
                    "DateFrom": None,
                    "DateTo": None,
                    "Sides": [{"Name": inn, "Type": -1, "ExactMatch": False}],
                    "Judges": [],
                    "CaseNumbers": [],
                    "WithVKSInstances": False,
                },
            )
            if result.get("ok"):
                total, samples = _parse_search_payload(result.get("data"))
                return KadReport(
                    inn=inn,
                    cases_found=total,
                    sample=samples,
                    source="playwright:fetch",
                )

            # 2) UI: подсказка участников → выбор → Найти
            ta = page.locator("#sug-participants textarea").first
            ta.click()
            ta.fill("")
            ta.type(inn, delay=35)
            try:
                page.wait_for_selector("#b-suggest li a", timeout=12000)
                page.evaluate("document.querySelector('#b-suggest li a').click()")
                page.wait_for_timeout(700)
            except Exception:
                # без подсказки пробуем плюс
                try:
                    page.locator("#sug-participants i.b-icon.add").first.click(timeout=2000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            page.locator("button:has-text('Найти')").first.click(force=True)

            # ждём либо JSON, либо капчу/блок
            for _ in range(40):
                page.wait_for_timeout(500)
                if "data" in captured or captured.get("error"):
                    break
                # PravoCaptcha / капча
                has_captcha = page.evaluate(
                    """() => {
                      const t = (document.body.innerText || '').toLowerCase();
                      if (t.includes('капч')) return true;
                      return !!document.querySelector(
                        '[class*=captcha i], [id*=captcha i], iframe[src*=captcha i], #pravocaptcha'
                      );
                    }"""
                )
                if has_captcha and "data" not in captured:
                    # даём ещё пару секунд на авто-прохождение
                    page.wait_for_timeout(2000)
                    if "data" not in captured:
                        return KadReport(
                            inn=inn,
                            error="pravocaptcha",
                            source="playwright-ui",
                        )

            if "data" in captured:
                total, samples = _parse_search_payload(captured["data"])
                return KadReport(
                    inn=inn,
                    cases_found=total,
                    sample=samples,
                    source=f"playwright-ui:{captured.get('url')}",
                )

            err = (
                captured.get("error")
                or result.get("error")
                or "no_search_response"
            )
            return KadReport(inn=inn, error=f"browser_{err}", source="playwright-ui")
        finally:
            page.close()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
            return KadReport(
                inn=inn,
                error="playwright_browser_missing",
                source="playwright",
            )
        return KadReport(inn=inn, error=f"browser_{msg}", source="playwright")


def reset_browser() -> None:
    _close()
