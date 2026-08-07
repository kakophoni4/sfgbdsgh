from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# --- regex ---

# Только «ООО "БРЕНД"» / ООО БРЕНД — не «ООО с историей 2017»
RE_OOO_QUOTED = re.compile(
    r"(?:ООО|OОО)\s*[«\"“']\s*([А-ЯЁA-Z0-9][^«\"”»'\n]{1,70}?)\s*[»\"”']",
    re.I,
)
# ООО Бренд / ООО БК Гарант (слово с заглавной; «с историей» отсечёт валидатор)
RE_OOO_BARE = re.compile(
    r"(?:ООО|OОО)\s+"
    r"((?:[А-ЯЁA-Z0-9][А-ЯЁA-Za-zа-яё0-9\-]*)"
    r"(?:\s+[А-ЯЁA-Z0-9][А-ЯЁA-Za-zа-яё0-9\-]*){0,4})"
)
# старый широкий паттерн — только для детекта «есть ООО», не для имени
RE_OOO = re.compile(r"\b(?:ООО|OОО)\b", re.I)
# рекламный хвост вместо названия
RE_FAKE_FIRM_NAME = re.compile(
    r"(?i)(?:"
    r"с\s+историей|без\s+истори|историей\s+\d{4}|нулевк|нулёвк|готов\w*|под\s+смен|"
    r"инн\s+по\s+запросу|по\s+запросу|без\s+сч[её]т|с\s+сч[её]т|"
    r"с\s+оборот|без\s+оборот|больш\w*\s+оборот|под\s+ключ|в\s+любой\s+регион|"
    r"профи\b|экспресс|срочно|недорого|дешев|"
    r"^\d{4}\s*г|история\s+\d{4}"
    r")"
)
RE_INN_LABELED = re.compile(r"ИНН\s*[:\-]?\s*(\d{10})\b", re.I)
RE_OGRN = re.compile(r"ОГРН\s*[:\-]?\s*(\d{13})\b", re.I)
RE_INN_ON_REQUEST = re.compile(r"ИНН\s+по\s+запросу", re.I)
RE_DATE = re.compile(
    r"(?:регистрац\w*\s*)?"
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[а-яё]+\s+\d{4}|\b(?:19|20)\d{2}\s*г\.?)",
    re.I,
)
RE_YEAR_ONLY = re.compile(r"\b((?:19|20)\d{2})\s*г(?:од)?\.?\b", re.I)
RE_SNO = re.compile(r"\b(ОСНО|ОСН\b|УСН(?:\s*\d+\s*%?)?|АУСН|ЕСХН)\b", re.I)
RE_OKVED = re.compile(r"\b(\d{2}\.\d{2}(?:\.\d{1,2})?)\b")
RE_USERNAME = re.compile(r"@([A-Za-z0-9_]{4,})")
RE_ZSK_GREEN = re.compile(
    r"зелён|зелен|🟢|уровне? риска:\s*🟢|в черных списках[^\n]{0,40}не найдено",
    re.I,
)
RE_ZSK_YELLOW = re.compile(r"жёлт|желт|🟡", re.I)
RE_ZSK_RED = re.compile(r"красн|🔴|недопустим", re.I)
RE_NO_ACCOUNT = re.compile(r"без\s+счет|без\s+счёт", re.I)
RE_BLOCKS = re.compile(r"блок|приостанов", re.I)
RE_DEBTS_NO = re.compile(r"без\s+долг|долги[^\n]{0,20}отсутств", re.I)
RE_ZERO = re.compile(r"без\s+оборот|нулев", re.I)
RE_PRIMARY = re.compile(r"первичк|база\s*1\s*с|1с\s+переда", re.I)
RE_LIQUID = re.compile(r"ликвидац|исключен", re.I)

