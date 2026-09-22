from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def parse_verified_handbook_section(school, page_start, page_end, pages=None):
    """Reviewed data are configuration tied to an exact source, never school branches."""
    import hashlib
    import json
    from copy import deepcopy
    from pathlib import Path
    if not pages:return None
    source=json.dumps([(p['page_number'],p['text']) for p in sorted(pages,key=lambda p:p['page_number'])],ensure_ascii=False,separators=(',',':')).encode('utf-8')
    digest=hashlib.sha256(source).hexdigest()
    path=Path(__file__).resolve().parents[1]/'data/reviewed_handbook_profiles.json'
    profiles=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    for profile in profiles:
        if profile['facts']['school']==school and profile['source_sha256']==digest:
            return deepcopy(profile['facts'])
    return None


PROMO_MARKERS = ("免费真题索取", "考研辅导班", "微信公众号&B 站", "B 站:", "小红书：", "抖音：")

def parse_vertical_cutoff_table(text:str,page:int=1)->list[dict[str,Any]]:
    if '近三年复试线' not in text:return []
    vertical=text.split('近三年复试线',1)[1];vertical=re.split(r'复试线分析|\n三[、.]|2027考研初复试',vertical,1)[0]
    lines=[x.strip() for x in vertical.splitlines() if x.strip()];result=[];college='学院待确认';i=0
    while i<len(lines):
        if lines[i].endswith(('学院','研究院')) and not re.search(r'[（(]?\d{6}',lines[i]):college=lines[i];i+=1;continue
        program=re.match(r'(?:[（(])?(\d{6})(?:[）)])?\s*(.+)',lines[i])
        if program and i+3<len(lines) and all(re.fullmatch(r'(?:\d{3}|[/—-])',lines[i+j]) for j in (1,2,3)):
            values=[int(lines[i+j]) if re.fullmatch(r'\d{3}',lines[i+j]) else None for j in (1,2,3)]
            change=values[2]-values[1] if values[1] is not None and values[2] is not None else None
            result.append({'college':college,'college_code':'','code':program[1],'name':program[2].strip(),'2024':values[0],'2025':values[1],'2026':values[2],'change':change,'page':page});i+=4;continue
        i+=1
    return result


def parse_vertical_admission_table(text:str,page:int=1)->list[dict[str,Any]]:
    """Parse Word tables flattened to one cell per line; absent median stays null."""
    if '2026考情难度分析' not in text:return []
    area=text.split('2026考情难度分析',1)[1]
    area=re.split(r'\n五[、.]|\n2026录取分析',area,1)[0]
    lines=[x.strip() for x in area.splitlines() if x.strip()]
    rows=[];college='学院待确认';college_code='';i=0
    while i<len(lines):
        unit=re.match(r'[（(](\d{3})[）)]\s*(.+(?:学院|研究院))$',lines[i])
        if unit:college_code,college=unit.group(1),unit.group(2).strip();i+=1;continue
        program=re.match(r'[（(](\d{6})[）)]\s*(.+)',lines[i])
        if not program:i+=1;continue
        boundary=i+1
        while boundary<len(lines) and not re.match(r'[（(](?:\d{3}|\d{6})[）)]',lines[boundary]):boundary+=1
        block=lines[i+1:boundary]
        numeric=[x for x in block if re.fullmatch(r'\d+(?:\.\d+)?(?::1)?',x)]
        if len(numeric)>=7:
            retest=int(float(numeric[-7]));admitted=int(float(numeric[-6]));minimum=int(float(numeric[-4]));maximum=int(float(numeric[-3]));average=float(numeric[-2]);professional_average=float(numeric[-1])
            rows.append({'college':college,'college_code':college_code,'code':program.group(1),'name':program.group(2).strip(),'max':maximum,'min':minimum,'median':None,'average':average,'retest_count':retest,'admitted':admitted,'eliminated':retest-admitted,'admit_rate':str((Decimal(admitted)*100/Decimal(retest)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))+'%' if retest else '待确认','professional_max':None,'professional_average':professional_average,'professional_min':None,'math_average':None,'page':page})
        i=boundary
    return rows


