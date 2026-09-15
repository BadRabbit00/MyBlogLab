"""Invalid drafts must not replace saved text or advance through the pipeline."""

from unittest.mock import patch

import pytest

from src.critique import run_critique
from src.draft import run_draft
from src.generate import generate_post_content
from src.llm import LLMResponse
from src.plan import Post
from src.validation import ResponseValidationError


VALID_TEXT = "Ядро Linux проверяет доступ к файлу. " * 10


def response(text):
    return LLMResponse(text, text, 100, 10.0, "test")


@pytest.fixture
def saved_draft(tmp_path):
    post = Post(
        id="test", date="2026-09-01", slot="morning", rubric="instrument",
        title="Права доступа", thesis="Ядро проверяет доступ к файлу.", keywords=[],
        image_hint="test", status="drafted", draft_path="out/drafts/test.md",
    )
    draft = tmp_path / post.draft_path
    draft.parent.mkdir(parents=True)
    draft.write_text(VALID_TEXT, encoding="utf-8")
    return post, draft


def test_generation_supplies_lint_feedback_and_saves_only_valid_attempt(saved_draft):
    post, draft = saved_draft
    with patch("src.generate.OUT_DRAFTS_DIR", draft.parent), \
         patch("src.generate.load_history", return_value=""), \
         patch("src.generate.load_docs", return_value=""), \
         patch("src.generate.plan.advance") as advance, \
         patch("src.generate.generate", side_effect=[response("**Текст**"), response(VALID_TEXT)]) as llm:
        text, lint = generate_post_content(post, max_attempts=2)
    assert lint.passed
    assert text == VALID_TEXT
    assert "Markdown" in llm.call_args_list[1].kwargs["user_prompt"]
    assert "Текст слишком короткий" in llm.call_args_list[1].kwargs["user_prompt"]
    assert draft.read_text(encoding="utf-8") == VALID_TEXT + "\n"
    advance.assert_called_once()
    assert advance.call_args.kwargs["needs_review"] is False


@pytest.mark.parametrize("existing", [True, False])
def test_exhausted_generation_preserves_existing_draft_and_plan(saved_draft, existing):
    post, draft = saved_draft
    if not existing:
        draft.unlink()
    with patch("src.generate.OUT_DRAFTS_DIR", draft.parent), \
         patch("src.generate.load_history", return_value=""), \
         patch("src.generate.load_docs", return_value=""), \
         patch("src.generate.plan.advance") as advance, \
         patch("src.generate.generate", return_value=response(VALID_TEXT + " 中文")) as llm:
        with pytest.raises(ResponseValidationError, match="иероглифы"):
            generate_post_content(post, max_attempts=2)
    assert llm.call_count == 2
    advance.assert_not_called()
    if existing:
        assert draft.read_text(encoding="utf-8") == VALID_TEXT
    else:
        assert not draft.exists()


@pytest.mark.parametrize("content", ["中文", "**Текст**", "{{ title }}", "<root>Текст</root>"])
def test_cli_draft_cannot_save_invalid_model_response(saved_draft, content):
    post, draft = saved_draft
    with patch("src.draft.OUT_DRAFTS_DIR", draft.parent), \
         patch("src.draft.plan.get_post", return_value=post), \
         patch("src.draft.plan.advance") as advance, \
         patch("src.draft.plan.kill") as kill, \
         patch("src.draft.generate", return_value=response(VALID_TEXT + content)):
        assert not run_draft(post.id, max_attempts=1)
    advance.assert_not_called()
    kill.assert_called_once()
    assert draft.read_text(encoding="utf-8") == VALID_TEXT


@pytest.mark.parametrize("content", ["中文", "**Текст**", "{{ title }}", "<root>Текст</root>"])
def test_critique_preserves_draft_when_rewrite_is_invalid(tmp_path, saved_draft, content):
    post, draft = saved_draft
    with patch("src.critique.BASE_DIR", tmp_path), \
         patch("src.critique.plan.get_post", return_value=post), \
         patch("src.critique.plan.recent_published", return_value=[]), \
         patch("src.critique.plan.advance") as advance, \
         patch("src.critique.generate", return_value=response(VALID_TEXT + content)):
        assert not run_critique(post.id)
    assert draft.read_text(encoding="utf-8") == VALID_TEXT
    advance.assert_called_once_with(post.id, status="drafted", needs_review=True)


def test_critique_does_not_queue_on_exhausted_llm_validation(tmp_path, saved_draft):
    post, draft = saved_draft
    with patch("src.critique.BASE_DIR", tmp_path), \
         patch("src.critique.plan.get_post", return_value=post), \
         patch("src.critique.plan.recent_published", return_value=[]), \
         patch("src.critique.plan.advance") as advance, \
         patch("src.critique.generate", side_effect=ResponseValidationError(["Markdown запрещён"])):
        assert not run_critique(post.id)
    assert draft.read_text(encoding="utf-8") == VALID_TEXT
    advance.assert_called_once_with(post.id, status="drafted", needs_review=True)
