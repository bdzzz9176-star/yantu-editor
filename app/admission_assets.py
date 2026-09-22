"""Build task-scoped chart evidence, including cross-page and duplicate-code programs."""
import re
import json
from pathlib import Path
from admission_tables import parse_score_bands, admission_block
from admission_model import normalize_facts

def _admission_cards(pages):
    """Locate cards by text positions; a new card may share its predecessor's last page."""
    material_ids=list(dict.fromkeys(p.get('material_id','') for p in pages))
    if len(material_ids)>1:
        cards=[]
        for material_id in material_ids:
            for card in _admission_cards([p for p in pages if p.get('material_id','')==material_id]):
                card['material_id']=material_id;cards.append(card)
        return cards
    ordered=sorted(pages,key=lambda p:p['page_number'])
    parts=[];page_offsets=[];offset=0
    for page in ordered:
        text=page['text'].replace('（','(').replace('）',')')+'\n'
        page_offsets.append((offset,page['page_number']));parts.append(text);offset+=len(text)
    text=''.join(parts)
    def page_at(position):
        return next(number for start,number in reversed(page_offsets) if start<=position)
    markers=list(re.finditer(r'2026\s*年一志愿',text))
    colleges=list(re.finditer(r'\((\d{3})\)\s*([^\n]{2,30}(?:学院|研究生院))',text))
    programs=list(re.finditer(r'\((\d{6})\)(?:\(专业学位\))?([^\n]+)',text))
    cards=[]
    for i,marker in enumerate(markers):
        college=next((m for m in reversed(colleges) if m.start()<marker.start()),None)
        program=next((m for m in reversed(programs) if m.start()<marker.start()),None)
        if not college or not program:raise ValueError('录取卡片缺少学院或专业身份，需核验原页')
        end=markers[i+1].start() if i+1<len(markers) else len(text)
        content=text[marker.end():end]
        total=re.search(r'合计',content)
        cards.append(dict(material_id=pages[0].get('material_id',''),college_code=college[1],code=program[1],name=program[2].strip(),page=page_at(marker.start()),page_end=page_at(marker.end()+total.end()) if total else None,content=content,ordinal=i+1))
    return cards

def collect_assets(facts, pages):
    facts=normalize_facts(facts)
    result=[]
    rows=facts.get('admission_2026',[])
    has_band_tables=any('成绩区间' in p.get('text','') and '合计' in p.get('text','') for p in pages)
    card_scan_error=''
    try:
        cards=_admission_cards(pages) if rows and has_band_tables else []
    except ValueError as error:
        # A malformed optional score-band card must not disable verified
        # admission summaries for the whole school.
        cards=[];card_scan_error=str(error)
    seen={}
    def summary_asset(row,warning=''):
        college_code=str(row.get('college_code') or '')
        if not college_code.isdigit():raise ValueError('学院归属未确认，不能生成录取汇总表')
        base=f'{college_code}_{row["code"]}_{row["page"]}'
        seen[base]=seen.get(base,0)+1
        key=base if seen[base]==1 else f'{base}_{seen[base]}'
        return dict(key=key,code=row['code'],college_code=college_code,college=row['college'],name=row.get('name',''),page=row['page'],page_end=None,bands=[],totals_match=None,chart_available=False,chart_warning=warning,scope_label=row.get('scope_label',''),scope_note=row.get('scope_note',''))
    if rows and not has_band_tables:
        # Some Word handbooks provide verified admission summaries without
        # machine-readable score bands. Keep the summary contract usable and
        # expose chart capability separately through an empty bands list.
        result=[]
        for row in rows:result.append(summary_asset(row,card_scan_error))
        return result
    used=set()
    for row in rows:
        college_code=row.get('college_code')
        if not college_code or not str(college_code).isdigit():
            raise ValueError('学院归属未确认，不能生成录取图表')
        start=row['page']
        candidates=[c for c in cards if (c['college_code'],c['code'],c['page'])==(str(college_code),row['code'],start) and (not row.get('material_id') or c.get('material_id')==row.get('material_id'))]
        if not candidates:
            candidates=[c for c in cards if (c['code'],c['page'])==(row['code'],start) and (not row.get('material_id') or c.get('material_id')==row.get('material_id'))]
        duplicate_key=len(candidates)>1
        if duplicate_key:
            normalize=lambda s:re.sub(r'\s+','',s.replace('（','(').replace('）',')'))
            candidates=[c for c in candidates if normalize(c['name'])==normalize(row['name'])]
        card_id=(candidates[0].get('material_id'),candidates[0]['ordinal']) if len(candidates)==1 else None
        if len(candidates)!=1 or card_id in used:
            result.append(summary_asset(row,f'{row["college"]} {row["code"]} 第{start}页分数段卡片未能唯一定位，已停用该图表'))
            continue
        card=candidates[0];used.add(card_id)
        end=card['page_end']
        try:
            bands=parse_score_bands(card['content'])
            if not bands:raise ValueError('缺少可核验的分数段原始数据')
            admission_block(facts['school'],row['college'],row['name'],row,bands)
        except ValueError as error:
            result.append(summary_asset(row,str(error)+'；已停用该图表'))
            continue
        key=f'{college_code}_{row["code"]}_{start}'
        if duplicate_key:key+=f'_{card["ordinal"]}'
        result.append(dict(key=key,code=row['code'],college_code=college_code,college=row['college'],name=row['name'],page=start,page_end=end,bands=bands,totals_match=True,chart_available=True,scope_label=row.get('scope_label',''),scope_note=row.get('scope_note','')))
    return result

def prepare_assets(workspace, task_id, facts, requested_keys=None):
    from admission_charts import chart
    root=Path(workspace)/'tasks'/task_id
    pages=json.loads((root/'source_extract.json').read_text(encoding='utf-8'))['pages']
    assets=collect_assets(facts,pages)
    out=root/'outputs';charts=[]
    (out/'charts').mkdir(parents=True,exist_ok=True)
    for item in assets:
        if requested_keys is not None and item['key'] not in requested_keys:continue
        # Tiny samples produce visually impressive but statistically weak charts.
        # This applies to every school and keeps the article focused on useful evidence.
        if sum(x['retest_count'] for x in item['bands']) < 10:continue
        filename=f'admission_band_{item["key"]}.png'
        chart(item['bands'],item['college'],item['code'],item['name'].split('（')[0],out/'charts'/filename,scope_label=item['scope_label'])
        charts.append(dict(key=item['key'],code=item['code'],college=item['college'],scope_label=item['scope_label'],scope_note=item['scope_note'],title=f'{item["college"]} {item["code"]} {item["name"]}｜2026一志愿分数段'+(f'（{item["scope_label"]}）' if item['scope_label'] else ''),filename=filename,url=f'/generated/tasks/{task_id}/charts/{filename}'))
    (out/'admission_table_review.json').write_text(json.dumps(assets,ensure_ascii=False,indent=2),encoding='utf-8')
    warnings=[{'key':x['key'],'college':x['college'],'code':x['code'],'message':x['chart_warning']} for x in assets if x.get('chart_warning')]
    manifest={'charts':charts,'warnings':warnings}
    (out/'charts/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