RE_PRICE = re.compile(
    r"(?:стоимость|цена)\s*[:\-]?\s*"
    r"(\d[\d\s.,]*)\s*"
    r"(тыс\.?\s*(?:руб|р\.?)?|т\.?\s*р\.?|млн\.?|миллион\w*|руб(?:лей)?|р\.?|₽)?",
    re.I,
)
RE_PRICE_ALT = re.compile(
    r"\b([\d\s]{1,3}(?:[.,]\d{3})+|\d+[.,]\d+)\s*"
    r"(тыс\.?\s*(?:руб|р)?|т\.?\s*р\.?|млн\.?)\b",
    re.I,
)

RE_REVENUE_LINE = re.compile(
    r"(20\d{2})\s*[-–—:г.]+\s*([\d\s.,]+)\s*(млн|тыс|т\.?р\.?|руб|р\.?)?",
    re.I,
)

# Разделители мульти-лотов
RE_SPLIT = re.compile(
    r"(?=^[\s]*[✅✔️❇️💎🟢🔥]*\s*ООО\b)|"
    r"(?=^-{6,})|"
    r"(?=^🔥{3,})",
    re.M | re.I,
)

RE_SPAM = re.compile(
    r"каталог\s+готовых|более\s+\d+\s+актуальн|прайс\s+с\s+инн\s+по\s+запросу|"
    r"подбор\s+компании\s+по\s+заданным|consalt-b\.ru|"
    r"продолжить\s+сотрудничество|@confessionalis_bot",
    re.I,
)
# спрос / «нужна компания» — не лот на продажу
RE_BUYER = re.compile(
    r"(?i)\b(нужна|нужен|нужно|ищу|куплю|требуется|подберите|помогите\s+найти)\b|"
    r"добрый\s+день|здравствуйте"
)
RE_SALE = re.compile(
    r"(?i)\b(прода[еёю]|продажа|стоимость|цена)\b|\bИНН\s*[:\-]?\s*\d{10}"
)
RE_BAD_NAME_LINE = re.compile(
    r"(?i)^(добрый|здравствуйте|всем|подскажите|нужна|нужен|нужно|ищу|куплю|"
    r"требуется|помогите|дата\s+\d|усн|осно)\b"
)

FOOTER_CUT = re.compile(
    r"(✍\s*Для связи|Большая часть компаний|📱\s*Удобный каталог|"
    r"КАТАЛОГ КОМПАНИЙ|💼\s*В НАЛИЧИИ)",
    re.I,
)


@dataclass
class Listing:
    name: str = ""
    inn: str = ""
    ogrn: str = ""
    inn_on_request: bool = False
    reg_date_raw: str = ""
    reg_year: int | None = None
    price_rub: int | None = None
    price_raw: str = ""
    sno: str = ""
    okved: str = ""
    zsk_claim: str = ""  # green/yellow/red/unknown
    has_account_claim: str = ""  # yes/no/unknown
    has_blocks_claim: bool = False
    no_debts_claim: bool = False
    zero_turnover_claim: bool = False
    primary_1c_claim: bool = False
    revenues: dict[str, int] = field(default_factory=dict)
    seller_username: str = ""
    seller_from_msg: str = ""
    chat_id: int = 0
    message_id: int = 0
    block_index: int = 0
    link: str = ""
    msg_date: str = ""
    raw_text: str = ""
    is_listing: bool = True
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def message_link(chat_id: int, message_id: int) -> str:
    raw = str(abs(chat_id))
    if raw.startswith("100"):
        raw = raw[3:]
    return f"https://t.me/c/{raw}/{message_id}"


def _parse_money(num: str, unit: str | None) -> int | None:
    if not num:
        return None
    s = num.strip().replace(" ", "").replace("\xa0", "")
    # 1.8 / 80.000 / 300,000 / 1,8
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        # 80.000 or 1.800.000 → thousands separators with dots
        s = s.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
        if s.count(".") > 1:
            s = s.replace(".", "")
    try:
        val = float(s)
    except ValueError:
        return None

    u = (unit or "").lower().replace(" ", "").replace("₽", "")
    if "млн" in u or "миллион" in u:
        return int(val * 1_000_000)
    # тыс / т.р / тр / т.р.
    if "тыс" in u or re.fullmatch(r"т\.?р\.?", u) or u in {"тр", "т.р", "т.р."}:
        return int(val * 1_000)
    if val < 1000:
        return None
    return int(val)


