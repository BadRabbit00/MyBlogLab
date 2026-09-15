"""Unit tests for src/generate.py - RAG pipeline, context builder, and feedback loop."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.generate import load_docs, load_history, generate_post_content
from src.lint import LintResult
from src.llm import LLMResponse
from src.plan import Post


def test_load_docs_empty_when_no_prefix(tmp_path: Path):
    with patch("src.generate.DOCS_DIR", tmp_path):
        assert load_docs(None) == ""
        assert load_docs("") == ""


def test_load_docs_matches_prefix(tmp_path: Path):
    doc1 = tmp_path / "POST1-architecture.md"
    doc1.write_text("# Namespace Internals\nKernel details...", encoding="utf-8")

    doc2 = tmp_path / "POST1-extra.md"
    doc2.write_text("# Seccomp filters\nBPF code...", encoding="utf-8")

    unrelated = tmp_path / "POST2-networking.md"
    unrelated.write_text("# TCP stack...", encoding="utf-8")

    with patch("src.generate.DOCS_DIR", tmp_path):
        loaded = load_docs("POST1")
        assert "ДОПОЛНИТЕЛЬНЫЙ МАТЕРИАЛ (POST1-architecture.md)" in loaded
        assert "Kernel details..." in loaded
        assert "ДОПОЛНИТЕЛЬНЫЙ МАТЕРИАЛ (POST1-extra.md)" in loaded
        assert "POST2-networking.md" not in loaded


def test_load_history_when_empty():
    with patch("src.plan.recent_published", return_value=[]):
        history = load_history(n=10)
        assert "опубликованных постов пока нет" in history


def test_load_history_formats_posts(tmp_path: Path):
    dummy_post = Post(
        id="w1-01",
        date="2026-09-01",
        slot="morning",
        rubric="razbor",
        title="Тестовый разбор",
        thesis="Архитектура важна",
        keywords=["arch"],
        image_hint="diagram",
        status="published",
        draft_path="out/drafts/w1-01.md",
    )
    draft_file = tmp_path / "out" / "drafts" / "w1-01.md"
    draft_file.parent.mkdir(parents=True, exist_ok=True)
    draft_file.write_text("Текст ранее вышедшего поста.", encoding="utf-8")

    with patch("src.plan.recent_published", return_value=[dummy_post]), \
         patch("src.generate.BASE_DIR", tmp_path):
        history = load_history(n=5)
        assert "[w1-01] «Тестовый разбор»" in history
        assert "Архитектура важна" in history
        assert "Текст ранее вышедшего поста" in history


@patch("src.generate.generate")
@patch("src.generate.plan.advance")
def test_generate_post_content_flow(mock_advance, mock_llm_gen, tmp_path: Path):
    dummy_post = Post(
        id="w1-05",
        date="2026-09-05",
        slot="morning",
        rubric="razbor",
        title="Тест генерации",
        thesis="Тестирование ядра",
        keywords=["test", "core"],
        image_hint="hint",
        status="pending",
        doc_prefix="POST5",
    )

    sys_file = tmp_path / "SYSTEM.MD"
    sys_file.write_text("Ты — Мика.", encoding="utf-8")

    valid_post_text = (
        "Linux namespace mnt изолирует точки монтирования процессов. "
        "Флаг MS_SHARED распространяет события между пирами, тогда как MS_PRIVATE "
        "блокирует любые изменения файловой системы за пределами контейнера. "
        "В ядре подсистема idmapped mounts позволяет пробрасывать uid без пересчета прав.\n\n"
        "Когда демон systemd-udevd стартует в отдельном sandbox, попытка сменить root "
        "приводит к ошибке EPERM. Используйте pivot_root вместо chroot для полной отсечки. "
        "Любое расхождение в настройках seccomp фильтров открывает вектор для побега.\n\n"
        "Проверка изоляции выполняется через чтение mountinfo ядра. "
        "Архитектура ядра не прощает полумер при настройке приватных пространств имен."
    )
    while len(valid_post_text) < 850:
        valid_post_text += " Дополнительный анализ подтверждает надежность."

    mock_llm_gen.return_value = LLMResponse(
        raw_content=valid_post_text,
        cleaned_content=valid_post_text,
        tokens_predicted=250,
        duration_ms=450.0,
        model_name="gemma-4",
    )

    out_drafts = tmp_path / "out" / "drafts"

    with patch("src.generate.SYSTEM_PROMPT_PATH", sys_file), \
         patch("src.generate.OUT_DRAFTS_DIR", out_drafts), \
         patch("src.generate.DOCS_DIR", tmp_path / "docs"):

        text, lint_res = generate_post_content(
            post=dummy_post,
            user_feedback="Сделай жестче",
            previous_draft="Старый черновик",
            max_attempts=1,
        )

        assert text == valid_post_text
        assert lint_res.passed
        assert mock_advance.called
        assert (out_drafts / "w1-05.md").exists()
        saved_content = (out_drafts / "w1-05.md").read_text(encoding="utf-8")
        assert valid_post_text in saved_content
