import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from scripts.build_word import build


class WordChartControlTests(unittest.TestCase):
    def build_and_count_images(self, markdown: str) -> int:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "draft.md"
            chart = root / "chart.png"
            output = root / "result.docx"
            source.write_text(markdown, encoding="utf-8")
            Image.new("RGB", (40, 30), "white").save(chart)
            build(output=output, source=source, chart=chart)
            with ZipFile(output) as archive:
                return sum(name.startswith("word/media/") for name in archive.namelist())

    def test_chart_marker_inserts_chart(self):
        count = self.build_and_count_images("# 标题\n\n## 二、2026复试线\n\n[图表建议：2024-2026四个方向复试线变化]\n")
        self.assertEqual(count, 1)

    def test_removed_chart_marker_removes_chart_from_word(self):
        count = self.build_and_count_images("# 标题\n\n## 二、2026复试线\n\n图表已经根据编辑意见删除。\n")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