def parse_vertical_program_table(text:str,page:int=1)->list[dict[str,Any]]:
    if '考研初复试介绍' not in text:return []
    area=text.split('考研初复试介绍',1)[1].split('考试科目及参考书目',1)[0]
    lines=[x.strip() for x in area.splitlines() if x.strip()]
    rows=[];college='学院待确认';college_code='';i=0
    while i<len(lines):
        unit=re.match(r'[（(](\d{3})[）)]\s*(.+(?:学院|研究院))$',lines[i])
        if unit:college_code,college=unit.group(1),unit.group(2).strip();i+=1;continue
        program=re.match(r'[（(](\d{6})[）)]\s*(.+)',lines[i])
        if not program:i+=1;continue
        boundary=i+1
        while boundary<len(lines) and not re.match(r'[（(](?:\d{3}|\d{6})[）)]',lines[boundary]):boundary+=1
        block=lines[i+1:boundary]
        ratio_index=next((n for n,x in enumerate(block) if re.fullmatch(r'\d+\s*/\s*\d+',x)),None)
        if ratio_index is not None:
            before=block[:ratio_index];after=block[ratio_index+1:]
            subject=next((x for x in before if '+' in x or '数一' in x or '数二' in x), '待确认')
            changes=[x for x in before if x.startswith('27改考')]
            if changes:subject+='；'+'；'.join(changes)
            retest=next((x for x in after if x not in ('学术型','专业型') and not x.startswith('27改考')), '待确认')
            retest_changes=[x for x in after if x.startswith('27改考')]
            if retest_changes:
                for change in dict.fromkeys(retest_changes):
                    if change not in retest:retest+='；'+change
            planned=int(re.split(r'\s*/\s*',block[ratio_index])[-1])
            rows.append({'college':college,'college_code':college_code,'code':program.group(1),'name':program.group(2).strip(),'planned':planned,'initial_subjects':subject,'retest':retest,'page':page})
        i=boundary
    return rows


def parse_vertical_professional_scores(text:str)->dict[tuple[str,str],dict[str,float]]:
    if '专业课难度分析' not in text:return {}
    area=text.split('专业课难度分析',1)[1]
    area=re.split(r'\n七[、.]|\n调剂情况',area,1)[0]
    lines=[x.strip() for x in area.splitlines() if x.strip()]
    result={};college_code='';i=0
    while i<len(lines):
        unit=re.match(r'[（(](\d{3})[）)]\s*(.+(?:学院|研究院))$',lines[i])
        if unit:college_code=unit.group(1);i+=1;continue
        program=re.match(r'[（(](\d{6})[）)]\s*(.+)',lines[i])
        if not program:i+=1;continue
        boundary=i+1
        while boundary<len(lines) and not re.match(r'[（(](?:\d{3}|\d{6})[）)]',lines[boundary]):boundary+=1
        numbers=[float(x) for x in lines[i+1:boundary] if re.fullmatch(r'\d+(?:\.\d+)?',x)]
        if len(numbers)>=3:result[(college_code,program.group(1))]={'professional_max':numbers[-3],'professional_min':numbers[-2],'professional_average':numbers[-1]}
        i=boundary
    return result


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not any(marker in line for marker in PROMO_MARKERS)]


def _last_match(pattern: re.Pattern[str], text: str, end: int) -> re.Match[str] | None:
    matches = list(pattern.finditer(text[:end]))
    return matches[-1] if matches else None


