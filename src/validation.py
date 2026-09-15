"""Plain-text contract for model answers and published post bodies.

Reject artifacts instead of deleting them: stripping tags or template expressions
can silently change technical facts. Inspection uses NFKC to catch fullwidth
delimiters and compatibility ideographs; the original text is never rewritten.
"""

import html
import json
import re
import unicodedata


PLAIN_TEXT_INSTRUCTION = (
    "Пиши обычным текстом на русском языке; латинские технические названия допустимы. "
    "Китайские иероглифы запрещены. Не используй Markdown (выделение, обратные "
    "кавычки, заголовки, списки, таблицы, разделители), HTML/XML, HTML-сущности, "
    "Jinja и другие шаблоны, BBCode или LaTeX. Не оборачивай ответ в JSON/YAML. "
    "Разделяй абзацы пустой строкой. Команды, флаги и ссылки пиши обычным текстом."
)

# Unicode 17.0 Script=Han, including radicals and supplementary ideographs.
# https://www.unicode.org/Public/17.0.0/ucd/Scripts.txt
# Han is shared with Japanese/Korean; this is a character check, not a language detector.
HAN_PATTERN = re.compile(
    "[\u2e80-\u2e99\u2e9b-\u2ef3\u2f00-\u2fd5\u3005\u3007"
    "\u3021-\u3029\u3038-\u303b\u3400-\u4dbf\u4e00-\u9fff"
    "\uf900-\ufa6d\ufa70-\ufad9\U00016fe2-\U00016fe3\U00016ff0-\U00016ff6"
    "\U00020000-\U0002a6df\U0002a700-\U0002b81d\U0002b820-\U0002cead"
    "\U0002ceb0-\U0002ebe0\U0002ebf0-\U0002ee5d\U0002f800-\U0002fa1d"
    "\U00030000-\U0003134a\U00031350-\U00033479]"
)

FORMAT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Markdown: обратные кавычки или блок кода", re.compile(r"`|~{3,}")),
    ("Markdown: выделение текста", re.compile(
        r"\*{2,}|(?<!\w)_{2,}|_{2,}(?!\w)|~{2,}"
        r"|\*(?=\S)[^*]*?(?<=\S)\*"
        r"|(?<!\w)_(?=\S)[^_]*?(?<=\S)_(?!\w)"
        r"|\|\|(?=\S)[^|]*?(?<=\S)\|\|"
    )),
    ("Markdown: заголовок, список или цитата", re.compile(
        r"^[ \t]*(?:#{1,6}(?:[ \t]+|$)|>"
        r"|(?:[-+*•▪◦‣]|\d{1,9}[.)])(?:[ \t]+|$))", re.MULTILINE
    )),
    ("Markdown: разделитель", re.compile(
        r"(?<!\S)--(?!\S)|(?<!\w)-{3,}"
        r"|--(?=\S)[^\n]*?(?<=\S)--"
        r"|^[ \t]*(?:[=]+|(?:[_*~][ \t]*){3,}|[━─═]{2,})[ \t]*$",
        re.MULTILINE,
    )),
    ("Markdown: ссылка, изображение или сноска", re.compile(
        r"!?\[[^\]\n]*\][ \t]*(?:\(|\[)"
        r"|^[ \t]*\[[^\]\n]+\]:|\[\^[^\]\n]+\]|\[\[[^\n]*?\]\]"
        r"|<(?:[a-z][a-z0-9+.-]*:[^<>\s]+|[^<>\s]+@[^<>\s]+)>",
        re.MULTILINE | re.IGNORECASE,
    )),
    ("Markdown: таблица", re.compile(
        r"^[ \t]*\|[^\n]*\|[ \t]*$"
        r"|^[ \t]*\|?[ \t]*:?-+:?[ \t]*\|[ \t]*:?-+:?[^\n]*$",
        re.MULTILINE,
    )),
    ("Markdown: отступ блока кода", re.compile(r"^(?: {4,}|\t[ \t]*)\S", re.MULTILINE)),
    ("Markdown: принудительный перенос строки", re.compile(r"(?: {2,}|\\)\n")),
    ("Markdown: экранированная разметка", re.compile(r"\\[*_`#\[\]]")),
    ("Jinja или другая шаблонная разметка", re.compile(r"\{\{|\}\}|\{%|%\}|\{#|#\}|<%|%>")),
    ("HTML/XML: тег, комментарий или декларация", re.compile(
        r"</?[^\W\d][\w:.-]*(?:\s[^<>]*)?/?>|<!|<\?"
        r"|^[ \t]*</?[^\W\d][\w:.-]*(?:\s[^<>]*)?$"
        r"|(?:^|(?<=\s))</?(?:b|i|em|strong|code|pre|div|span|p|br|a|post|text|root)(?:\s[^<>]*)?$",
        re.MULTILINE | re.IGNORECASE,
    )),
    ("Служебные токены модели в тексте ответа", re.compile(r"<\||<[^<>\s]*\|>")),
    ("BBCode: разметка текста", re.compile(
        r"\[/?(?:b|i|u|s|url|img|code|quote|list|size|color|font|spoiler|table|tr|td)(?:=[^\]\n]*)?\]",
        re.IGNORECASE,
    )),
    ("LaTeX: разметка текста или формулы", re.compile(
        r"\\[a-zA-Z]+\*?(?:\[[^\]\n]*\])?\s*\{"
        r"|\\[()\[\]]|\$\$|(?<![\w\\])\$(?=\S)[^$\n]*?(?<=\S)\$(?!\w)"
    )),
    ("YAML: обёртка ответа", re.compile(
        r"\A\s*(?:text|post|content|response|answer|draft|текст|пост|ответ|черновик)[ \t]*:",
        re.IGNORECASE,
    )),
)

