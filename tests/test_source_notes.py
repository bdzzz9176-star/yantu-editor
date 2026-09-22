import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from source_notes import sources_at_end

class SourceNotesTest(unittest.TestCase):
    def test_relocation_preserves_content(self):
        text='# 稿件\n## 学院A\n|人数|\n|---|\n|35|\n*数据来源：手册第12页。*\n[录取分段图:081000]\n风险待核验。\n## 数据说明\n适用2026年。'
        out=sources_at_end(text);body,tail=out.split('## 资料来源与说明')
        self.assertNotIn('来源',body);self.assertIn('第12页',tail)
        self.assertIn('风险待核验',body);self.assertIn('[录取分段图:081000]',body)
        self.assertIn('|35|',body);self.assertIn('适用2026年',tail)
        self.assertEqual(out,sources_at_end(out))
    def test_two_colleges_keep_source_identity(self):
        out=sources_at_end('## 甲学院\n来源：甲手册第2页。\n## 乙学院\n来源：乙手册第9页。')
        self.assertIn('甲学院：来源：甲手册第2页',out)
        self.assertIn('乙学院：来源：乙手册第9页',out)
    def test_bold_source_and_no_sources(self):
        out=sources_at_end('# 文\n**数据来源**：手册第1页。\n正文')
        self.assertIn('资料来源与说明',out)
        self.assertEqual(sources_at_end('正文'),'正文\n')
    def test_existing_duplicate_appendix_paragraphs_are_collapsed(self):
        out=sources_at_end('正文\n## 资料来源与说明\n同一口径说明。\n\n同一口径说明。')
        self.assertEqual(out.count('同一口径说明。'),1)

if __name__=='__main__':unittest.main()

