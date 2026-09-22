import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from admission_tables import parse_score_bands, admission_block
from admission_document import table_asset

class AdmissionTablesTest(unittest.TestCase):
    def test_longer_named_variant_wins_over_base_name(self):
        assets=[{'college':'先进制造学院','code':'085401','name':'新一代电子信息技术','key':'base'},{'college':'先进制造学院','code':'085401','name':'新一代电子信息技术（海西联培）','key':'joint'}]
        self.assertEqual(table_asset('先进制造学院－085401 新一代电子信息技术（海西联培）',assets)['key'],'joint')

    def test_wrapped_scores_and_counts(self):
        rows=parse_score_bands('成绩区间\n320-329 329 328\n321 3 2 1 67%\n合计 3 2 1 67%')
        self.assertEqual(rows[0]['admitted'],2)
        self.assertEqual(rows[0]['rate'],'67%')
    def test_reject_inconsistent_counts(self):
        with self.assertRaises(ValueError):
            parse_score_bands('成绩区间\n320-329 328 3 3 1 100%\n合计')
    def test_ratio_and_identity(self):
        row=dict(code='085402',retest_count=51,admitted=35,eliminated=16,max=400,min=309,average=361,page=1262)
        result=admission_block('甲大学','甲学院','通信工程',row,[])
        self.assertIn('| 51 | 35 | 1.46 | 400 | 309 | 361 |',result)
        self.assertIn('甲学院－085402 通信工程',result)
    def test_total_mismatch_blocks(self):
        row=dict(code='085402',retest_count=51,admitted=35,eliminated=16)
        with self.assertRaises(ValueError):
            admission_block('甲大学','甲学院','通信工程',row,[dict(retest_count=1,admitted=1,eliminated=0)])
    def test_reporting_scope_can_differ_from_source_bands(self):
        row=dict(code='085400',retest_count=159,admitted=93,eliminated=66,max=450,min=347,median=401,average=400,admit_rate='58%',page=1,reporting=dict(retest_count=148,admitted=83,eliminated=65,max=450,min=370,median=None,average=403.7,admit_rate='56%'))
        result=admission_block('甲大学','甲学院','电子信息',row,[])
        self.assertIn('| 148 | 83 | 1.78 | 450 | 370 | 403.7 |',result)

if __name__=='__main__': unittest.main()

