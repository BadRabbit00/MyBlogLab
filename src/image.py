"""Image generator module for blog-agent (Step 3: SVG card -> PNG).

Injects deterministic geometric accents and rubric-tailored color palettes into
templates/card.svg and compiles them to high-resolution PNGs via resvg.
"""

import hashlib
import html
from pathlib import Path
import subprocess
import tempfile
from typing import Optional

import src.plan as plan

BASE_DIR: Path = Path(__file__).resolve().parent.parent
TEMPLATE_PATH: Path = BASE_DIR / "templates" / "card.svg"
OUT_IMAGES_DIR: Path = BASE_DIR / "out" / "images"

RUBRIC_COLORS: dict[str, str] = {
    "razbor": "#38bdf8",     # Cyan / Sky
    "keys": "#f43f5e",       # Neon Rose / Red
    "instrument": "#10b981", # Emerald Green
    "dnevnik": "#a855f7",    # Purple / Lavender
}

RUBRIC_LABELS: dict[str, str] = {
    "razbor": "РАЗБОР",
    "keys": "КЕЙС",
    "instrument": "ИНСТРУМЕНТ",
    "dnevnik": "ДНЕВНИК",
}

SHAPES: list[str] = [
    # Shape 0: Hexagon Matrix
    """
    <polygon points="100,10 180,55 180,145 100,190 20,145 20,55" opacity="0.6"/>
    <polygon points="100,35 160,70 160,130 100,165 40,130 40,70" opacity="0.9"/>
    <circle cx="100" cy="100" r="14" fill="currentColor" fill-opacity="0.8"/>
    <line x1="100" y1="10" x2="100" y2="35"/>
    <line x1="180" y1="55" x2="160" y2="70"/>
    <line x1="180" y1="145" x2="160" y2="130"/>
    <line x1="100" y1="190" x2="100" y2="165"/>
    """,
    # Shape 1: Circuit Lattice
    """
    <path d="M 10 30 L 90 30 L 130 80 L 220 80" stroke-width="2"/>
    <circle cx="10" cy="30" r="5" fill="currentColor"/>
    <circle cx="220" cy="80" r="7" fill="currentColor"/>
    <path d="M 40 120 L 110 120 L 150 160 L 200 160" stroke-width="2"/>
    <circle cx="40" cy="120" r="4" fill="currentColor"/>
    <circle cx="200" cy="160" r="6" fill="currentColor"/>
    <line x1="90" y1="30" x2="90" y2="100" stroke-dasharray="4 4"/>
    """,
    # Shape 2: Concentric Radar Arcs
    """
    <circle cx="110" cy="110" r="95" stroke-dasharray="12 6" opacity="0.4"/>
    <circle cx="110" cy="110" r="65" stroke-width="2"/>
    <circle cx="110" cy="110" r="30" opacity="0.7"/>
    <circle cx="110" cy="110" r="8" fill="currentColor"/>
    <line x1="110" y1="5" x2="110" y2="215" opacity="0.3"/>
    <line x1="5" y1="110" x2="215" y2="110" opacity="0.3"/>
    """,
    # Shape 3: Diamond Node Grid
    """
    <polygon points="100,10 190,100 100,190 10,100" stroke-width="2"/>
    <polygon points="100,45 155,100 100,155 45,100" opacity="0.7"/>
    <circle cx="100" cy="10" r="5" fill="currentColor"/>
    <circle cx="190" cy="100" r="5" fill="currentColor"/>
    <circle cx="100" cy="190" r="5" fill="currentColor"/>
    <circle cx="10" cy="100" r="5" fill="currentColor"/>
    <circle cx="100" cy="100" r="10" fill="currentColor" fill-opacity="0.5"/>
    """,
    # Shape 4: Binary Slice Bars
    """
    <rect x="20" y="20" width="16" height="150" opacity="0.8" fill="currentColor" fill-opacity="0.15"/>
    <rect x="55" y="60" width="16" height="110" opacity="0.8" fill="currentColor" fill-opacity="0.15"/>
    <rect x="90" y="10" width="16" height="160" opacity="0.8" fill="currentColor" fill-opacity="0.15"/>
    <rect x="125" y="80" width="16" height="90" opacity="0.8" fill="currentColor" fill-opacity="0.15"/>
    <rect x="160" y="40" width="16" height="130" opacity="0.8" fill="currentColor" fill-opacity="0.15"/>
    <line x1="0" y1="180" x2="200" y2="180" stroke-width="2"/>
    """,
    # Shape 5: Isometric Sandbox Cube
    """
    <path d="M 100 15 L 180 60 L 180 150 L 100 195 L 20 150 L 20 60 Z" stroke-width="2"/>
    <line x1="100" y1="105" x2="180" y2="60"/>
    <line x1="100" y1="105" x2="20" y2="60"/>
    <line x1="100" y1="105" x2="100" y2="195"/>
    <circle cx="100" cy="105" r="7" fill="currentColor"/>
    """,
]


