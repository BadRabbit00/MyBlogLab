"""Critique and refinement module for blog-agent (Step 2: drafted -> queued).

Analyses draft with previous channel history and targeted linter feedback,
activates Gemma 4 deep thinking mode, refines the draft, and queues it for review/publishing.
"""

from pathlib import Path
from typing import Optional

from src.lint import RUBRIC_LIMITS, lint_post
from src.llm import generate
from src.validation import ResponseValidationError, require_plain_text
import src.plan as plan

from src.paths import APP_DIR, DATA_DIR

BASE_DIR: Path = DATA_DIR
SYSTEM_PROMPT_PATH: Path = APP_DIR / "SYSTEM.MD"
CRITIQUE_TEMPLATE_PATH: Path = APP_DIR / "prompts" / "critique.md"
OUT_DRAFTS_DIR: Path = BASE_DIR / "out" / "drafts"


def _read_file_text(path: Path) -> str:
    """Read text file safely."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def run_critique(post_id: Optional[str] = None) -> bool:
    """Critique and refine a drafted post, transitioning it to 'queued'."""
    post = plan.get_post(post_id) if post_id else plan.next_for("critique")
    if not post:
        return False

    draft_path = BASE_DIR / (post.draft_path or f"out/drafts/{post.id}.md")
    if not draft_path.exists():
        plan.kill(post.id, f"Draft file not found at {draft_path}")
        return False

    draft_text = _read_file_text(draft_path)
    system_prompt = _read_file_text(SYSTEM_PROMPT_PATH)
    critique_template = _read_file_text(CRITIQUE_TEMPLATE_PATH)
    min_len, max_len = RUBRIC_LIMITS.get(post.rubric, (700, 1000))

    # 1. Gather recent published posts to detect duplication
    recent = plan.recent_published(n=10)
    if recent:
        published_items: list[str] = []
        for p in recent:
            published_items.append(f"- [{p.id}] «{p.title}»: {p.thesis}")
        published_context = "Ранее опубликованные посты канала:\n" + "\n".join(published_items)
    else:
        published_context = "Ранее опубликованных постов нет (это начало ведения канала)."

    # 2. Run preliminary lint on current draft
    initial_lint = lint_post(draft_text, post.rubric, stage="draft")
    if initial_lint.errors:
        lint_context = "Замечания линтера к текущему черновику:\n- " + "\n- ".join(initial_lint.errors)
    else:
        lint_context = "Линтер не выявил критических замечаний к стилю, но требуется вычитка и полировка."

    user_prompt = critique_template.format(
        title=post.title,
        rubric=post.rubric,
        draft=draft_text,
        published_context=published_context,
        lint_context=lint_context,
        min_len=min_len,
        max_len=max_len,
    )

    try:
        response = generate(
            post_id=post.id,
            step="critique",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            enable_thinking=True,  # Gemma 4 thinking mode is engaged!
            preset="critique",
            custom_params={"n_predict": 3072},
        )
        refined_text = response.cleaned_content
        require_plain_text(refined_text)

        # 3. Post-critique lint check
        final_lint = lint_post(refined_text, post.rubric, stage="critique")

        # Persist updated content
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(refined_text + "\n")

        if final_lint.passed:
            plan.advance(post.id, status="queued", needs_review=False)
        else:
            # Minor issues remain after critique: queue with needs_review flag
            plan.advance(post.id, status="queued", needs_review=True)

        return True

    except ResponseValidationError:
        # Keep the saved draft and its current status when the rewrite is invalid.
        plan.advance(post.id, status=post.status, needs_review=True)
        return False
    except Exception as exc:
        # If critique fails due to LLM error, keep existing draft but mark needs_review
        plan.advance(post.id, status="queued", needs_review=True)
        return False


def run_all_drafted() -> int:
    """Critique all drafted posts."""
    drafted_posts = plan.all_for("critique")
    success_count = 0
    for post in drafted_posts:
        if run_critique(post.id):
            success_count += 1
    return success_count