def extract_price(text: str) -> tuple[int | None, str]:
    m = RE_PRICE.search(text)
    if m:
        price = _parse_money(m.group(1), m.group(2))
        if price:
            return price, m.group(0).strip()
    # fallback: "90 т.р." без слова цена ближе к концу
    tail = text[-400:] if len(text) > 400 else text
    for m in RE_PRICE_ALT.finditer(tail):
        price = _parse_money(m.group(1), m.group(2))
        if price and price >= 5_000:
            return price, m.group(0).strip()
    return None, ""


def extract_revenues(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for year, num, unit in RE_REVENUE_LINE.findall(text):
        # не путать с ценой "2024 г. - 80 000"
        money = _parse_money(num, unit or "руб")
        if money is None:
            continue
        # выручка обычно с unit млн/тыс или крупные суммы
        if unit or money >= 50_000:
            out[year] = money
    return out


def extract_zsk(text: str) -> str:
    if RE_ZSK_RED.search(text) and not RE_ZSK_GREEN.search(text):
        return "red"
    if RE_ZSK_GREEN.search(text):
        return "green"
    if RE_ZSK_YELLOW.search(text):
        return "yellow"
    return "unknown"


def extract_sno(text: str) -> str:
    m = RE_SNO.search(text)
    if not m:
        return ""
    s = m.group(1).upper().replace(" ", "")
    if s.startswith("ОСН") and not s.startswith("ОСНО"):
        return "ОСНО"
    if s.startswith("УСН"):
        # сохранить ставку если есть
        m2 = re.search(r"УСН\s*(\d+\s*%?)", text, re.I)
        return f"УСН {m2.group(1).replace(' ', '')}" if m2 else "УСН"
    return s


def extract_reg(text: str) -> tuple[str, int | None]:
    # явная дата дд.мм.гггг
    m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]((?:19|20)\d{2}))\b", text)
    if m:
        year = int(m.group(2))
        return m.group(1), year
    m = re.search(
        r"(?:регистрац\w*|от)\s*(\d{1,2}\s+[а-яё]+\s+((?:19|20)\d{2}))",
        text,
        re.I,
    )
    if m:
        return m.group(1), int(m.group(2))
    m = re.search(
        r"(?:январ|феврал|март|апрел|май|мая|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*\s+((?:19|20)\d{2})",
        text,
        re.I,
    )
    if m:
        return m.group(0), int(m.group(1))
    # "с историей 2017г" / "2012 год"
    m = RE_YEAR_ONLY.search(text)
    if m:
        year = int(m.group(1))
        if 1990 <= year <= 2030:
            return m.group(0), year
    return "", None


def _clean_firm_core(raw: str) -> str:
    name = (raw or "").strip(" .,—-«»\"'“”")
    name = re.split(r"\s*,\s*", name, maxsplit=1)[0].strip()
    name = re.split(r"\s+[–—-]\s+", name, maxsplit=1)[0].strip()
    # отрезать хвост «ИНН …» / «с историей…» если влез в кавычки
    name = re.split(r"(?i)\s+ИНН\b", name, maxsplit=1)[0].strip()
    name = re.split(r"(?i)\s+с\s+историей\b", name, maxsplit=1)[0].strip()
    name = name.strip(" «»\"'“”")
    return name


def is_plausible_firm_name(name: str) -> bool:
    """Отсекает рекламу вида «ООО с историей 2017» / «ООО Профи ИНН по запросу»."""
    if not name or len(name) < 2:
        return False
    core = name
    core = re.sub(r"(?i)^ООО\s*", "", core).strip(" «»\"'“”")
    if len(core) < 2 or len(core) > 60:
        return False
    if RE_FAKE_FIRM_NAME.search(core):
        return False
    if RE_BAD_NAME_LINE.search(core):
        return False
    # сплошь цифры / год
    if re.fullmatch(r"[\d\s./гГ]+", core):
        return False
    # должно быть хоть немного «буквенного» бренда
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", core)
    if len(letters) < 2:
        return False
    # «с историей…» часто без кавычек уже отфильтровано; ловим mid-string
    if re.search(r"(?i)историей|по\s+запросу|нулевк|нулёвк", core):
        return False
    return True


