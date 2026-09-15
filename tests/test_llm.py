"""Unit tests for src/llm.py - Token formatting, sanitization, and client."""

from unittest.mock import MagicMock, patch
import pytest
from pathlib import Path
import json

from src.llm import (
    format_gemma4_prompt,
    sanitize_response,
    generate,
    log_interaction,
    LLMResponse,
)


def test_format_gemma4_prompt_without_thinking():
    sys = "You are Mika."
    user = "Write a post."
    prompt = format_gemma4_prompt(sys, user, enable_thinking=False)

    assert prompt.startswith("<|turn>system\nYou are Mika.<turn|>\n")
    assert "<|turn>user\nWrite a post.<turn|>\n" in prompt
    assert prompt.endswith("<|turn>model\n")
    assert "<|think|>" not in prompt


def test_format_gemma4_prompt_with_thinking():
    sys = "You are Mika."
    user = "Review this draft."
    prompt = format_gemma4_prompt(sys, user, enable_thinking=True)

    assert "<|turn>system\n<|think|>\nYou are Mika.<turn|>\n" in prompt
    assert "<|turn>user\nReview this draft.<turn|>\n" in prompt
    assert prompt.endswith("<|turn>model\n")


def test_sanitize_response_normal():
    raw = "Готовый текст поста без лишних тегов."
    cleaned = sanitize_response(raw)
    assert cleaned == "Готовый текст поста без лишних тегов."


def test_sanitize_response_with_thinking_channel():
    raw = (
        "<|channel>thought\n"
        "Need to analyze namespace isolation and avoid cliches.\n"
        "<channel|>\n"
        "Чистый текст поста после размышлений."
    )
    cleaned = sanitize_response(raw)
    assert cleaned == "Чистый текст поста после размышлений."
    assert "thought" not in cleaned


def test_sanitize_response_cutoff_inside_thought():
    # Model reached token limit before closing thought channel
    raw = "<|channel>thought\nI am still thinking and then cutoff occurs..."
    with pytest.raises(ValueError, match="cut off inside thinking channel"):
        sanitize_response(raw)


def test_sanitize_response_strips_markdown_fences():
    raw = "```markdown\nТекст внутри блоков кода\n```"
    cleaned = sanitize_response(raw)
    assert cleaned == "Текст внутри блоков кода"


def test_sanitize_response_strips_conversational_prefixes():
    raw = "Вот готовый пост:\nАрхитектура ядра Linux построена на модулях."
    cleaned = sanitize_response(raw)
    assert cleaned == "Архитектура ядра Linux построена на модулях."

    raw2 = "Черновик:\nСистемные вызовы epoll."
    cleaned2 = sanitize_response(raw2)
    assert cleaned2 == "Системные вызовы epoll."


def test_log_interaction(tmp_path: Path):
    with patch("src.llm.LOGS_DIR", tmp_path):
        log_interaction(
            post_id="test-01",
            step="draft",
            prompt="Prompt content",
            response_data={"content": "result"},
            cleaned_output="result",
            duration_ms=123.45,
        )

        log_file = tmp_path / "test-01.jsonl"
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["post_id"] == "test-01"
        assert data["step"] == "draft"
        assert data["cleaned_output"] == "result"


@patch("src.llm.httpx.Client")
def test_generate_success(mock_client_class, tmp_path: Path):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "content": "<|channel>thought\nPlan text\n<channel|>\nГотовый пост.",
        "tokens_predicted": 42,
        "model": "gemma-4",
    }
    mock_resp.raise_for_status.return_value = None
    mock_client.post.return_value = mock_resp

    with patch("src.llm.LOGS_DIR", tmp_path):
        res = generate(
            post_id="p-01",
            step="draft",
            system_prompt="System",
            user_prompt="User",
            max_retries=1,
        )

    assert res.cleaned_content == "Готовый пост."
    assert res.tokens_predicted == 42