def _context_fields(page_text: dict[int,str]) -> dict[str,Any]:
    """Keep recurring handbook sections as sourced facts even when their prose varies."""
    profile={};course_notes=[];score_formulas=[]
    active_college={'college_code':'待确认','college':'学院待确认'}
    for page,text in sorted(page_text.items()):
        intro=re.search(r'学校简介\s*([\s\S]*?)(?:第四轮学科评估|综合性价比|$)',text)
        if intro and intro.group(1).strip():profile['introduction']=re.sub(r'\s+',' ',intro.group(1)).strip()
        if '第四轮学科评估' in text:
            area=text.split('第四轮学科评估',1)[1].split('综合性价比',1)[0]
            disciplines=[]
            for line in area.splitlines():
                match=re.match(r'(.{2,30}?)[：:]\s*([A-C][+-]?)\s*$',line.strip())
                if match:disciplines.append({'discipline':match.group(1).strip(),'grade':match.group(2),'page':page})
            if disciplines:profile['discipline_evaluations']=disciplines
        colleges=list(re.finditer(r'\((\d{3})\)([^\n]{2,40}(?:研究生院|研究院|学院)(?:\([^\n)]*学院\))?)',text))
        if colleges:
            active_college={'college_code':colleges[-1].group(1),'college':colleges[-1].group(2).strip()}
        college=dict(active_college)
        if '初复试专业课介绍' in text:
            note=text.split('初复试专业课介绍',1)[1].split('总成绩计算公式',1)[0].strip()
            if note:course_notes.append({**college,'content':note,'page':page})
        formula=re.search(r'总成绩计算公式\s*([^\n]+)',text)
        if formula:score_formulas.append({**college,'formula':formula.group(1).strip(),'page':page})
        if '考试科目及参考书目' in text and not any(item.get('page')==page for item in course_notes):
            note=text.split('考试科目及参考书目',1)[1]
            note=re.split(r'\n四[、.]|\n2026考情难度分析',note,1)[0].strip()
            if note:course_notes.append({**college,'content':note,'page':page})
        # Some handbooks omit a section title and start directly with this
        # three-column reference-book table header.
        if re.search(r'专业课代码\s+考试科目\s+参考(?:教材|书目)',text) and not any(item.get('page')==page for item in course_notes):
            note=re.split(r'专业课代码\s+考试科目\s+参考(?:教材|书目)',text,1)[1]
            note=re.split(r'总成绩计算公式|\n四[、.]|\n20\d{2}考情难度分析',note,1)[0].strip()
            if note:course_notes.append({**college,'content':note,'page':page})
        if '复试信息' in text:
            formula_area=text.split('复试信息',1)[1]
            formula_area=re.split(r'奖助学金|学费',formula_area,1)[0]
            lines=[x.strip() for x in formula_area.splitlines() if x.strip()]
            active='学院待确认'
            for line in lines:
                if line.endswith(('学院','研究院')):active=line;continue
                if '总成绩' in line and '=' in line:score_formulas.append({'college_code':'待确认','college':active,'formula':line,'page':page})
    return {'school_profile':profile,'course_notes':course_notes,'score_formulas':score_formulas}


def _coverage(facts:dict[str,Any], source_text:str='')->dict[str,Any]:
    groups={'院校基本信息':bool(facts.get('school_profile')),'招生专业与考试科目':len(facts.get('programs',[])),
            '专业课与参考资料':len(facts.get('course_notes',[])),'复试总成绩公式':len(facts.get('score_formulas',[])),
            '一志愿录取统计':len(facts.get('admission_2026',[])),'近三年复试线':len(facts.get('cutoffs',[]))}
    cutoff_heading=bool(re.search(r'(?:近[\u4e00-三两\d]年)?(?:复试|录取)(?:分数)?线(?:变化)?(?:情况)?',source_text))
    details={k:('已识别' if v is True else f'已识别 {v} 组' if v else '未识别') for k,v in groups.items()}
    if not groups['近三年复试线']:
        details['近三年复试线']='资料中发现该栏目，但未能形成可审核数据' if cutoff_heading else '该学校对应资料页未设置此栏目'
    return {'sections':groups,'details':details,'complete_sections':[k for k,v in groups.items() if v],'missing_sections':[k for k,v in groups.items() if not v]}