def extract_name(text: str) -> str:
    # 1) ООО в кавычках — самый надёжный вариант
    for m in RE_OOO_QUOTED.finditer(text):
        core = _clean_firm_core(m.group(1))
        if is_plausible_firm_name(core):
            return f"ООО «{core}»"
    # 2) ООО БРЕНД заглавными (без «с историей…»)
    for m in RE_OOO_BARE.finditer(text):
        core = _clean_firm_core(m.group(1))
        if is_plausible_firm_name(core):
            return f"ООО «{core}»"
    # 3) первая строка — только если похожа на бренд, не на объявление
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 2:
            continue
        if RE_SPAM.search(line):
            continue
        if re.fullmatch(r"[✅✔️❇️💎🟢🔥⚜️💲💵✍📱🚦❌📍\s]+", line):
            continue
        if re.match(r"^(для связи|пишите|стоимость|цена)\b", line, re.I):
            continue
        clean = re.sub(r"^[\W_🟢✅✔️❇️💎🔥]+", "", line).strip()
        if not clean or clean.lower().startswith("инн"):
            continue
        if RE_BAD_NAME_LINE.search(clean):
            continue
        if re.search(r"(?i)с\s+историей|инн\s+по\s+запросу|нужна\s+компа", clean):
            continue
        # строка целиком «ООО …» — прогоняем через валидатор
        if re.match(r"(?i)^ООО\b", clean):
            core = _clean_firm_core(re.sub(r"(?i)^ООО\s*", "", clean))
            if is_plausible_firm_name(core):
                return f"ООО «{core[:80]}»"
            continue
        if is_plausible_firm_name(clean[:80]):
            return clean[:120]
    return ""


def extract_inn(text: str) -> tuple[str, bool]:
    on_req = bool(RE_INN_ON_REQUEST.search(text))
    m = RE_INN_LABELED.search(text)
    if m:
        return m.group(1), on_req
    # 10-значные числа: не путать с ОГРН/телефоном
    candidates = re.findall(r"\b(\d{10})\b", text)
    # исключить куски ОГРН
    ogrns = set(RE_OGRN.findall(text))
    for c in candidates:
        if any(c in o for o in ogrns):
            continue
        # грубый контроль ИНН юрлица: 10 цифр
        return c, on_req
    return "", on_req


def is_spam_or_ad(text: str) -> str:
    t = text.strip()
    if len(t) < 40:
        return "too_short"
    if RE_SPAM.search(t) and not RE_OOO.search(t) and not RE_INN_LABELED.search(t):
        return "catalog_ad"
    # прайс без конкретной фирмы
    if re.search(r"без\s+сч[её]та\s+от\s+\d", t, re.I) and t.count("ООО") == 0:
        return "price_list"
    # спрос: «нужна нулёвка» без продажи конкретной фирмы
    if RE_BUYER.search(t[:400]) and not RE_SALE.search(t[:400]) and not RE_INN_LABELED.search(t):
        if not RE_OOO.search(t):
            return "buyer_request"
    return ""


def split_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    # обрезать общий футер у всего сообщения — режем внутри блока позже
    parts = [p.strip() for p in RE_SPLIT.split(text) if p and p.strip()]
    if len(parts) <= 1:
        # альтернатива: несколько "✅ ООО" в одном куске
        chunks = re.split(r"(?=✅\s*ООО\b)", text)
        parts = [p.strip() for p in chunks if p.strip()]

    # если всё ещё один блок, но несколько ИНН-карточек
    if len(parts) == 1 and len(RE_INN_LABELED.findall(text)) > 1:
        chunks = re.split(r"(?=ИНН\s*[:\-]?\s*\d{10})", text, flags=re.I)
        # первая часть — шапка; приклеиваем к следующим если без ИНН
        rebuilt: list[str] = []
        header = ""
        for i, ch in enumerate(chunks):
            ch = ch.strip()
            if not ch:
                continue
            if i == 0 and not RE_INN_LABELED.search(ch):
                header = ch
                continue
            rebuilt.append((header + "\n" + ch).strip() if header and i == 1 else ch)
        if rebuilt:
            parts = rebuilt

    return parts or [text]


