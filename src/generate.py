"""Content generation engine with RAG support (docs/ + post history + feedback loop).

Handles context compilation:
1. Channel post history.
2. Domain documentation files from ./docs/ matching post's doc_prefix.
3. User rejection comments and iterative refinement.
"""

from pathlib import Path
from typing import Optional

from src.lint import RUBRIC_LIMITS, LintResult, lint_post
from src.llm import generate
from src.logger import get_logger
import src.plan as plan

logger = get_logger("generate")

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DOCS_DIR: Path = BASE_DIR / "docs"
SYSTEM_PROMPT_PATH: Path = BASE_DIR / "SYSTEM.MD"
OUT_DRAFTS_DIR: Path = BASE_DIR / "out" / "drafts"


def _read_file_text(path: Path) -> str:
    """Read text file safely."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_docs(doc_prefix: Optional[str]) -> str:
    """Load all markdown articles in docs/ matching the specified doc_prefix."""
    if not doc_prefix or not DOCS_DIR.exists():
        return ""

    matched_files = sorted(DOCS_DIR.glob(f"{doc_prefix}*.md"))
    if not matched_files:
        return ""

    sections: list[str] = []
    for file_path in matched_files:
        content = _read_file_text(file_path)
        sections.append(
            f"--- ДОПОЛНИТЕЛЬНЫЙ МАТЕРИАЛ ({file_path.name}) ---\n{content}\n"
        )

    return "\n".join(sections)


def load_history(n: int = 15) -> str:
    """Compile recent channel posts to maintain narrative continuity and avoid repetition."""
    published = plan.recent_published(n=n)
    if not published:
        return "История канала: опубликованных постов пока нет (первая неделя)."

    history_items: list[str] = []
    for p in published:
        draft_file = BASE_DIR / (p.draft_path or f"out/drafts/{p.id}.md")
        snippet = ""
        if draft_file.exists():
            snippet = _read_file_text(draft_file)[:250] + "..."
        history_items.append(
            f"- [{p.id}] «{p.title}» ({p.rubric})\n  Тезис: {p.thesis}\n  Фрагмент: {snippet}"
        )

    return "Ранее вышедшие посты канала:\n" + "\n\n".join(history_items)


def generate_post_content(
    post: plan.Post,
    user_feedback: Optional[str] = None,
    previous_draft: Optional[str] = None,
    max_attempts: int = 2,
) -> tuple[str, LintResult]:
    """Generate or regenerate post text with Gemma 4 using docs, history, and feedback.

    Returns tuple of (cleaned_text, lint_result).
    """
    system_prompt = _read_file_text(SYSTEM_PROMPT_PATH)
    min_len, max_len = RUBRIC_LIMITS.get(post.rubric, (700, 1000))
    token_limit = int(max_len / 2.5)

    docs_context = load_docs(post.doc_prefix)
    history_context = load_history(n=15)

    prompt_parts: list[str] = [
        f"Рубрика: {post.rubric}",
        f"Заголовок: {post.title}",
        f"Тезис для раскрытия: {post.thesis}",
        f"Опорные понятия: {', '.join(post.keywords)}",
        f"Префикс документации: {post.doc_prefix or 'нет'}",
        "",
        "=== ИСТОРИЯ КАНАЛА ===",
        history_context,
    ]

    if docs_context:
        prompt_parts.extend([
            "",
            "=== ДОПОЛНИТЕЛЬНЫЕ МАТЕРИАЛЫ И СТАТЬИ ПО ТЕМЕ (ИЗ ПАПКИ DOCS) ===",
            docs_context,
        ])

    prompt_parts.extend([
        "",
        "=== ТРЕБОВАНИЯ К ПОСТУ ===",
        f"- Формат: ровно 3–4 коротких абзаца (в сумме 6–8 предложений, 100–130 слов).",
        f"- Длина строго от {min_len} до {max_len} символов (с пробелами). Не превышай {max_len}!",
        "- Раскрой именно указанный тезис с опорой на предоставленные материалы.",
        "- Первое предложение — жесткий факт или утверждение. Никаких приветствий и вводных слов.",
        "- Приведи один конкретный технический пример (команда, флаг, системный вызов, уязвимость или архитектурный механизм).",
        "- Характер Мики: не более двух коротких ремарок в скобках.",
        "- Финал — констатация факта. Без риторических вопросов к читателю в конце.",
        "- Без штампов («важно отметить», «в современном мире», «давайте разберемся»).",
    ])

    if previous_draft and user_feedback:
        prompt_parts.extend([
            "",
            "=== ОБРАТНАЯ СВЯЗЬ ПО ПРЕДЫДУЩЕЙ ВЕРСИИ ===",
            "Твой предыдущий черновик:",
            f'"""\n{previous_draft.strip()}\n"""',
            f"Твой предыдущий пост не понравился пользователю, вот его комментарий: {user_feedback.strip()}",
            "Перепиши пост заново с учетом замечания пользователя!",
        ])

    prompt_parts.append(
        "\nВерни ТОЛЬКО готовый текст поста для публикации. Без заголовка, без кавычек и без пояснений."
    )

    user_prompt = "\n".join(prompt_parts)
    best_text = ""
    best_lint = LintResult(passed=False, char_count=0, min_len=min_len, max_len=max_len, errors=["Не генерировалось"])

    logger.info(f"Generating content for post #{post.id} ({post.rubric}) - Title: '{post.title}'")
    if user_feedback:
        logger.info(f"Incorporating user feedback into prompt: '{user_feedback}'")

    for attempt in range(1, max_attempts + 1):
        step_name = f"bot_regen_{attempt}" if user_feedback else f"bot_gen_{attempt}"
        logger.debug(f"LLM generation attempt {attempt}/{max_attempts} (step={step_name})")
        response = generate(
            post_id=post.id,
            step=step_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            enable_thinking=False,
            preset="draft",
            custom_params={"n_predict": token_limit},
        )
        text = response.cleaned_content
        lint_res = lint_post(text, post.rubric, stage="draft")

        best_text = text
        best_lint = lint_res
        if lint_res.passed:
            break

    # Persist draft to out/drafts/{id}.md
    OUT_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_file = OUT_DRAFTS_DIR / f"{post.id}.md"
    with open(draft_file, "w", encoding="utf-8") as f:
        f.write(best_text + "\n")

    plan.advance(
        post.id,
        status="drafted",
        draft_path=f"out/drafts/{post.id}.md",
        needs_review=(not best_lint.passed),
    )

    return best_text, best_lint
