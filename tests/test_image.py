"""Unit tests for src/image.py - SVG card generation and styling."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.image import (
    _wrap_title,
    _render_title_tspans,
    generate_card,
    RUBRIC_COLORS,
    RUBRIC_LABELS,
    SHAPES,
)
from src.plan import Post


def test_wrap_title_short():
    title = "Короткий заголовок"
    lines = _wrap_title(title, max_chars_per_line=30)
    assert lines == ["Короткий заголовок"]


def test_wrap_title_multiline():
    title = "Архитектура ядра Linux и детальный разбор изоляции пространств имен mnt"
    lines = _wrap_title(title, max_chars_per_line=25)
    assert len(lines) > 1
    for line in lines:
        assert len(line) <= 35  # reasonable word wrap bounds


def test_wrap_title_caps_at_4_lines():
    title = "один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать"
    lines = _wrap_title(title, max_chars_per_line=10)
    assert len(lines) <= 4


def test_render_title_tspans_escapes_xml():
    lines = ["Тест <xml> & 'кавычки'"]
    tspans = _render_title_tspans(lines)
    assert "&lt;xml&gt;" in tspans
    assert "&amp;" in tspans
    assert "<tspan" in tspans


def test_rubric_palettes_configured():
    for rubric in ["razbor", "keys", "instrument", "dnevnik"]:
        assert rubric in RUBRIC_COLORS
        assert rubric in RUBRIC_LABELS
        assert RUBRIC_COLORS[rubric].startswith("#")


@patch("src.image.subprocess.run")
def test_generate_card_mock_resvg(mock_subproc, tmp_path: Path):
    dummy_post = Post(
        id="w1-01",
        date="2026-09-01",
        slot="morning",
        rubric="razbor",
        title="Тестовый заголовок разбора",
        thesis="Тезис",
        keywords=["k1"],
        image_hint="hint",
        status="drafted",
    )

    template_svg = tmp_path / "card.svg"
    template_svg.write_text(
        "<svg>{{ACCENT_COLOR}} {{RUBRIC_LABEL}} {{POST_ID}} {{TITLE_TSPAN_LINES}} {{ACCENT_SHAPE}}</svg>",
        encoding="utf-8",
    )
    out_images = tmp_path / "out" / "images"

    mock_subproc.return_value = MagicMock(returncode=0)

    with patch("src.image.TEMPLATE_PATH", template_svg), \
         patch("src.image.OUT_IMAGES_DIR", out_images), \
         patch("src.image.plan.get_post", return_value=dummy_post):

        out_png = generate_card("w1-01")
        assert out_png.name == "w1-01.png"
        assert mock_subproc.called

        # verify resvg command arguments
        cmd = mock_subproc.call_args[0][0]
        assert cmd[0] == "resvg"
        assert cmd[2] == str(out_png)


def test_generate_card_missing_post_raises():
    with patch("src.image.plan.get_post", return_value=None):
        with pytest.raises(KeyError):
            generate_card("unknown-id")
