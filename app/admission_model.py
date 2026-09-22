"""Normalize legacy single-college and multi-college facts without modifying inputs."""
from copy import deepcopy
import re


def normalize_facts(facts,require_identity=True):
    result=deepcopy(facts)
    for program in result.get('programs',[]):
        for field in ('college','college_code'):
            if not program.get(field) and result.get(field):program[field]=result[field]
    for row in result.get('admission_2026',[]):
        candidates=[p for p in result.get('programs',[]) if p['code']==row['code'] and
                    (not row.get('college_code') or p.get('college_code')==row['college_code']) and
                    (not row.get('college') or p.get('college')==row['college'])]
        for field in ('college','college_code','name'):
            if row.get(field):continue
            values={p[field] for p in candidates if p.get(field)}
            if len(values)==1:row[field]=values.pop()
            elif field!='name' and not values and result.get(field):row[field]=result[field]
        if require_identity and (not re.fullmatch(r'\d{3}',str(row.get('college_code',''))) or not row.get('name') or not row.get('college') or '待' in row['college']):
            raise ValueError(f'{row["code"]}学院或专业身份未唯一确定，请核验数据')
    for row in result.get('cutoffs',[]):
        for field in ('college','college_code'):
            if not row.get(field) and result.get(field):row[field]=result[field]
    return result


def require_confirmed(task):
    if task.get('status')!='facts_confirmed':
        raise ValueError('当前任务数据尚未确认，不能生成或导出')

