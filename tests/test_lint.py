"""Unit tests for src/lint.py - Validation rules, regexes, and bounds."""

import pytest
from src.lint import lint_post, RUBRIC_LIMITS, LintResult


def test_clean_post_passes_lint():
    # Valid post for 'razbor' rubric (800 - 1000 characters)
    text = (
        "Пространство имен mnt изолирует точки монтирования процессов. "
        "Флаг MS_SHARED распространяет события между пирами, тогда как MS_PRIVATE "
        "блокирует любые изменения файловой системы за пределами контейнера. "
        "В ядре подсистема idmapped mounts позволяет пробрасывать uid без пересчета прав.\n\n"
        "Когда демон systemd-udevd стартует в отдельном sandbox, попытка сменить root "
        "приводит к ошибке EPERM. Используйте pivot_root вместо chroot для полной отсечки. "
        "Любое расхождение в настройках seccomp фильтров открывает вектор для побега.\n\n"
        "Проверка изоляции выполняется через чтение mountinfo ядра. "
        "Архитектура ядра не прощает полумер при настройке приватных пространств имен."
    )
    # Pad to reach exactly 850 chars
    padding = " Дополнительный анализ байт-кода ядра подтверждает надежность."
    while len(text) < 850:
        text += padding

    res = lint_post(text, rubric="razbor", stage="critique")
    assert res.passed, f"Lint failed with errors: {res.errors}"
    assert len(res.errors) == 0


@pytest.mark.parametrize(
    "cliche,label",
    [
        ("важно отметить следующее", "важно отметить"),
        ("стоит отметить этот факт", "стоит отметить"),
        ("в современном мире технологии", "в современном мире"),
        ("играет ключевую роль в стеке", "играет ключевую роль"),
        ("не только в тестах, но и в продакшене", "не только... но и"),
        ("давайте разберемся в деталях", "давайте разберемся"),
        ("итак, подведем черту", "итак,"),
        ("в заключение статьи", "в заключение"),
        ("Итог: все работает стабильно", "Итог/Вывод"),
    ],
)
def test_banned_cliches_detected(cliche: str, label: str):
    text = f"Старт процесса. {cliche}. Завершение работы без ошибок в системе."
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any(label in err for err in res.errors)


def test_greeting_rejected():
    text = "Привет, разработчики! Сегодня мы разберем память ядра и утечки."
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any("приветствие" in err.lower() for err in res.errors)


def test_goodbye_rejected():
    text = "Ядро очищено от руткитов. До скорого!"
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any("прощание" in err.lower() for err in res.errors)


def test_question_at_end_rejected():
    text = "Настройка epoll завершена успешно. А как вы настраиваете сокеты в проде?"
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any("вопрос к читателю" in err.lower() for err in res.errors)


def test_diminutives_rejected():
    text = "Запустим наш маленький контейнерчик и проверим скриптик на ошибки."
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any("уменьшительные" in err.lower() for err in res.errors)


def test_excessive_emojis_rejected():
    text = "Первый запуск демона 🚀 прошел штатно. Но лог выдал ошибку 🔥! Проверьте дамп ⚡."
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any("эмодзи" in err.lower() for err in res.errors)


def test_kaomoji_rejected():
    text = "Стек вызовов чист (^_^) и полностью валидирован компилятором (/o/). Все в порядке."
    res = lint_post(text, rubric="razbor", stage="draft")
    assert not res.passed
    assert any("каомодзи" in err.lower() for err in res.errors)


def test_length_bounds_per_rubric():
    short_text = "Короткий текст."
    for rubric, (min_len, max_len) in RUBRIC_LIMITS.items():
        res = lint_post(short_text, rubric=rubric, stage="critique")
        assert not res.passed
        assert any("короткий" in err.lower() for err in res.errors)