ENTITY_PATTERN = re.compile(r"&(?:#[0-9]{1,7};?|#[xX][0-9a-fA-F]{1,6};?|[a-zA-Z][a-zA-Z0-9]{1,31};)")


class ResponseValidationError(ValueError):
    """A model answer or saved post violates the plain-text contract."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("Ответ отклонён: " + "; ".join(self.errors))


def validate_plain_text(text: object) -> list[str]:
    """Return one actionable error per violated rule, without modifying the input."""
    if not isinstance(text, str):
        return ["Ответ должен быть строкой текста"]
    if not text.strip():
        return ["Ответ пустой"]

    errors: list[str] = []
    # Preserve emoji ZWJ sequences in the output, but don't let joiners hide markup.
    inspected = unicodedata.normalize("NFKC", text).replace("\u200d", "")
    if HAN_PATTERN.search(text) or HAN_PATTERN.search(inspected):
        errors.append("Обнаружены китайские иероглифы (Han); перепиши фрагмент по-русски")

    for char in text:
        category = unicodedata.category(char)
        if (
            (category == "Cc" and char not in "\n\r\t")
            or (category == "Cf" and char != "\u200d")
            or category == "Cs"
        ):
            errors.append(f"Недопустимый управляющий или невидимый символ U+{ord(char):04X}")
            break

    # Treat every line ending consistently, even for a model emitting CR-only text.
    inspected = inspected.replace("\r\n", "\n").replace("\r", "\n")
    inspected = inspected.replace("\u2028", "\n").replace("\u2029", "\n")
    # The persona explicitly permits this kaomoji; its underscores are not emphasis.
    inspected = inspected.replace(unicodedata.normalize("NFKC", "¯\\_(ツ)_/¯"), " ")
    for label, pattern in FORMAT_RULES:
        if pattern.search(inspected):
            errors.append(f"{label}; нужен обычный текст")

    if any(html.unescape(match[0]) != match[0] for match in ENTITY_PATTERN.finditer(inspected)):
        errors.append("HTML-сущности запрещены; используй обычные символы текста")

    stripped = inspected.strip()
    if stripped.startswith(("{", "[")):
        try:
            value = json.loads(stripped)
        except (ValueError, RecursionError):
            pass
        else:
            if isinstance(value, (dict, list)):
                errors.append("JSON-обёртка запрещена; верни только текст поста")

    return errors


def require_plain_text(text: str) -> None:
    """Stop persistence or publication when a post contains forbidden artifacts."""
    errors = validate_plain_text(text)
    if errors:
        raise ResponseValidationError(errors)
