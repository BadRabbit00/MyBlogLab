"""Unit tests for src/bot.py - Keyboards, navigation, and validation logic."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.bot import (
    find_post_by_tag_or_number,
    make_review_keyboard,
    make_photo_keyboard,
    render_main_menu,
    render_list_page,
    process_add_doc_post_number,
    PostReviewStates,
)
from src.plan import Post, Plan


@pytest.fixture
def mock_plan():
    p1 = Post(
        id="w1-01",
        date="2026-09-01",
        slot="morning",
        rubric="razbor",
        title="Пост 1",
        thesis="Тезис 1",
        keywords=["k1"],
        image_hint="h1",
        status="pending",
        doc_prefix="POST1",
    )
    p2 = Post(
        id="w1-02",
        date="2026-09-02",
        slot="morning",
        rubric="keys",
        title="Пост 2",
        thesis="Тезис 2",
        keywords=["k2"],
        image_hint="h2",
        status="drafted",
        doc_prefix="POST2",
    )
    p3 = Post(
        id="w1-03",
        date="2026-09-03",
        slot="morning",
        rubric="instrument",
        title="Пост 3",
        thesis="Тезис 3",
        keywords=["k3"],
        image_hint="h3",
        status="published",
        doc_prefix="POST3",
    )
    return Plan(meta={"channel": "@test_channel"}, posts=[p1, p2, p3], raw_yaml={})


def test_find_post_by_tag_or_number_exact_id(mock_plan):
    with patch("src.bot.plan.load", return_value=mock_plan):
        post = find_post_by_tag_or_number("w1-01")
        assert post is not None
        assert post.id == "w1-01"


def test_find_post_by_tag_or_number_tag(mock_plan):
    with patch("src.bot.plan.load", return_value=mock_plan):
        post1 = find_post_by_tag_or_number("POST2")
        assert post1 is not None
        assert post1.id == "w1-02"

        post2 = find_post_by_tag_or_number("post2")
        assert post2 is not None
        assert post2.id == "w1-02"


def test_find_post_by_tag_or_number_numeric(mock_plan):
    with patch("src.bot.plan.load", return_value=mock_plan):
        post = find_post_by_tag_or_number("3")
        assert post is not None
        assert post.id == "w1-03"


def test_find_post_by_tag_or_number_not_found(mock_plan):
    with patch("src.bot.plan.load", return_value=mock_plan):
        post = find_post_by_tag_or_number("w99-99")
        assert post is None


def test_make_review_keyboard():
    kb = make_review_keyboard("w1-01")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "approve:w1-01" in callbacks
    assert "reject:w1-01" in callbacks
    assert "card:w1-01" in callbacks
    assert "menu:main" in callbacks


def test_make_photo_keyboard():
    kb = make_photo_keyboard("w1-01")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "pubcard:w1-01" in callbacks
    assert "menu:main" in callbacks


def test_render_main_menu(mock_plan):
    with patch("src.bot.plan.load", return_value=mock_plan), \
         patch("src.bot.plan.get_stats", return_value={"total": 3, "pending": 1, "drafted": 1, "queued": 0, "published": 1}), \
         patch("src.bot.plan.next_for", return_value=mock_plan.posts[0]):

        text, kb = render_main_menu()
        assert "@test_channel" in text
        assert "Всего постов: <b>3</b>" in text
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:posts" in callbacks
        assert "menu:generate" in callbacks
        assert "menu:add_doc" in callbacks


def test_render_posts_page(mock_plan):
    with patch("src.bot.plan.load", return_value=mock_plan):
        text, kb = render_list_page(page=0)
        assert "Контент-план" in text
        assert "w1-01" in text.lower()
        assert "w1-02" in text.lower()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:main" in callbacks
        assert "gen_req:w1-01" in callbacks


@pytest.mark.asyncio
async def test_process_add_doc_post_number_rejects_non_pending(mock_plan):
    # w1-02 has status="drafted"
    with patch("src.bot.plan.load", return_value=mock_plan):
        message = AsyncMock()
        message.text = "POST2"
        state = AsyncMock()

        await process_add_doc_post_number(message, state)

        # Ensure error message was sent and state was cleared
        assert message.answer.called
        sent_text = message.answer.call_args[0][0]
        assert "уже обработан" in sent_text
        assert "pending" in sent_text
        assert state.clear.called


@pytest.mark.asyncio
async def test_process_add_doc_post_number_accepts_pending(mock_plan):
    # w1-01 has status="pending"
    with patch("src.bot.plan.load", return_value=mock_plan):
        message = AsyncMock()
        message.text = "POST1"
        state = AsyncMock()

        await process_add_doc_post_number(message, state)

        assert message.answer.called
        sent_text = message.answer.call_args[0][0]
        assert "Выбран пост: #W1-01" in sent_text
        assert state.set_state.called
        assert state.update_data.called
