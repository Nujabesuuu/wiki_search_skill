"""Language code normalisation: agents often write 'Polish' or 'польська' instead of 'pl'."""
from __future__ import annotations

import re

# code: (English name, native name, Ukrainian name)
LANGUAGES = {
    "en": ("English", "English", "англійська"), "de": ("German", "Deutsch", "німецька"),
    "fr": ("French", "français", "французька"), "es": ("Spanish", "español", "іспанська"),
    "it": ("Italian", "italiano", "італійська"), "pt": ("Portuguese", "português", "португальська"),
    "pl": ("Polish", "polski", "польська"), "cs": ("Czech", "čeština", "чеська"),
    "sk": ("Slovak", "slovenčina", "словацька"), "uk": ("Ukrainian", "українська", "українська"),
    "ru": ("Russian", "русский", "російська"), "be": ("Belarusian", "беларуская", "білоруська"),
    "bg": ("Bulgarian", "български", "болгарська"), "ro": ("Romanian", "română", "румунська"),
    "hu": ("Hungarian", "magyar", "угорська"), "nl": ("Dutch", "Nederlands", "нідерландська"),
    "sv": ("Swedish", "svenska", "шведська"), "no": ("Norwegian", "norsk", "норвезька"),
    "da": ("Danish", "dansk", "данська"), "fi": ("Finnish", "suomi", "фінська"),
    "et": ("Estonian", "eesti", "естонська"), "lv": ("Latvian", "latviešu", "латиська"),
    "lt": ("Lithuanian", "lietuvių", "литовська"), "el": ("Greek", "Ελληνικά", "грецька"),
    "tr": ("Turkish", "Türkçe", "турецька"), "ar": ("Arabic", "العربية", "арабська"),
    "he": ("Hebrew", "עברית", "іврит"), "fa": ("Persian", "فارسی", "перська"),
    "hi": ("Hindi", "हिन्दी", "гінді"), "bn": ("Bengali", "বাংলা", "бенгальська"),
    "ur": ("Urdu", "اردو", "урду"), "id": ("Indonesian", "Bahasa Indonesia", "індонезійська"),
    "ms": ("Malay", "Bahasa Melayu", "малайська"), "vi": ("Vietnamese", "Tiếng Việt", "вʼєтнамська"),
    "th": ("Thai", "ไทย", "тайська"), "zh": ("Chinese", "中文", "китайська"),
    "ja": ("Japanese", "日本語", "японська"), "ko": ("Korean", "한국어", "корейська"),
    "hr": ("Croatian", "hrvatski", "хорватська"), "sr": ("Serbian", "српски", "сербська"),
    "sl": ("Slovenian", "slovenščina", "словенська"), "ka": ("Georgian", "ქართული", "грузинська"),
    "kk": ("Kazakh", "қазақша", "казахська"), "az": ("Azerbaijani", "azərbaycanca", "азербайджанська"),
    "ca": ("Catalan", "català", "каталанська"), "sw": ("Swahili", "Kiswahili", "суахілі"),
    "tl": ("Tagalog", "Tagalog", "тагальська"),
}

_ALIASES = {}
for _code, _names in LANGUAGES.items():
    for _n in _names:
        _ALIASES[_n.lower()] = _code
_ALIASES.update({"czech republic": "cs", "farsi": "fa", "mandarin": "zh", "portuguese (brazil)": "pt",
                 "norwegian bokmål": "no", "nb": "no", "filipino": "tl"})

_CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,8})*$")


class LanguageError(ValueError):
    pass


def normalize_lang(value: str) -> str:
    v = value.strip().lower()
    v = v.removesuffix(".wikipedia").removesuffix(".wikipedia.org").removesuffix("wiki")
    if v in _ALIASES:
        return _ALIASES[v]
    if _CODE_RE.match(v):
        return v
    raise LanguageError(f"Unknown language '{value}'. Use a Wikipedia language code such as pl, cs, uk, de.")


def parse_langs(value: str | list[str]) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,\s]+", value)
    out: list[str] = []
    for item in items:
        if item.strip():
            code = normalize_lang(item)
            if code not in out:
                out.append(code)
    return out


def lang_name(code: str) -> str:
    return LANGUAGES.get(code, (code,))[0]


def project(code: str) -> str:
    return f"{code}.wikipedia"


def dbname(code: str) -> str:
    return code.replace("-", "_") + "wiki"
