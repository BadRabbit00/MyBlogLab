"""Token isolation, plain-text validation, and publication."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.plan import Post, Plan
from src.publish import (
    get_bot_token,
    run_publish,
)
from src.validation import ResponseValidationError


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


def test_get_bot_token_from_read_only_secret_file(tmp_path, monkeypatch):
    token_file = tmp_path / "telegram_bot_token"
    token_file.write_text("dummy-secret\n", encoding="utf-8")
    token_file.chmod(0o400)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_file))
    with patch("src.publish.os.chmod") as chmod:
        assert get_bot_token() == "dummy-secret"
    chmod.assert_not_called()


def test_empty_secret_file_is_rejected(tmp_path, monkeypatch):
    token_file = tmp_path / "telegram_bot_token"
    token_file.write_text(" \n", encoding="utf-8")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_file))
    with pytest.raises(ValueError, match="empty"):
        get_bot_token()


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


@pytest.fixture
def queued_post(tmp_path):
    post = Post(
        id="w1-01", date="2026-09-01", slot="morning", rubric="instrument",
        title="Тест", thesis="Тезис", keywords=[], image_hint="hint", status="queued",
        draft_path="out/drafts/w1-01.md",
    )
    draft = tmp_path / post.draft_path
    draft.parent.mkdir(parents=True)
    draft.write_text("Проверь x < y, y > 0 и флаг --help. Символ & допустим.", encoding="utf-8")
    image = tmp_path / "out/images/w1-01.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"test image")
    return post, draft


@pytest.mark.parametrize("text", ["中文", "**Текст**", "{{ title }}", "<post>Текст</post>"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_publish_rejects_invalid_saved_draft_before_side_effects(tmp_path, queued_post, text, dry_run):
    post, draft = queued_post
    draft.write_text(text, encoding="utf-8")
    with patch("src.publish.BASE_DIR", tmp_path), \
         patch("src.publish.plan.get_post", return_value=post), \
         patch("src.publish.plan.advance") as advance, \
         patch("src.publish.generate_card") as card, \
         patch("src.publish.get_bot_token") as token, \
         patch("src.publish.httpx.Client") as client:
        with pytest.raises(ResponseValidationError):
            run_publish(post.id, dry_run=dry_run)
    advance.assert_not_called()
    card.assert_not_called()
    token.assert_not_called()
    client.assert_not_called()


def test_publish_sends_original_plain_text_without_parse_mode(tmp_path, queued_post):
    post, draft = queued_post
    content_plan = Plan(meta={"channel": "@test"}, posts=[post], raw_yaml={})
    with patch("src.publish.BASE_DIR", tmp_path), \
         patch("src.publish.plan.get_post", return_value=post), \
         patch("src.publish.plan.load", return_value=content_plan), \
         patch("src.publish.plan.advance") as advance, \
         patch("src.publish.get_bot_token", return_value="test-token"), \
         patch("src.publish.httpx.Client") as client_class:
        client = client_class.return_value.__enter__.return_value
        client.post.return_value.json.return_value = {"ok": True, "result": {"message_id": 42}}
        assert run_publish(post.id)
    data = client.post.call_args.kwargs["data"]
    assert data["caption"] == draft.read_text(encoding="utf-8")
    assert "parse_mode" not in data
    assert advance.call_args.kwargs["status"] == "published"
