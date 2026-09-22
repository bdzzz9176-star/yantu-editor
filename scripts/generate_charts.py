from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = PROJECT_ROOT / "data" / "cases" / "dalian_maritime" / "manual_data.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "dalian_maritime" / "charts"
WIDTH, HEIGHT = 1600, 900
COLORS = {
    "background": "#fffdf8", "ink": "#17201d", "muted": "#68736f",
    "line": "#dedbd2", "green": "#184f3b", "amber": "#a65b19",
    "amber_soft": "#fff0d8", "blue": "#477a8f", "gold": "#d19a3b",
    "red": "#b85743", "soft": "#f4f1e9",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), size)


def text_center(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, used_font: ImageFont.FreeTypeFont, fill: str) -> None:
    box = draw.textbbox((0, 0), value, font=used_font)
    draw.text((xy[0] - (box[2] - box[0]) / 2, xy[1] - (box[3] - box[1]) / 2), value, font=used_font, fill=fill)


def base_canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 42, WIDTH - 55, HEIGHT - 42), radius=28, fill="#ffffff", outline=COLORS["line"], width=2)
    text_center(draw, (WIDTH / 2, 105), title, font(42, True), COLORS["ink"])
    text_center(draw, (WIDTH / 2, 158), subtitle, font(24, True), COLORS["ink"])
    draw.line((100, 190, WIDTH - 100, 190), fill=COLORS["line"], width=2)
    return image, draw


def draw_grouped_bars(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    categories: list[str],
    series: list[tuple[str, list[float], str]],
    y_min: float,
    y_max: float,
    warning_category: str | None = None,
    x_axis_label: str = "专业代码",
) -> None:
    left, top, right, bottom = 155, 255, 1490, 710
    plot_height = bottom - top
    for index in range(6):
        value = y_min + (y_max - y_min) * index / 5
        y = bottom - plot_height * index / 5
        draw.line((left, y, right, y), fill="#e9e6de", width=2)
        label = f"{value:.0f}"
        draw.text((left - 72, y - 15), label, font=font(18), fill=COLORS["muted"])

    group_width = (right - left) / len(categories)
    bar_width = min(58, group_width / (len(series) + 1))
    for category_index, category in enumerate(categories):
        center = left + group_width * (category_index + 0.5)
        if category == warning_category:
            draw.rounded_rectangle((center - group_width * .46, top - 22, center + group_width * .46, bottom + 62), radius=16, fill=COLORS["amber_soft"])
        for series_index, (_, values, color) in enumerate(series):
            value = values[category_index]
            x0 = center + (series_index - (len(series) - 1) / 2) * (bar_width + 8) - bar_width / 2
            y = bottom - (value - y_min) / (y_max - y_min) * plot_height
            draw.rounded_rectangle((x0, y, x0 + bar_width, bottom), radius=7, fill=color)
            text_center(draw, (x0 + bar_width / 2, y - 19), f"{value:g}", font(17, True), COLORS["ink"])
        text_center(draw, (center, bottom + 35), category + ("*" if category == warning_category else ""), font(20, True), COLORS["ink"])

    text_center(draw, ((left + right) / 2, bottom + 78), x_axis_label, font(18), COLORS["muted"])

    legend_x = 105
    for label, _, color in series:
        draw.rounded_rectangle((legend_x, 215, legend_x + 28, 239), radius=5, fill=color)
        draw.text((legend_x + 38, 213), label, font=font(18), fill=COLORS["ink"])
        legend_x += 190


def footer(draw: ImageDraw.ImageDraw, source: dict, warning: str | None = None) -> None:
    if warning:
        draw.rounded_rectangle((100, 760, WIDTH - 100, 812), radius=12, fill=COLORS["amber_soft"])
        draw.text((120, 774), "风险提示：" + warning, font=font(17), fill="#7d430f")
    source_y = 828 if warning else 785
    draw.text((100, source_y), f"数据来源：择校手册 {source['page_range']}｜当前口径：{source['usage_decision']}", font=font(16), fill=COLORS["muted"])


def save_chart(image: Image.Image, output: Path, filename: str) -> str:
    output.mkdir(parents=True, exist_ok=True)
    target = output / filename
    image.save(target, format="PNG", optimize=True)
    return filename


def generate_all_charts(data_file: Path = DEFAULT_DATA, output_dir: Path = DEFAULT_OUTPUT) -> dict:
    data = json.loads(Path(data_file).read_text(encoding="utf-8"))
    source = data["source"]
    charts = []

    cutoffs = data["cutoffs"]
    chart_title = "2024—2026年电子通信相关专业复试线变化"
    chart_subtitle = "大连海事大学 · 信息科学技术学院 · 单位：分"
    image, draw = base_canvas(chart_title, chart_subtitle)
    categories = [item["program_code"] for item in cutoffs]
    series = [(str(year), [item[str(year)] for item in cutoffs], color) for year, color in zip((2024, 2025, 2026), (COLORS["blue"], COLORS["gold"], COLORS["green"]))]
    draw_grouped_bars(image, draw, categories, series, 240, 410)
    footer(draw, source)
    filename = save_chart(image, output_dir, "cutoff_trends.png")
    charts.append({"id": "cutoff_trends", "title": chart_title, "subtitle": chart_subtitle, "filename": filename, "url": f"/generated/charts/{filename}", "data": cutoffs, "warning": None})

    admission = data["admission_2026"]
    warning = next((item.get("warning") for item in admission if item.get("warning")), None)
    chart_title = "2026年电子通信相关专业一志愿录取分数"
    chart_subtitle = "大连海事大学 · 信息科学技术学院 · 最低分/平均分/最高分 · 单位：分"
    image, draw = base_canvas(chart_title, chart_subtitle)
    categories = [item["program_code"] for item in admission]
    series = [("最低分", [item["min"] for item in admission], COLORS["blue"]), ("平均分", [item["avg"] for item in admission], COLORS["gold"]), ("最高分", [item["max"] for item in admission], COLORS["green"])]
    draw_grouped_bars(image, draw, categories, series, 240, 420, warning_category="085408")
    footer(draw, source, warning)
    filename = save_chart(image, output_dir, "admission_scores_2026.png")
    charts.append({"id": "admission_scores_2026", "title": chart_title, "subtitle": chart_subtitle, "filename": filename, "url": f"/generated/charts/{filename}", "data": admission, "warning": warning})

    subject = data["subject_scores_2026"]
    chart_title = "2026年电子通信相关专业807专业课成绩"
    chart_subtitle = "大连海事大学 · 信息科学技术学院 · 最低分/平均分/最高分 · 单位：分"
    image, draw = base_canvas(chart_title, chart_subtitle)
    categories = [item["program_code"] for item in subject]
    series = [("最低分", [item["min"] for item in subject], COLORS["blue"]), ("平均分", [item["avg"] for item in subject], COLORS["gold"]), ("最高分", [item["max"] for item in subject], COLORS["green"])]
    draw_grouped_bars(image, draw, categories, series, 50, 145)
    footer(draw, source)
    filename = save_chart(image, output_dir, "subject_scores_2026.png")
    charts.append({"id": "subject_scores_2026", "title": chart_title, "subtitle": chart_subtitle, "filename": filename, "url": f"/generated/charts/{filename}", "data": subject, "warning": None})

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "deterministic_pillow_v1",
        "source": source,
        "charts": charts,
    }
    temporary = output_dir / ".charts_manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_dir / "charts_manifest.json")
    return manifest


if __name__ == "__main__":
    generate_all_charts()

