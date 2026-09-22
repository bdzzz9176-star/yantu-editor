"""Source-backed, per-program admission tables; no model-generated numbers."""
from __future__ import annotations
import re

FULL_HEADERS=['学院与专业','最高/最低/中位/平均','复试/录取/淘汰','录取率','专业课最高/平均/最低','数学平均']
LEGACY_HEADERS=['学院及专业','复试人数','录取人数','复录比','录取最高分','录取最低分','录取平均分']


def shown(value):
    return '—' if value is None or value=='' else str(value)


def reporting_row(row):
    result=dict(row);result.update(row.get('reporting') or {})
    return result


def admission_values(identity: str,row: dict) -> list[str]:
    row=reporting_row(row)
    return [identity,
            ' / '.join(shown(row.get(k)) for k in ('max','min','median','average')),
            ' / '.join(shown(row.get(k)) for k in ('retest_count','admitted','eliminated')),
            shown(row.get('admit_rate')),
            ' / '.join(shown(row.get(k)) for k in ('professional_max','professional_average','professional_min')),
            shown(row.get('math_average'))]


def parse_score_bands(text: str) -> list[dict]:
    if '成绩区间' not in text or '合计' not in text:
        return []
    section=text.split('成绩区间',1)[1].split('合计',1)[0]
    matches=list(re.finditer(r'(?<!\d)(\d{3})\s*[-—–]\s*(\d{3})(?!\d)',section))
    result=[]
    for i,m in enumerate(matches):
        chunk=section[m.end():matches[i+1].start() if i+1<len(matches) else len(section)]
        counts=re.search(r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s*%',chunk)
        if not counts:
            raise ValueError('分数段尾部人数无法识别，需核验原页')
        entered,admitted,eliminated=map(int,counts.group(1,2,3))
        if entered!=admitted+eliminated or admitted>entered:
            raise ValueError('分数段人数不一致，需核验原页')
        result.append(dict(band=f'{m[1]}-{m[2]}',retest_count=entered,admitted=admitted,eliminated=eliminated,rate=counts[4]+'%'))
    return result


def admission_block(school: str, college: str, name: str, row: dict, bands: list[dict]) -> str:
    identity=f'{college}－{row["code"]} {name}'
    if bands:
        for key in ('retest_count','admitted','eliminated'):
            if sum(x[key] for x in bands)!=row[key]:
                raise ValueError(f'{identity} 分数段{key}合计与录取汇总不一致，停止插入')
    display=reporting_row(row)
    ratio=f'{display["retest_count"]/display["admitted"]:.2f}' if display.get('admitted') and display.get('retest_count') is not None else '—'
    values=[identity,shown(display.get('retest_count')),shown(display.get('admitted')),ratio,shown(display.get('max')),shown(display.get('min')),shown(display.get('average'))]
    lines=[f'**{school} · {identity} · 2026年一志愿录取汇总**','',
           '| '+' | '.join(LEGACY_HEADERS)+' |',
           '|---|---:|---:|---:|---:|---:|---:|',
           '| '+' | '.join(values)+' |','',
           ]
    if bands:
        lines += [f'**{school} · {identity} · 2026年一志愿初试分数段统计**','',
                  '| 初试分数段 | 进入复试 | 拟录取 | 被刷 | 手册录取率 |','|---|---:|---:|---:|---:|']
        lines += [f'| {x["band"]} | {x["retest_count"]} | {x["admitted"]} | {x["eliminated"]} | {x["rate"]} |' for x in bands]
        lines += [f'| 合计 | {row["retest_count"]} | {row["admitted"]} | {row["eliminated"]} | {row["admit_rate"]} |','',
                  f'来源：择校手册第{row["page"]}页。只列原表提供的区间，未列区间不补零；百分比保留手册取整结果。这些是2026年历史样本，不能视为2027年录取概率。','']
    return '\n'.join(lines)

