"""Time-zone, region/language and locale mappings.

These tables are deliberately explicit and reviewable.  They are not a
complete IANA database: ``zoneinfo`` remains the authority for offsets.  The
Windows table is used only to translate a native Windows time-zone id for
``tzutil`` and for display; unknown zones fall back to the platform's own
identifier and are reported rather than silently guessed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Common Windows display ids <-> IANA ids.  Windows exposes more ids; unknown
# ids are treated as opaque and their current UTC offset is still measured.
WINDOWS_TO_IANA: dict[str, str] = {
    "UTC": "UTC",
    "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Taipei Standard Time": "Asia/Taipei",
    "Singapore Standard Time": "Asia/Singapore",
    "India Standard Time": "Asia/Kolkata",
    "Pakistan Standard Time": "Asia/Karachi",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Myanmar Standard Time": "Asia/Yangon",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Arabian Standard Time": "Asia/Dubai",
    "Arab Standard Time": "Asia/Riyadh",
    "Iran Standard Time": "Asia/Tehran",
    "Israel Standard Time": "Asia/Jerusalem",
    "Turkey Standard Time": "Europe/Istanbul",
    "Russian Standard Time": "Europe/Moscow",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "E. Europe Standard Time": "Europe/Chisinau",
    "FLE Standard Time": "Europe/Kyiv",
    "GTB Standard Time": "Europe/Bucharest",
    "Atlantic Standard Time": "America/Halifax",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Mexico Standard Time": "America/Mexico_City",
    "Central America Standard Time": "America/Guatemala",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Newfoundland Standard Time": "America/St_Johns",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "AUS Central Standard Time": "Australia/Darwin",
    "W. Australia Standard Time": "Australia/Perth",
    "New Zealand Standard Time": "Pacific/Auckland",
    "South Africa Standard Time": "Africa/Johannesburg",
    "Egypt Standard Time": "Africa/Cairo",
    "Morocco Standard Time": "Africa/Casablanca",
    "Kenya Standard Time": "Africa/Nairobi",
}

IANA_TO_WINDOWS: dict[str, str] = {}
for _win, _iana in WINDOWS_TO_IANA.items():
    IANA_TO_WINDOWS.setdefault(_iana, _win)

# Extra common aliases.
IANA_TO_WINDOWS.update(
    {
        "Asia/Calcutta": "India Standard Time",
        "Asia/Hong_Kong": "China Standard Time",
        "Asia/Macau": "China Standard Time",
        "Asia/Chongqing": "China Standard Time",
        "Asia/Urumqi": "China Standard Time",
        "Europe/Amsterdam": "W. Europe Standard Time",
        "Europe/Brussels": "Romance Standard Time",
        "Europe/Madrid": "Romance Standard Time",
        "Europe/Rome": "W. Europe Standard Time",
        "Europe/Vienna": "W. Europe Standard Time",
        "Europe/Zurich": "W. Europe Standard Time",
        "Europe/Stockholm": "W. Europe Standard Time",
        "Europe/Oslo": "W. Europe Standard Time",
        "Europe/Copenhagen": "Romance Standard Time",
        "Europe/Helsinki": "FLE Standard Time",
        "Europe/Athens": "GTB Standard Time",
        "Europe/Lisbon": "GMT Standard Time",
        "Europe/Dublin": "GMT Standard Time",
        "America/Toronto": "Eastern Standard Time",
        "America/Vancouver": "Pacific Standard Time",
        "America/Phoenix": "Mountain Standard Time",
        "America/Monterrey": "Central Standard Time",
        "America/Buenos_Aires": "Argentina Standard Time",
        "Australia/Melbourne": "AUS Eastern Standard Time",
        "Australia/Brisbane": "AUS Eastern Standard Time",
        "Pacific/Auckland": "New Zealand Standard Time",
        "Etc/UTC": "UTC",
    }
)

WESTERN_COUNTRIES = {
    "US",
    "CA",
    "GB",
    "IE",
    "FR",
    "DE",
    "NL",
    "BE",
    "LU",
    "CH",
    "AT",
    "IT",
    "ES",
    "PT",
    "SE",
    "NO",
    "DK",
    "FI",
    "IS",
    "PL",
    "CZ",
    "SK",
    "HU",
    "RO",
    "BG",
    "GR",
    "HR",
    "SI",
    "EE",
    "LV",
    "LT",
    "AU",
    "NZ",
    "MT",
    "CY",
}

CJK_COUNTRIES = {"CN", "TW", "HK", "MO", "JP", "KR", "KP"}

# Country -> likely language families.  A set, because several countries are
# bilingual.  This is a consistency heuristic, never proof of identity.
COUNTRY_LANGUAGES: dict[str, set[str]] = {
    "CN": {"zh"},
    "TW": {"zh"},
    "HK": {"zh", "en"},
    "MO": {"zh", "pt"},
    "SG": {"en", "zh", "ms", "ta"},
    "JP": {"ja"},
    "KR": {"ko"},
    "KP": {"ko"},
    "US": {"en", "es"},
    "CA": {"en", "fr"},
    "GB": {"en"},
    "IE": {"en", "ga"},
    "AU": {"en"},
    "NZ": {"en", "mi"},
    "IN": {"en", "hi", "ta", "te", "bn", "mr", "gu", "kn", "ml", "pa"},
    "DE": {"de"},
    "AT": {"de"},
    "CH": {"de", "fr", "it", "rm"},
    "FR": {"fr"},
    "BE": {"nl", "fr", "de"},
    "NL": {"nl"},
    "LU": {"fr", "de", "lb"},
    "ES": {"es", "ca", "gl", "eu"},
    "MX": {"es"},
    "AR": {"es"},
    "CL": {"es"},
    "CO": {"es"},
    "PE": {"es"},
    "BR": {"pt"},
    "PT": {"pt"},
    "IT": {"it"},
    "SE": {"sv"},
    "NO": {"no", "nb", "nn"},
    "DK": {"da"},
    "FI": {"fi", "sv"},
    "IS": {"is"},
    "PL": {"pl"},
    "CZ": {"cs"},
    "SK": {"sk"},
    "HU": {"hu"},
    "RO": {"ro"},
    "BG": {"bg"},
    "GR": {"el"},
    "HR": {"hr"},
    "SI": {"sl"},
    "EE": {"et"},
    "LV": {"lv"},
    "LT": {"lt"},
    "RU": {"ru"},
    "BY": {"be", "ru"},
    "UA": {"uk", "ru"},
    "TR": {"tr"},
    "IL": {"he", "ar", "en"},
    "SA": {"ar"},
    "AE": {"ar", "en"},
    "EG": {"ar"},
    "ZA": {"en", "af", "zu", "xh"},
    "NG": {"en"},
    "KE": {"en", "sw"},
    "MA": {"ar", "fr"},
    "TH": {"th"},
    "VN": {"vi"},
    "ID": {"id"},
    "MY": {"ms", "en", "zh", "ta"},
    "PH": {"en", "tl"},
    "PK": {"ur", "en"},
    "BD": {"bn"},
    "LK": {"si", "ta"},
    "NP": {"ne"},
}

# Fallback locale for a country when the exit IP does not expose a time zone.
COUNTRY_LOCALE: dict[str, str] = {
    "CN": "zh-CN",
    "TW": "zh-TW",
    "HK": "zh-HK",
    "MO": "zh-MO",
    "SG": "en-SG",
    "JP": "ja-JP",
    "KR": "ko-KR",
    "US": "en-US",
    "CA": "en-CA",
    "GB": "en-GB",
    "IE": "en-IE",
    "AU": "en-AU",
    "NZ": "en-NZ",
    "IN": "en-IN",
    "DE": "de-DE",
    "AT": "de-AT",
    "CH": "de-CH",
    "FR": "fr-FR",
    "BE": "nl-BE",
    "NL": "nl-NL",
    "ES": "es-ES",
    "MX": "es-MX",
    "AR": "es-AR",
    "CL": "es-CL",
    "CO": "es-CO",
    "BR": "pt-BR",
    "PT": "pt-PT",
    "IT": "it-IT",
    "SE": "sv-SE",
    "NO": "nb-NO",
    "DK": "da-DK",
    "FI": "fi-FI",
    "PL": "pl-PL",
    "CZ": "cs-CZ",
    "TR": "tr-TR",
    "RU": "ru-RU",
    "UA": "uk-UA",
    "IL": "he-IL",
    "SA": "ar-SA",
    "AE": "ar-AE",
    "EG": "ar-EG",
    "ZA": "en-ZA",
    "TH": "th-TH",
    "VN": "vi-VN",
    "ID": "id-ID",
    "MY": "ms-MY",
    "PH": "en-PH",
    "PK": "ur-PK",
    "BD": "bn-BD",
}

LANGUAGE_LOCALE: dict[str, str] = {
    "en": "en-US",
    "zh": "zh-CN",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "de": "de-DE",
    "fr": "fr-FR",
    "es": "es-ES",
    "pt": "pt-BR",
    "it": "it-IT",
    "nl": "nl-NL",
    "sv": "sv-SE",
    "no": "nb-NO",
    "nb": "nb-NO",
    "da": "da-DK",
    "fi": "fi-FI",
    "pl": "pl-PL",
    "cs": "cs-CZ",
    "ru": "ru-RU",
    "uk": "uk-UA",
    "tr": "tr-TR",
    "ar": "ar-SA",
    "he": "he-IL",
    "hi": "hi-IN",
    "th": "th-TH",
    "vi": "vi-VN",
    "id": "id-ID",
    "ms": "ms-MY",
}

# Only used to align a system time zone when the exit provider gives no zone.
# For countries spanning multiple zones (US/CA/AU/RU/BR), this is explicitly a
# representative fallback and the audit/report flags it as such.
COUNTRY_FALLBACK_ZONE: dict[str, str] = {
    "CN": "Asia/Shanghai",
    "TW": "Asia/Taipei",
    "HK": "Asia/Hong_Kong",
    "MO": "Asia/Macau",
    "SG": "Asia/Singapore",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "IN": "Asia/Kolkata",
    "US": "America/New_York",
    "CA": "America/Toronto",
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "NL": "Europe/Amsterdam",
    "BE": "Europe/Brussels",
    "CH": "Europe/Zurich",
    "AT": "Europe/Vienna",
    "IT": "Europe/Rome",
    "ES": "Europe/Madrid",
    "PT": "Europe/Lisbon",
    "SE": "Europe/Stockholm",
    "NO": "Europe/Oslo",
    "DK": "Europe/Copenhagen",
    "FI": "Europe/Helsinki",
    "PL": "Europe/Warsaw",
    "CZ": "Europe/Prague",
    "TR": "Europe/Istanbul",
    "RU": "Europe/Moscow",
    "UA": "Europe/Kyiv",
    "IL": "Asia/Jerusalem",
    "SA": "Asia/Riyadh",
    "AE": "Asia/Dubai",
    "EG": "Africa/Cairo",
    "ZA": "Africa/Johannesburg",
    "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City",
    "AR": "America/Argentina/Buenos_Aires",
    "TH": "Asia/Bangkok",
    "VN": "Asia/Ho_Chi_Minh",
    "ID": "Asia/Jakarta",
    "MY": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",
    "PK": "Asia/Karachi",
    "BD": "Asia/Dhaka",
}


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("_", "-").split(".", 1)[0]
    if not text:
        return None
    language = text.split("-", 1)[0].lower()
    if language in {"c", "posix"}:
        return None
    return language


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("_", "-").split(".", 1)[0]
    if not text or text.lower() in {"c", "posix"}:
        return None
    return text


def locale_for_country(country_code: str | None, language: str | None = None) -> str:
    if country_code and country_code.upper() in COUNTRY_LOCALE:
        return COUNTRY_LOCALE[country_code.upper()]
    if language and language.lower() in LANGUAGE_LOCALE:
        return LANGUAGE_LOCALE[language.lower()]
    return "en-US"


def language_for_country(country_code: str | None) -> str | None:
    if not country_code:
        return None
    languages = COUNTRY_LANGUAGES.get(country_code.upper())
    if not languages:
        return None
    # Prefer English when both are plausible; otherwise choose deterministically
    # from the declared set.
    if "en" in languages:
        return "en"
    return sorted(languages)[0]


# Standard (winter) UTC offsets in minutes.  This fallback exists because a
# bare Windows CPython may not ship the IANA tzdata package; ZoneInfo is used
# first whenever it is available.  DST is handled for the common North
# American, European, Australian and New Zealand zones below.  The ±2h audit
# tolerance means a one-hour DST approximation never creates a false failure;
# the exact zone-name comparison is preferred whenever possible.
STANDARD_OFFSET_MINUTES: dict[str, int] = {
    "UTC": 0,
    "Etc/UTC": 0,
    "Asia/Shanghai": 480,
    "Asia/Chongqing": 480,
    "Asia/Urumqi": 480,
    "Asia/Hong_Kong": 480,
    "Asia/Macau": 480,
    "Asia/Taipei": 480,
    "Asia/Singapore": 480,
    "Asia/Tokyo": 540,
    "Asia/Seoul": 540,
    "Asia/Kolkata": 330,
    "Asia/Calcutta": 330,
    "Asia/Karachi": 300,
    "Asia/Dhaka": 360,
    "Asia/Bangkok": 420,
    "Asia/Yangon": 390,
    "Asia/Kathmandu": 345,
    "Asia/Colombo": 330,
    "Asia/Dubai": 240,
    "Asia/Riyadh": 180,
    "Asia/Tehran": 210,
    "Asia/Jerusalem": 120,
    "Asia/Ho_Chi_Minh": 420,
    "Asia/Jakarta": 420,
    "Asia/Kuala_Lumpur": 480,
    "Asia/Manila": 480,
    "Europe/Istanbul": 180,
    "Europe/Moscow": 180,
    "Europe/Kyiv": 120,
    "Europe/London": 0,
    "Atlantic/Reykjavik": 0,
    "Europe/Dublin": 0,
    "Europe/Lisbon": 0,
    "Europe/Berlin": 60,
    "Europe/Paris": 60,
    "Europe/Madrid": 60,
    "Europe/Rome": 60,
    "Europe/Amsterdam": 60,
    "Europe/Brussels": 60,
    "Europe/Vienna": 60,
    "Europe/Zurich": 60,
    "Europe/Stockholm": 60,
    "Europe/Oslo": 60,
    "Europe/Copenhagen": 60,
    "Europe/Prague": 60,
    "Europe/Warsaw": 60,
    "Europe/Budapest": 60,
    "Europe/Belgrade": 60,
    "Europe/Bucharest": 120,
    "Europe/Athens": 120,
    "Europe/Helsinki": 120,
    "Europe/Chisinau": 120,
    "America/New_York": -300,
    "America/Toronto": -300,
    "America/Chicago": -360,
    "America/Mexico_City": -360,
    "America/Monterrey": -360,
    "America/Denver": -420,
    "America/Phoenix": -420,
    "America/Los_Angeles": -480,
    "America/Vancouver": -480,
    "America/Anchorage": -540,
    "Pacific/Honolulu": -600,
    "America/Halifax": -240,
    "America/St_Johns": -210,
    "America/Bogota": -300,
    "America/Lima": -300,
    "America/Guatemala": -360,
    "America/La_Paz": -240,
    "America/Santiago": -240,
    "America/Argentina/Buenos_Aires": -180,
    "America/Buenos_Aires": -180,
    "America/Sao_Paulo": -180,
    "Australia/Sydney": 600,
    "Australia/Melbourne": 600,
    "Australia/Brisbane": 600,
    "Australia/Darwin": 570,
    "Australia/Perth": 480,
    "Pacific/Auckland": 720,
    "Africa/Johannesburg": 120,
    "Africa/Cairo": 120,
    "Africa/Casablanca": 60,
    "Africa/Lagos": 60,
    "Africa/Nairobi": 180,
}

# Zones whose local clock observes DST and the rule family used to approximate
# the current offset when tzdata is unavailable.
NORTH_AMERICA_DST = {
    "America/New_York",
    "America/Toronto",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Vancouver",
    "America/Halifax",
    "America/St_Johns",
}
EUROPE_DST = {
    "Europe/London",
    "Europe/Dublin",
    "Europe/Lisbon",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Vienna",
    "Europe/Zurich",
    "Europe/Stockholm",
    "Europe/Oslo",
    "Europe/Copenhagen",
    "Europe/Prague",
    "Europe/Warsaw",
    "Europe/Budapest",
    "Europe/Belgrade",
    "Europe/Bucharest",
    "Europe/Athens",
    "Europe/Helsinki",
    "Europe/Chisinau",
    "Europe/Kyiv",
}
AUSTRALIA_DST = {"Australia/Sydney", "Australia/Melbourne"}
NEW_ZEALAND_DST = {"Pacific/Auckland"}


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (6 - first.weekday()) % 7  # Monday=0, Sunday=6
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_sunday(year: int, month: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _northern_dst_active(today: date, start: date, end: date) -> bool:
    return start <= today < end


def _approx_dst_active(iana: str, today: date) -> bool:
    if iana in NORTH_AMERICA_DST:
        return _northern_dst_active(
            today,
            _nth_sunday(today.year, 3, 2),
            _nth_sunday(today.year, 11, 1),
        )
    if iana in EUROPE_DST:
        return _northern_dst_active(
            today,
            _last_sunday(today.year, 3),
            _last_sunday(today.year, 10),
        )
    if iana in AUSTRALIA_DST:
        start = _nth_sunday(today.year, 10, 1)
        end = _nth_sunday(today.year, 4, 1)
        return today >= start or today < end
    if iana in NEW_ZEALAND_DST:
        start = _last_sunday(today.year, 9)
        end = _nth_sunday(today.year, 4, 1)
        return today >= start or today < end
    return False


def offset_for_zone(iana: str | None, at: datetime | None = None) -> int | None:
    if not iana:
        return None
    try:
        zone = ZoneInfo(iana)
    except (ZoneInfoNotFoundError, ValueError):
        base = STANDARD_OFFSET_MINUTES.get(iana)
        if base is None:
            return None
        when = (at or datetime.now()).date()
        if _approx_dst_active(iana, when):
            base += 60
        return base * 60
    when = at or datetime.now(zone)
    try:
        offset = when.astimezone(zone).utcoffset()
    except (ValueError, OverflowError):
        return None
    return int(offset.total_seconds()) if offset is not None else None


def windows_id_for_iana(iana: str | None) -> str | None:
    if not iana:
        return None
    return IANA_TO_WINDOWS.get(iana)


def iana_for_windows_id(native_id: str | None) -> str | None:
    if not native_id:
        return None
    direct = WINDOWS_TO_IANA.get(native_id)
    if direct:
        return direct
    # tzutil can emit a display name with a different casing.
    lowered = {k.lower(): v for k, v in WINDOWS_TO_IANA.items()}
    return lowered.get(native_id.lower())


def country_is_western(country_code: str | None) -> bool:
    return bool(country_code and country_code.upper() in WESTERN_COUNTRIES)


def country_is_cjk(country_code: str | None) -> bool:
    return bool(country_code and country_code.upper() in CJK_COUNTRIES)


def language_region_conflict(language: str | None, country_code: str | None) -> tuple[bool, str]:
    """Return (is_hard_conflict, explanation).

    Hard conflict deliberately covers the requested Chinese-system + Western-IP
    case, plus the symmetric CJK/Western case.  Other mismatches are advisory.
    """
    lang = normalize_language(language)
    country = country_code.upper() if country_code else None
    expected = COUNTRY_LANGUAGES.get(country or "", set())
    if not lang or not expected:
        return False, "国家或语言样本不足，无法判断冲突。"
    if lang in expected:
        return False, f"语言 {lang} 与该国家/地区的常见语言集合一致。"
    if lang == "zh" and country_is_western(country):
        return True, f"中文系统 + 欧美出口（{country}）是明显的语言/地区画像冲突。"
    if lang in {"ja", "ko"} and country_is_western(country):
        return True, f"{lang} 语言系统 + 欧美出口（{country}）存在明显冲突。"
    if lang in {"en", "de", "fr", "es", "pt", "it", "nl"} and country_is_cjk(country):
        return True, f"西方语言系统 + CJK 出口（{country}）存在明显冲突。"
    return False, f"语言 {lang} 不在 {country} 的常见语言集合中，但不足以判定为硬冲突。"


def accept_language_value(locale: str) -> str:
    tag = normalize_locale(locale) or "en-US"
    language = normalize_language(tag) or "en"
    if language == tag.lower():
        return language
    return f"{tag},{language}"