def parse_handbook_pages(school: str, pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Parse the handbook's recurring school template without a per-school mapping."""
    if not pages:
        return None
    pages=sorted(pages,key=lambda p:p['page_number'])
    start, end = pages[0]["page_number"], pages[-1]["page_number"]
    page_text = {p["page_number"]: "\n".join(_clean_lines(p["text"]+'\n'+p.get('ocr_text',''))).replace('（','(').replace('）',')') for p in pages}
    context=_context_fields(page_text)
    verified = parse_verified_handbook_section(school, start, end, pages)
    if verified:
        verified["parser_mode"] = "verified_profile"
        for key,value in context.items():verified.setdefault(key,value)
        verified['coverage']=_coverage(verified)
        return verified

    joined = "\n".join(f"\n[[PAGE:{number}]]\n{text}" for number, text in page_text.items())
    college_re = re.compile(r"\((\d{3})\)([^\n]{2,40}(?:研究生院|研究院|学院)(?:\([^\n)]*学院\))?)")
    plain_college_re = re.compile(r"(?:^|\n)[\s\uf0d8■]*([^\n()]{2,40}(?:研究生院|研究院|学院)(?:\([^\n)]*学院\))?)\s*(?=\n)")
    program_re = re.compile(r"\((\d{6})\)(?:\(专业学位\))?([^\n]{2,45})")
    page_re = re.compile(r"\[\[PAGE:(\d+)\]\]")

    def source_page(position: int) -> int:
        marker = _last_match(page_re, joined, position)
        return int(marker.group(1)) if marker else start

    # Catalogue blocks are identified by the stable column heading used throughout the handbook.
    programs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in program_re.finditer(joined):
        next_program=program_re.search(joined,match.end())
        next_college=college_re.search(joined,match.end())
        boundary=min([m.start() for m in (next_program,next_college) if m]+[len(joined)])
        tail = joined[match.end():boundary]
        if "研究方向" not in tail[:220] or "统招人数" not in tail[:220]:
            continue
        college = _last_match(college_re, joined, match.start())
        direction = re.search(r"\(\d{2}\)[^\n]*?\s+(\d+)\s*人?\s*\n", tail)
        subject_area = tail[:650].split("面试", 1)[0].split("初复试专业课介绍", 1)[0]
        subjects = re.findall(r"\((20[14]|30[12]|\d{3})\)([^\n]{2,30})", subject_area)
        subject_matches=list(re.finditer(r'\(\d{3}\)[^\n]+',subject_area))
        retest_tail=subject_area[subject_matches[-1].end():].strip() if subject_matches else ''
        retest_text=''.join(retest_tail.splitlines()).strip() or '待确认'
        subject_text = "；".join(f"{code}{name.strip()}" for code, name in subjects[:4])
        key = ((college.group(1) if college else ""), match.group(1))
        if key in seen:
            continue
        seen.add(key)
        programs.append({
            "college_code": college.group(1) if college else "待确认",
            "college": college.group(2).strip() if college else "学院待确认",
            "code": match.group(1), "name": match.group(2).strip(),
            "planned": int(direction.group(1)) if direction else None,
            "initial_subjects": subject_text or "待确认", "retest": "面试" if "面试" in tail[:650] else retest_text,
            "page": source_page(match.start()),
        })

    # Admission cards share four summary values followed by admitted/retest ratio and subject values.
    admissions: list[dict[str, Any]] = []
    admission_marker=r"(20\d{2})\s*年\s*[|｜]?\s*一志愿"
    for marker in re.finditer(admission_marker, joined):
        before = joined[max(0, marker.start() - 240):marker.start()]
        program_matches = list(program_re.finditer(before))
        if not program_matches:
            continue
        pm = program_matches[-1]
        code, name = pm.group(1), pm.group(2).strip()
        # A college heading remains active on continuation pages until replaced.
        college = _last_match(college_re, joined, marker.start())
        plain_college=_last_match(plain_college_re,joined,marker.start())
        college_name=plain_college.group(1).strip() if plain_college else (college.group(2).strip() if college else '学院待确认')
        known_codes={p.get('college_code') for p in programs if p.get('college')==college_name and re.fullmatch(r'\d{3}',str(p.get('college_code','')))}
        college_code=next(iter(known_codes)) if len(known_codes)==1 else (college.group(1) if college else '待确认')
        next_admission=re.search(admission_marker,joined[marker.end():])
        admission_end=marker.end()+next_admission.start() if next_admission else len(joined)
        tail = joined[marker.end():admission_end]
        summary = re.search(r"录取最高分\s+录取最低分\s+录取中位分\s+录取平均分[\s\S]{0,80}?(\d{3})\s+(\d{3})\s+([\d.]+)\s+([\d.]+)", tail)
        ratio = re.search(r"(\d+)\s*/\s*(\d+)\s*\(([\d.]+)\)", tail)
        subject = re.search(r"专业课最高分\s+专业课平均分\s+专业课最低分\s+数学平均分[\s\S]{0,80}?(\d{2,6})\s+([\d.]+)\s+(\d{2,3})\s+([\d.]+)", tail)
        # Some PDF tables interleave the last summary column with the first
        # subject-score column, e.g. "86138" means admitted=86 and
        # professional_max=138. Recover it from semantic column boundaries.
        compact=None
        if summary and not ratio and subject:
            first=subject.group(1)
            for split in range(1,len(first)-1):
                admitted_candidate=int(first[:split]); professional_candidate=int(first[split:])
                if admitted_candidate>0 and 50<=professional_candidate<=150:
                    compact=(admitted_candidate,professional_candidate,float(subject.group(2)),int(subject.group(3)),float(subject.group(4)))
                    break
        if not summary or (not ratio and not compact):
            continue
        admitted, retest = (int(ratio.group(1)),int(ratio.group(2))) if ratio else (compact[0],None)
        rate = str((Decimal(admitted)*100/Decimal(retest)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))+'%' if retest else None
        direction_match=re.search(r'\((\d{2})\)',name)
        admissions.append({"year":int(marker.group(1)),"college_code": college_code, "college": college_name, "code": code, "name": name, "direction":direction_match.group(1) if direction_match else None, "max": int(summary.group(1)), "min": int(summary.group(2)), "median": float(summary.group(3)), "average": float(summary.group(4)), "retest_count": retest, "admitted": admitted, "eliminated": retest - admitted if retest is not None else None, "admit_rate": rate, "professional_max": compact[1] if compact else (int(subject.group(1)) if subject else None), "professional_average": compact[2] if compact else (float(subject.group(2)) if subject else None), "professional_min": compact[3] if compact else (int(subject.group(3)) if subject else None), "math_average": compact[4] if compact else (float(subject.group(4)) if subject else None), "page": source_page(marker.start())})

    # Image-only summary tables are paired with the semantic identity markers
    # from the same page in reading order. No school-specific mapping is used.
    active_ocr_college_code='待确认';active_ocr_college_name='学院待确认'
    for page in pages:
        cards=page.get('ocr_admission_rows',[])
        if not cards:continue
        # Identity labels often remain readable only in the OCR layer when the
        # PDF embeds a broken font map. Use the same merged text that the main
        # parser uses, while keeping the numeric grid OCR independent.
        text=page_text.get(page['page_number'],'')
        markers=list(re.finditer(admission_marker,text))
        for marker,card in zip(markers,cards):
            before=text[:marker.start()]
            pm=list(program_re.finditer(before))
            if not pm:continue
            program=pm[-1];college=_last_match(college_re,before,len(before));plain=_last_match(plain_college_re,before,len(before))
            if college:
                active_ocr_college_code=college.group(1);active_ocr_college_name=plain.group(1).strip() if plain else college.group(2).strip()
            else:
                # OCR may damage every Chinese character in an institute name
                # while preserving its three-digit catalogue code. The code is
                # sufficient to recover the canonical name from parsed programs.
                unit_codes=re.findall(r'(?:^|\n)[^\n]{0,4}\((\d{3})\)[^\n]*',before)
                if unit_codes:
                    active_ocr_college_code=unit_codes[-1]
                    unit_program=next((p for p in programs if p.get('college_code')==active_ocr_college_code),None)
                    if unit_program:active_ocr_college_name=unit_program.get('college','学院待确认')
            college_name=active_ocr_college_name;college_code=active_ocr_college_code
            catalogue=[p for p in programs if p.get('code')==program.group(1)]
            if college_name=='学院待确认' and len(catalogue)==1:
                college_name=catalogue[0].get('college',college_name);college_code=catalogue[0].get('college_code',college_code)
            admitted,retest=card['admitted'],card['retest_count']
            ocr_name=program.group(2).strip();direction_match=re.search(r'\((\d{2})\)',ocr_name)
            admissions.append({'year':int(marker.group(1)),'college_code':college_code,'college':college_name,
                'code':program.group(1),'name':ocr_name,'direction':direction_match.group(1) if direction_match else None,'max':card['max'],'min':card['min'],
                'median':card['median'],'average':card['average'],'retest_count':retest,'admitted':admitted,
                'eliminated':retest-admitted,'admit_rate':str((Decimal(admitted)*100/Decimal(retest)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))+'%' if retest else None,
                'professional_max':None,'professional_average':None,'professional_min':None,'math_average':None,'page':page['page_number']})

    raw_text='\n'.join(p['text'] for p in pages)
    if not programs:
        programs=parse_vertical_program_table(raw_text,start)
    if not admissions:
        admissions=parse_vertical_admission_table(raw_text,start)
    professional_scores=parse_vertical_professional_scores(raw_text)
    for row in admissions:
        row.update(professional_scores.get((row.get('college_code',''),row.get('code','')),{}))
    # Text and OCR layers may expose the same card. Keep one best row per
    # college/program identity instead of producing duplicate facts.
    unique_admissions={}
    for row in admissions:
        direction=row.get('direction')
        if not direction:
            direction_match=re.search(r'\((\d{2})\)',str(row.get('name','')))
            direction=direction_match.group(1) if direction_match else ''
        key=(row.get('year'),row.get('college_code'),row.get('code'),direction)
        completeness=sum(row.get(k) is not None for k in ('retest_count','admitted','max','min','median','average','professional_max','professional_average','professional_min','math_average'))
        previous=unique_admissions.get(key)
        if previous is None or completeness>previous[0]:unique_admissions[key]=(completeness,row)
    admissions=[item[1] for item in unique_admissions.values()]

    cutoffs: list[dict[str, Any]] = []
    cutoff_part = joined.split("录取分数线变化情况", 1)[-1] if "录取分数线变化情况" in joined else ""
    for line in cutoff_part.splitlines():
        row = re.search(r"(.{2,50}?)\s+(\d{3})\s+(\d{3})\s+(\d{3})\s+(?:上升|上涨|下降|保持不变)\s*(\d+)?", line)
        if row:
            values = [int(row.group(i)) for i in (2, 3, 4)]
            cutoffs.append({"code": "", "name": row.group(1).strip(), "2024": values[0], "2025": values[1], "2026": values[2], "change": values[2] - values[1], "page": source_page(joined.find(line))})

    if not cutoffs:
        for page in pages:
            for item in page.get('ocr_cutoff_rows',[]):
                candidates=[p for p in programs if p.get('code')==item.get('code')]
                if len(candidates)==1:p=candidates[0]
                elif item.get('code'):
                    p={'college':'学院待确认','college_code':'','code':item['code'],'name':'专业名称待确认'}
                else:continue
                values=item['values'];years=item['years']
                direction=re.search(r'(?<!\d)(0[1-9])(?!\d)',item.get('ocr_identity',''))
                display_name=p['name']+(f'({direction.group(1)}方向)' if direction else '')
                row={'college':p['college'],'college_code':p['college_code'],'code':p['code'],'name':display_name,'page':page['page_number'],'change':values[-1]-values[-2] if values[-1] is not None and values[-2] is not None else None}
                if len(candidates)!=1:row['identity_status']='pending_review'
                row.update({str(year):value for year,value in zip(years,values)})
                cutoffs.append(row)

    # Two-year cutoff tables are common in newer school profiles. Parse by
    # their semantic year headers and program identities; keep the unavailable
    # third year empty instead of discarding the entire table.
    if not cutoffs and re.search(r'25\s*复试线\s+26\s*复试线',cutoff_part):
        active_college=None
        named_colleges=sorted({p['college'] for p in programs},key=len,reverse=True)
        matches=list(program_re.finditer(cutoff_part))
        for index,match in enumerate(matches):
            prefix=cutoff_part[:match.start()]
            compact_prefix=re.sub(r'\s+','',prefix)
            located=[(compact_prefix.rfind(re.sub(r'\s+','',college_name)),college_name) for college_name in named_colleges]
            located=[item for item in located if item[0]>=0]
            if located:active_college=max(located)[1]
            block=match.group(2)+'\n'+cutoff_part[match.end():matches[index+1].start() if index+1<len(matches) else len(cutoff_part)]
            single=re.search(r'\d+\s*/\s*\d+\s*/\s*\d+\s*/\s*\d+',block)
            if not single:continue
            scores=[int(x) for x in re.findall(r'(?<!\d)\d{3}(?!\d)',block[:single.start()])]
            trend=re.search(r'(上涨|上升|下降|不变)\s*(\d+)?',block)
            if len(scores)>=2:y25,y26=scores[-2:]
            elif len(scores)==1 and trend and trend.group(2):
                y26=scores[0];delta=int(trend.group(2));y25=y26-delta if trend.group(1) in ('上涨','上升') else y26+delta if trend.group(1)=='下降' else y26
            else:continue
            candidates=[p for p in programs if p['code']==match.group(1) and (not active_college or p['college']==active_college)]
            p=candidates[0] if len(candidates)==1 else None
            cutoffs.append({'college':p['college'] if p else active_college or '学院待确认','college_code':p['college_code'] if p else '', 'code':match.group(1),'name':p['name'] if p else match.group(2).strip(),'2024':None,'2025':y25,'2026':y26,'change':y26-y25,'page':source_page(joined.find(cutoff_part)+match.start())})

    # Some Word handbooks use a vertical table: one line for the program,
    # followed by three separate score lines. Merged college cells apply to
    # all following programs until the next college heading.
    if not cutoffs and "近三年复试线" in joined:
        vertical=joined.split("近三年复试线",1)[1]
        vertical=re.split(r"复试线分析|\n三[、.]|2027考研初复试",vertical,1)[0]
        lines=[x.strip() for x in vertical.splitlines() if x.strip()]
        active_college='学院待确认';i=0
        while i<len(lines):
            line=lines[i]
            if line.endswith(('学院','研究院')) and not re.search(r'[（(]?\d{6}',line):active_college=line;i+=1;continue
            program=re.match(r'(?:[（(])?(\d{6})(?:[）)])?\s*(.+)',line)
            if program and i+3<len(lines) and all(re.fullmatch(r'\d{3}',lines[i+j]) for j in (1,2,3)):
                values=[int(lines[i+j]) for j in (1,2,3)]
                college_matches=[p for p in programs if p.get('college')==active_college]
                college_codes={p.get('college_code') for p in college_matches if p.get('college_code')}
                cutoffs.append({'college':active_college,'college_code':next(iter(college_codes)) if len(college_codes)==1 else '',
                                'code':program.group(1),'name':program.group(2).strip(),'2024':values[0],'2025':values[1],'2026':values[2],
                                'change':values[2]-values[1],'page':source_page(joined.find('近三年复试线'))})
                i+=4;continue
            i+=1

    vertical_cutoffs=parse_vertical_cutoff_table(raw_text,start)
    if len(vertical_cutoffs)>len(cutoffs):cutoffs=vertical_cutoffs

    if not programs and not admissions and not cutoffs:
        return None
    # Resolve wrapped cutoff labels by catalogue identity, not by equal scores.
    if cutoff_part and programs:
        flat=re.sub(r'\[\[PAGE:\d+\]\]','',cutoff_part)
        flat=flat.split('变化情况',1)[-1]
        cursor=0; active_college=None; resolved=[]
        for match in re.finditer(r'(\d{3})\s+(\d{3})\s+(\d{3})\s+(?:上升|上涨|下降|保持不变)\s*(\d+)?\s*分?',flat):
            label=re.sub(r'\s+','',flat[cursor:match.start()]);cursor=match.end()
            named_colleges=sorted({p['college'] for p in programs},key=len,reverse=True)
            for college_name in named_colleges:
                if college_name.replace(' ','') in label:
                    active_college=college_name;break
            program_label=label.replace(active_college or '', '') if active_college else label
            candidates=[p for p in programs if p['college']==active_college and p['name'] in program_label]
            if len(candidates)==1:
                p=candidates[0];values=[int(match[i]) for i in (1,2,3)]
                resolved.append(dict(college=p['college'],college_code=p['college_code'],code=p['code'],name=p['name'],**{str(y):v for y,v in zip((2024,2025,2026),values)},change=values[2]-values[1],page=source_page(joined.find(cutoff_part))))
            else:
                values=[int(match[i]) for i in (1,2,3)]
                college_codes={p['college_code'] for p in programs if p['college']==active_college}
                resolved.append(dict(college=active_college or '学院待确认',college_code=next(iter(college_codes)) if len(college_codes)==1 else '',code='',name=program_label,source_label=label,identity_status='pending_review',**{str(y):v for y,v in zip((2024,2025,2026),values)},change=values[2]-values[1],page=source_page(joined.find(cutoff_part))))
        if len(resolved)==len(cutoffs):cutoffs=resolved
    # Close a trailing parenthetical institute name when PDF extraction drops
    # only its final punctuation; this preserves the visible catalogue label.
    for item in programs + admissions + cutoffs:
        college_name=item.get('college')
        if isinstance(college_name,str) and college_name.count('(')>college_name.count(')'):
            item['college']=college_name+')'
    colleges = []
    for item in programs + admissions:
        pair = {"code": item.get("college_code"), "name": item.get("college")}
        if pair not in colleges:
            colleges.append(pair)
    warnings = ["这是通用模板自动解析结果；空值和学院归属必须在写稿前人工确认。", "每项数据均保留手册页码，确认前不会进入草稿。"]
    warnings += [f'第{r["page"]}页复试线“{r.get("college", "")}{r["name"]}”与目录专业名称未唯一对应；保留原名，不自动套用其他专业代码。' for r in cutoffs if r.get('identity_status')=='pending_review']
    cutoff_years=sorted({int(key) for row in cutoffs for key in row if re.fullmatch(r'20\d{2}',str(key))})
    admission_years=sorted({int(row.get('year',2026)) for row in admissions})
    result={"schema_version": "1.3", "parser_mode": "generic_template", "school": school, "colleges": colleges, "programs": programs, "admission_2026": admissions, "admission_years":admission_years, "cutoffs": cutoffs, "cutoff_years":cutoff_years, **context,"excluded_pages": [], "warnings": warnings, "review_status": "pending_user_review"}
    result['coverage']=_coverage(result,raw_text)
    if result['coverage']['missing_sections']:
        result['warnings'].append('未识别或未披露栏目：'+'、'.join(result['coverage']['missing_sections'])+'。生成时必须明确说明，不能静默省略。')
    return result