def _wrap_title(title: str, max_chars_per_line: int = 32) -> list[str]:
    """Wrap title into clean multi-line slices for SVG display."""
    words = title.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0

    for word in words:
        word_len = len(word)
        if current_line and (current_len + 1 + word_len) > max_chars_per_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = word_len
        else:
            current_line.append(word)
            current_len += (1 if current_line else 0) + word_len

    if current_line:
        lines.append(" ".join(current_line))

    # Cap at 4 lines for layout harmony
    return lines[:4]


def _render_title_tspans(lines: list[str]) -> str:
    """Generate SVG text and tspans for wrapped title lines."""
    tspans: list[str] = []
    y_step = 62
    for idx, line in enumerate(lines):
        dy = 0 if idx == 0 else y_step
        escaped_line = html.escape(line)
        tspans.append(
            f'<tspan x="0" dy="{dy}">{escaped_line}</tspan>'
        )
    inner_text = "\n    ".join(tspans)
    return (
        f'<text font-family="\'Liberation Sans\', sans-serif" font-size="44" font-weight="800" fill="#f8fafc" letter-spacing="-0.5">\n'
        f'    {inner_text}\n'
        f'  </text>'
    )


def generate_card(post_id: str) -> Path:
    """Generate social card PNG for the specified post ID."""
    post = plan.get_post(post_id)
    if not post:
        raise KeyError(f"Post with id '{post_id}' not found.")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        svg_content = f.read()

    accent_color = RUBRIC_COLORS.get(post.rubric, "#38bdf8")
    rubric_label = RUBRIC_LABELS.get(post.rubric, post.rubric.upper())

    # Deterministic accent selection based on post id hash
    id_hash = int(hashlib.sha256(post.id.encode()).hexdigest(), 16)
    shape_index = id_hash % len(SHAPES)
    accent_shape = SHAPES[shape_index].replace("currentColor", accent_color)

    # Deterministic coordinates within upper right bounds (x: 880-960, y: 120-180)
    accent_x = 880 + (id_hash % 70)
    accent_y = 120 + ((id_hash >> 8) % 60)

    # Title formatting
    title_lines = _wrap_title(post.title)
    title_tspans = _render_title_tspans(title_lines)

    # Badge width calculation (approx 12px per char + padding)
    badge_width = max(90, len(rubric_label) * 12 + 32)
    id_offset_x = badge_width + 20

    # Replacement dictionary
    replacements: dict[str, str] = {
        "{{ACCENT_COLOR}}": accent_color,
        "{{RUBRIC_LABEL}}": rubric_label,
        "{{BADGE_WIDTH}}": str(badge_width),
        "{{ID_OFFSET_X}}": str(id_offset_x),
        "{{POST_ID}}": post.id.upper(),
        "{{ACCENT_X}}": str(accent_x),
        "{{ACCENT_Y}}": str(accent_y),
        "{{ACCENT_SHAPE}}": accent_shape,
        "{{TITLE_TSPAN_LINES}}": title_tspans,
    }

    final_svg = svg_content
    for key, val in replacements.items():
        final_svg = final_svg.replace(key, val)

    OUT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out_png_path = OUT_IMAGES_DIR / f"{post.id}.png"

    # Render through resvg
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8") as tmp_svg:
        tmp_svg_path = Path(tmp_svg.name)
        tmp_svg.write(final_svg)
        tmp_svg.flush()

    try:
        cmd = ["resvg", str(tmp_svg_path), str(out_png_path)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        if tmp_svg_path.exists():
            tmp_svg_path.unlink()

    return out_png_path


def generate_all_cards() -> int:
    """Generate cards for all posts in the content plan."""
    all_plan = plan.load()
    count = 0
    for post in all_plan.posts:
        generate_card(post.id)
        count += 1
    return count
