"""Post content linter and validator for blog-agent.

Enforces length limits, detects banned LLM clichés, validates persona boundaries,
and counts emojis/kaomojis.
"""

from dataclasses import dataclass, field
import re

BANNED_PATTERNS: list[tuple[str, str]] = [
    (r"\bважно отметить\b", "Штамп 'важно отметить'"),
    (r"\bстоит отметить\b", "Штамп 'стоит отметить'"),
    (r"\bв современном мире\b", "Штамп 'в современном мире'"),
    (r"\bиграет ключевую роль\b", "Штамп 'играет ключевую роль'"),
    (r"\bне только.{1,40}но и\b", "Конструкция 'не только... но и'"),
    (r"\bдавайте разбер[её]мся\b", "Зачин 'давайте разберемся'"),
    (r"\bитак,", "Затычка 'итак,'"),
    (r"\bв заключение\b", "Штамп 'в заключение'"),
    (r"—.{1,60}—", "Вставка в длинных тире"),
    (r"\b(Итог|Вывод):", "Подзаголовок-затычка 'Итог/Вывод:'"),
]

GREETING_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:привет|здравствуйте|добрый день|хай|доброе утро|добрый вечер|хеллоу)[\s,!\.]",
    flags=re.IGNORECASE,
)

GOODBYE_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:пока|до встречи|до свидания|увидимся|до скорого|подписывайтесь|ставьте лайки)[\s!\.]*$",
    flags=re.IGNORECASE,
)

DIMINUTIVE_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:контейнерчик|скриптик|демончик|файлик|серверок|сокетик|базка|базочка|проксик|докерик)[а-я]*\b",
    flags=re.IGNORECASE,
)

EMOJI_PATTERN: re.Pattern[str] = re.compile(
    r"[\U0001F1E0-\U0001F1FF"  # flags
    r"\U0001F300-\U0001F5FF"  # symbols & pictographs
    r"\U0001F600-\U0001F64F"  # emoticons
    r"\U0001F680-\U0001F6FF"  # transport & map
    r"\U0001F700-\U0001F77F"  # alchemical
    r"\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    r"\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    r"\U0001FA00-\U0001FA6F"  # Chess Symbols
    r"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    r"\U00002600-\U000026FF"  # Misc Symbols (lightning, warnings, gears)
    r"\U00002702-\U000027B0"  # Dingbats
    r"]",
    flags=re.UNICODE,
)

KAOMOJI_PATTERN: re.Pattern[str] = re.compile(
    r"(\([^\w\s]{1,5}[\w\s]*[^\w\s]{1,5}\)|[\\/][oO_][\\/]|¯\\_\(ツ\)_/¯|\(｡[♥•‿]｡\))"
)

RUBRIC_LIMITS: dict[str, tuple[int, int]] = {
    "razbor": (800, 1000),
    "keys": (700, 1000),
    "instrument": (300, 500),
    "dnevnik": (200, 3000),
}


@dataclass
class LintResult:
    """Outcome of lint checks for a generated post."""

    passed: bool
    char_count: int
    min_len: int
    max_len: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    banned_matches: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Return formatted summary of findings."""
        if self.passed:
            return f"OK: {self.char_count} chars (target {self.min_len}-{self.max_len})"
        issues = "; ".join(self.errors)
        return f"FAILED ({self.char_count} chars): {issues}"


def lint_post(text: str, rubric: str, stage: str = "publish") -> LintResult:
    """Validate post text against style, safety, and formatting constraints.

    Stage can be 'draft', 'critique', or 'publish'.
    """
    cleaned = text.strip()
    char_count = len(cleaned)
    nominal_min, nominal_max = RUBRIC_LIMITS.get(rubric, (300, 1000))

    # For draft stage, reject grossly oversized responses (> 1.25x nominal)
    effective_max = int(nominal_max * 1.25) if stage == "draft" else nominal_max
    effective_min = int(nominal_min * 0.85) if stage == "draft" else nominal_min

    errors: list[str] = []
    warnings: list[str] = []
    banned_matches: list[str] = []

    # 1. Length validation
    if char_count < effective_min:
        errors.append(f"Текст слишком короткий: {char_count} знаков (минимум {nominal_min})")
    elif char_count > effective_max:
        errors.append(f"Текст превышает лимит: {char_count} знаков (максимум {effective_max})")

    # 2. Banned phrases and clichés
    for pattern_str, label in BANNED_PATTERNS:
        matches = re.findall(pattern_str, cleaned, flags=re.IGNORECASE)
        if matches:
            errors.append(f"{label} (найдено {len(matches)} раз)")
            banned_matches.append(label)

    # 3. Greetings check
    first_line = cleaned.split("\n", 1)[0].strip()
    if GREETING_PATTERN.search(first_line):
        errors.append("Обнаружено запрещенное приветствие в начале поста")

    # 4. Goodbye / call-to-action check
    if GOODBYE_PATTERN.search(cleaned):
        errors.append("Обнаружено запрещенное прощание или призыв подписаться")

    # 5. Ending question check
    last_paragraph = cleaned.split("\n\n")[-1].strip()
    if last_paragraph.endswith("?") or re.search(r"\bчто думаете\b|\bа как вы\b|\bа вы\b\?", last_paragraph, flags=re.IGNORECASE):
        errors.append("Запрещен вопрос к читателю в финале поста")

    # 6. Diminutive technical terms
    dim_matches = DIMINUTIVE_PATTERN.findall(cleaned)
    if dim_matches:
        errors.append(f"Уменьшительные формы терминов: {', '.join(set(dim_matches))}")

    # 7. Emoji count (max 2)
    emojis = EMOJI_PATTERN.findall(cleaned)
    if len(emojis) > 2:
        errors.append(f"Превышен лимит эмодзи: {len(emojis)} (максимум 2)")

    # 8. Kaomoji count (max 1)
    kaomojis = KAOMOJI_PATTERN.findall(cleaned)
    if len(kaomojis) > 1:
        errors.append(f"Превышен лимит каомодзи: {len(kaomojis)} (максимум 1)")

    passed = len(errors) == 0
    return LintResult(
        passed=passed,
        char_count=char_count,
        min_len=nominal_min,
        max_len=nominal_max,
        errors=errors,
        warnings=warnings,
        banned_matches=banned_matches,
    )
