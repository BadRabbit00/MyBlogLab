"""Draft generation module for blog-agent (Step 1: pending -> drafted).

Renders persona and rubric instructions, queries Gemma 4, validates length and style,
and persists generated drafts to out/drafts/{id}.md.
"""

from pathlib import Path
from typing import Optional

from src.lint import RUBRIC_LIMITS, lint_post
from src.llm import generate
import src.plan as plan

BASE_DIR: Path = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH: Path = BASE_DIR / "SYSTEM.MD"
DRAFT_TEMPLATE_PATH: Path = BASE_DIR / "prompts" / "draft.md"
STYLE_PATH: Path = BASE_DIR / "prompts" / "style.md"
OUT_DRAFTS_DIR: Path = BASE_DIR / "out" / "drafts"


def _read_file_text(path: Path) -> str:
    """Read text file safely."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def run_draft(post_id: Optional[str] = None, max_attempts: int = 3) -> bool:
    """Generate draft for the specified post or the next pending post.

    Returns True if draft succeeded and advanced to 'drafted', False if killed or skipped.
    """
    post = plan.get_post(post_id) if post_id else plan.next_for("draft")
    if not post:
        return False

    if post.rubric == "dnevnik":
        return False

    system_prompt = _read_file_text(SYSTEM_PROMPT_PATH)
    draft_template = _read_file_text(DRAFT_TEMPLATE_PATH)
    min_len, max_len = RUBRIC_LIMITS.get(post.rubric, (700, 1000))
    token_limit = int(max_len / 2.6)  # Gemma 4 Russian token ratio is ~3.5-4.0 chars/token

    last_errors: list[str] = []

    for attempt in range(1, max_attempts + 1):
        retry_feedback = ""
        if last_errors:
            errors_str = "; ".join(last_errors)
            retry_feedback = f"\n\nВАЖНО (предыдущая попытка отклонена): {errors_str}. Исправь это и строго держись лимита {min_len}-{max_len} знаков!"

        user_prompt = draft_template.format(
            rubric=post.rubric,
            title=post.title,
            thesis=post.thesis,
            keywords=", ".join(post.keywords),
            min_len=min_len,
            max_len=max_len,
            retry_feedback=retry_feedback,
        )

        try:
            response = generate(
                post_id=post.id,
                step=f"draft_attempt_{attempt}",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                enable_thinking=False,
                preset="draft",
                custom_params={"n_predict": token_limit},
            )
            draft_text = response.cleaned_content

            lint_res = lint_post(draft_text, post.rubric, stage="draft")
            if lint_res.passed:
                # Success! Persist to out/drafts/{id}.md
                OUT_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
                draft_file = OUT_DRAFTS_DIR / f"{post.id}.md"
                with open(draft_file, "w", encoding="utf-8") as f:
                    f.write(draft_text + "\n")

                rel_draft_path = f"out/drafts/{post.id}.md"
                plan.advance(post.id, status="drafted", draft_path=rel_draft_path)
                return True

            last_errors = lint_res.errors

        except Exception as exc:
            last_errors = [str(exc)]

    # All attempts failed: kill the post with reason
    reason_msg = f"Draft failed after {max_attempts} attempts: {'; '.join(last_errors)}"
    plan.kill(post.id, reason_msg)
    return False


def run_all_pending() -> int:
    """Generate drafts for all pending posts."""
    pending_posts = plan.all_for("draft")
    success_count = 0
    for post in pending_posts:
        if run_draft(post.id):
            success_count += 1
    return success_count
