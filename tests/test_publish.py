"""Unit tests for src/publish.py - Token isolation, HTML entity escaping, and publication."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.plan import Post, Plan
from src.publish import (
    get_bot_token,
    markdown_to_telegram_html,
    run_publish,
)


def test_get_bot_token_from_env():
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123456:ABC-DEF"}):
        assert get_bot_token() == "123456:ABC-DEF"

    with patch.dict(os.environ, {"BOT_TOKEN": "789012:GHI-JKL"}, clear=True):
        assert get_bot_token() == "789012:GHI-JKL"


def test_get_bot_token_from_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=file_token_secret\nOTHER_VAR=123", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True), \
         patch("src.publish.ENV_FILE", env_file):
        assert get_bot_token() == "file_token_secret"


def test_get_bot_token_from_token_file(tmp_path: Path):
    token_file = tmp_path / ".tg_bot_token"
    token_file.write_text("file_token_0600", encoding="utf-8")
    token_file.chmod(0o644)  # insecure

    with patch.dict(os.environ, {}, clear=True), \
         patch("src.publish.ENV_FILE", tmp_path / "non_existent.env"), \
         patch("src.publish.TOKEN_PATHS", [token_file]):
        token = get_bot_token()
        assert token == "file_token_0600"
        # Verify permissions were hardened to 0600
        mode = oct(token_file.stat().st_mode & 0o777)
        assert mode == "0o600"


def test_get_bot_token_missing_raises(tmp_path: Path):
    with patch.dict(os.environ, {}, clear=True), \
         patch("src.publish.ENV_FILE", tmp_path / "non_existent.env"), \
         patch("src.publish.TOKEN_PATHS", [tmp_path / "token_missing"]):
        with pytest.raises(FileNotFoundError):
            get_bot_token()


def test_markdown_to_telegram_html():
    raw = (
        "Заголовок с **жирным** и *курсивным* текстом.\n"
        "Специальные символы: <script> & 'quotes'\n\n"
        "Инлайн код: `sudo iptables -L`.\n"
        "```python\ndef test():\n    return x < y & True\n```"
    )
    result = markdown_to_telegram_html(raw)

    assert "<b>жирным</b>" in result
    assert "<i>курсивным</i>" in result
    assert "&lt;script&gt;" in result
    assert "<code>sudo iptables -L</code>" in result
    assert "<pre><code>def test():\n    return x &lt; y &amp; True</code></pre>" in result


def test_run_publish_dry_run(tmp_path: Path):
    dummy_post = Post(
        id="w1-01",
        date="2026-09-01",
        slot="morning",
        rubric="razbor",
        title="Тестовый разбор",
        thesis="Тезис",
        keywords=["k1"],
        image_hint="hint",
        status="queued",
        draft_path="out/drafts/w1-01.md",
    )

    draft_file = tmp_path / "out" / "drafts" / "w1-01.md"
    draft_file.parent.mkdir(parents=True, exist_ok=True)
    draft_file.write_text("Готовый пост для публикации.", encoding="utf-8")

    img_file = tmp_path / "out" / "images" / "w1-01.png"
    img_file.parent.mkdir(parents=True, exist_ok=True)
    img_file.write_bytes(b"dummy_png_bytes")

    dummy_plan = Plan(meta={"channel": "@test_channel"}, posts=[dummy_post], raw_yaml={})

    with patch("src.publish.BASE_DIR", tmp_path), \
         patch("src.publish.plan.get_post", return_value=dummy_post), \
         patch("src.publish.plan.load", return_value=dummy_plan):

        success = run_publish("w1-01", dry_run=True)
        assert success is True


def test_run_publish_caption_limit_exceeded(tmp_path: Path):
    dummy_post = Post(
        id="w1-01",
        date="2026-09-01",
        slot="morning",
        rubric="razbor",
        title="Тест",
        thesis="Тезис",
        keywords=["k1"],
        image_hint="hint",
        status="queued",
        draft_path="out/drafts/w1-01.md",
    )

    draft_file = tmp_path / "out" / "drafts" / "w1-01.md"
    draft_file.parent.mkdir(parents=True, exist_ok=True)
    # Draft exceeding 1024 characters
    draft_file.write_text("A" * 1050, encoding="utf-8")

    img_file = tmp_path / "out" / "images" / "w1-01.png"
    img_file.parent.mkdir(parents=True, exist_ok=True)
    img_file.write_bytes(b"dummy_png_bytes")

    with patch("src.publish.BASE_DIR", tmp_path), \
         patch("src.publish.plan.get_post", return_value=dummy_post):
        with pytest.raises(ValueError, match="Telegram caption limit exceeded"):
            run_publish("w1-01", dry_run=True)
