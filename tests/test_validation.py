"""Plain-text contract: forbidden artifacts and realistic technical counterexamples."""

import pytest

from src.lint import lint_post
from src.validation import ResponseValidationError, require_plain_text, validate_plain_text


@pytest.mark.parametrize("char", [
    "中", "文", "汉", "漢", "\u3400", "\u4dbf", "\u9fff", "\uf900", "\ufad9",
    "\u2e80", "\u2f00", "\u3007", "\u3021", "\u303b",
    "\U00016ff2", "\U00020000", "\U0002a6df", "\U0002b81d", "\U0002cead",
    "\U0002ebe0", "\U0002ee5d", "\U0002f800", "\U0002fa1d",
    "\U00030000", "\U0003134a", "\U00033479", "㊗",
])
def test_han_rejected_anywhere_in_prose(char):
    errors = validate_plain_text(f"Обычный текст {char} внутри предложения.")
    assert any("иероглифы" in error for error in errors)


@pytest.mark.parametrize("text", [
    "**Жирный** текст", "***Жирный курсив***", "**Оборванное выделение",
    "*Курсив* внутри текста", "_Курсив_ внутри текста", "__Жирный__ текст",
    "~~Зачёркнутый~~ текст", "||Спойлер|| в тексте", "Набери `ls`.",
    "Оборванный `код", "```markdown\nТекст\n```", "~~~python\nprint(1)\n~~~",
    "# Заголовок", "\n  ## Заголовок", "Заголовок\n=", "Заголовок\n--",
    "Текст -- продолжение", "Текст --- продолжение", "--выделение--",
    "Текст\n- - -\nПродолжение", "Текст\n***\nПродолжение",
    "- Пункт списка", "+ Пункт списка", "* Пункт списка", "• Пункт списка",
    "1. Первый пункт", "2) Второй пункт", "Текст\r- Пункт списка",
    "> Цитата", ">Цитата без пробела", "    print(1)", "        print(1)", "\tprint(1)",
    "Текст  \nПринудительный перенос", "Текст\\\nПринудительный перенос",
    "[Документация](https://example.com)", "![Картинка](image.png)",
    "[Документация][ref]", "[ref]: https://example.com", "Сноска[^1]",
    "[[Вики-ссылка]]", "<https://example.com>", "<mail@example.com>",
    "| Имя | Значение |\n| --- | --- |", "Имя | Значение\n--- | ---",
    r"\*экранированное выделение\*",
    "{{ name }}", "{{ незакрытая вставка", "{% if enabled %}Текст{% endif %}",
    "{# комментарий #}", "<%= expression %>",
    "<b>Жирный</b>", "<s>Зачёркнутый</s>", "<root />", '<item id="1">Текст</item>',
    "<ns:post>Текст</ns:post>", "<текст>Ответ</текст>", "Текст <br/> дальше",
    "<!-- комментарий -->", '<!DOCTYPE html>', '<![CDATA[Текст]]>',
    '<?xml version="1.0"?>', '<span class="unfinished', '<article',
    "[b]Жирный[/b]", "[url=https://example.com]Ссылка[/url]",
    r"\textbf{Жирный}", r"\begin{document}Текст\end{document}", r"\(x^2\)", "$x^2$", "$$x^2$$",
    r"\texttt{Код}", r"\href{https://example.com}{Ссылка}", r"\section*{Название}",
    "&lt;b&gt;Текст&lt;/b&gt;", "Текст &amp; ещё текст", "&#20013;", "&#x4e2d;",
    "&amp;lt;b&amp;gt;", "＜b＞Текст＜/b＞", "＊＊Жирный＊＊", "｛｛ name ｝｝",
    "<|channel>analysis", "Ответ<channel|>остаток", "Ответ<turn|>остаток",
    '{"text": "Текст поста"}', '["Текст поста"]', 'text: "Текст поста"', "\ncontent: |\n  Текст поста",
    "Текст\u200bсо скрытым символом", "Текст\x00с управляющим символом",
    "\u202eТекст", "*\u200d*скрытое выделение*\u200d*",
])
def test_markup_and_artifacts_rejected(text):
    assert validate_plain_text(text), repr(text)
    with pytest.raises(ResponseValidationError):
        require_plain_text(text)


@pytest.mark.parametrize("text", [
    "Ядро Linux изолирует процесс.\n\nСледующий абзац остаётся обычным текстом.",
    "Запусти docker run --read-only --network=none image.",
    "Команда ls --help выводит справку. Флаг -n ограничивает вывод.",
    "--help", "Флаги MS_PRIVATE, snake_case и prefix__suffix описаны в заголовке.",
    "systemd-udevd, UTF-8, read-only и /proc/self/mountinfo.",
    "Диапазон 10–20 мс. Таймаут — 30 секунд.",
    "Условие x < y и y > 0, значение x <= 10, y >= 2. Результат x<y.",
    "Вычисление 2 * 3 = 6; цена $10, бюджет $20; ошибка -1.",
    "Ссылка https://example.com/path?a=1&b=2 и почта ops@example.com.",
    "Значение $PATH хранит пути. Команда echo ${PATH} печатает значение.",
    "Запусти cat /proc/self/status | head -n 5 или command || fallback.",
    "Фильтр *.py ищет Python, а *.md — документацию.",
    "Вызов f(x), индекс values[0], набор {1, 2} и массив [1] описывают данные.",
    "C# и C++ используют разные модели. #linux — тег канала.",
    r"Путь C:\Users\mika\post.txt доступен процессу.",
    "Текст с «кавычками», (ремаркой), 50% и амперсандом &.",
    "Допустимые эмодзи 🚀 и ⚙️.", "Каомодзи ¯\\_(ツ)_/¯ в тексте.",
    "Эмодзи 👩‍💻 внутри предложения.", "Буква ё и е\u0308 допустимы.",
])
def test_plain_technical_text_is_preserved(text):
    assert validate_plain_text(text) == []
    require_plain_text(text)


@pytest.mark.parametrize("value", [None, 123, [], {}, "", " \n\t "])
def test_empty_and_non_text_responses_rejected(value):
    assert validate_plain_text(value)


@pytest.mark.parametrize("stage", ["draft", "critique", "publish"])
@pytest.mark.parametrize("artifact", ["中", "**выделение**", "{{ name }}", "<p>текст</p>"])
def test_lint_enforces_plain_text_at_every_stage(stage, artifact):
    text = "Ядро Linux проверяет доступ к файлу. " * 10 + artifact
    result = lint_post(text, "instrument", stage=stage)
    assert not result.passed
    assert all(error in result.errors for error in validate_plain_text(text))