def trim_footer(block: str) -> str:
    m = FOOTER_CUT.search(block)
    if m and m.start() > 80:
        return block[: m.start()].strip()
    return block.strip()


def parse_block(
    block: str,
    *,
    chat_id: int,
    message_id: int,
    block_index: int,
    sender: str,
    msg_date: str,
) -> Listing:
    block = trim_footer(block)
    listing = Listing(
        chat_id=chat_id,
        message_id=message_id,
        block_index=block_index,
        link=message_link(chat_id, message_id),
        seller_from_msg=sender or "",
        msg_date=msg_date,
        raw_text=block,
    )

    skip = is_spam_or_ad(block)
    # блок-часть мультипоста может быть короче — проверяем мягче
    if skip in {"catalog_ad", "price_list", "buyer_request"}:
        listing.is_listing = False
        listing.skip_reason = skip
        return listing

    listing.name = extract_name(block)
    inn, on_req = extract_inn(block)
    listing.inn = inn
    listing.inn_on_request = on_req
    ogrn_m = RE_OGRN.search(block)
    listing.ogrn = ogrn_m.group(1) if ogrn_m else ""
    listing.reg_date_raw, listing.reg_year = extract_reg(block)
    listing.price_rub, listing.price_raw = extract_price(block)
    listing.sno = extract_sno(block)
    okveds = RE_OKVED.findall(block)
    listing.okved = okveds[0] if okveds else ""
    listing.zsk_claim = extract_zsk(block)
    if RE_NO_ACCOUNT.search(block):
        listing.has_account_claim = "no"
    elif re.search(r"\b(?:счет|счёт|р/с)\b", block, re.I):
        listing.has_account_claim = "yes"
    else:
        listing.has_account_claim = "unknown"
    listing.has_blocks_claim = bool(RE_BLOCKS.search(block))
    listing.no_debts_claim = bool(RE_DEBTS_NO.search(block))
    listing.zero_turnover_claim = bool(RE_ZERO.search(block))
    listing.primary_1c_claim = bool(RE_PRIMARY.search(block))
    listing.revenues = extract_revenues(block)

    users = RE_USERNAME.findall(block)
    # не брать служебные боты каталога если есть нормальный контакт
    listing.seller_username = users[0] if users else (sender or "")

    # фейковое «ООО с историей…» без ИНН — не лот
    if listing.name and not is_plausible_firm_name(listing.name):
        listing.name = ""

    # валидность: нужен ИНН/ОГРН или нормальное имя + цена/режим
    has_id = bool(listing.inn or listing.ogrn)
    has_name = bool(listing.name and is_plausible_firm_name(listing.name))
    looks_like = bool(
        has_id
        or (
            has_name
            and (listing.price_rub or listing.sno or listing.revenues)
        )
    )
    if not looks_like:
        listing.is_listing = False
        listing.skip_reason = skip or "not_a_listing"
    return listing


def parse_message(
    text: str,
    *,
    chat_id: int,
    message_id: int,
    sender: str = "",
    msg_date: str = "",
) -> list[Listing]:
    if not text or not text.strip():
        return []

    global_skip = is_spam_or_ad(text)
    if global_skip in {"catalog_ad", "price_list"} and not RE_INN_LABELED.search(text):
        return []

    blocks = split_blocks(text)
    listings: list[Listing] = []
    for i, block in enumerate(blocks):
        item = parse_block(
            block,
            chat_id=chat_id,
            message_id=message_id,
            block_index=i,
            sender=sender,
            msg_date=msg_date,
        )
        if item.is_listing:
            listings.append(item)
    return listings
