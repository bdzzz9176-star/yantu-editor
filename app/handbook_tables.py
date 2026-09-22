"""Deterministic handbook sections shared by every single-school article."""
import re


def _shown(value):
    return '—' if value is None or value == '' else str(value)


def _college_label(name, code):
    return f'{name}（{code}）' if code not in (None, '', '待确认') else str(name)


def _professional_subject(program):
    text=str(program.get('initial_subjects',''))
    match=re.search(r'(?<!\d)(8\d{2})\s*([^；;，,]*)',text)
    return (match.group(1)+match.group(2)).strip() if match else '—'


def _table(title,headers,rows):
    if not rows:return ''
    sources=[]
    if '依据' in headers:
        source_index=headers.index('依据');sources=[str(row[source_index]) for row in rows]
        headers=[value for i,value in enumerate(headers) if i!=source_index]
        rows=[[value for i,value in enumerate(row) if i!=source_index] for row in rows]
    lines=[f'**{title}**','', '| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|']
    lines += ['| '+' | '.join(str(v).replace('\n','；') for v in row)+' |' for row in rows]
    if sources:lines += ['',f'来源：{title}：'+'、'.join(dict.fromkeys(sources))+'。']
    return '\n'.join(lines)+'\n'


def standard_blocks(facts):
    school=facts['school'];blocks={};profile=facts.get('school_profile') or {};rows=[]
    if profile.get('introduction'):rows.append(['学校简介',profile['introduction'],'手册院校基本信息页'])
    for label,key in [('所在地区','location'),('排名情况','ranking'),('录取特点','admission_policy'),('住宿情况','accommodation')]:
        if profile.get(key):rows.append([label,profile[key],'补充资料'])
    for x in profile.get('discipline_evaluations',[]):rows.append(['学科评估',f'{x["discipline"]}：{x["grade"]}',f'第{x["page"]}页'])
    if rows:blocks['院校基本信息']=_table(f'{school}院校基本信息',['项目','内容','依据'],rows)
    programs=facts.get('programs',[])
    if programs:blocks['招生专业与考试科目']=_table(f'{school}招生专业与初复试科目',['学院/校区','专业','学制','研究方向','初试科目','上年/当年统招人数','复试科目','备注','依据'],[[p['college'],f'{p["code"]} {p.get("name","")}',_shown(p.get('duration')),_shown(p.get('direction')),_shown(p.get('initial_subjects')),_shown(p.get('planned_previous'))+'/'+_shown(p.get('planned')),_shown(p.get('retest')),p.get('note',''),f'第{p["page"]}页'] for p in programs])
    books=facts.get('reference_books',[])
    if books:blocks['参考书目']=_table(f'{school}考试科目及参考书目',['阶段','科目','参考书目/说明'],[[x['stage'],x['subject'],x['books']] for x in books])
    notes=facts.get('course_notes',[])
    if notes:blocks['专业课与参考资料']=_table(f'{school}考试科目及参考书目',['类别','科目与参考书目/说明','依据'],[['初试及复试',x['content'],f'第{x["page"]}页'] for x in notes])
    formulas=facts.get('score_formulas',[])
    if formulas:blocks['复试总成绩公式']=_table(f'{school}复试总成绩计算',['学院','总成绩计算公式','依据'],[[_college_label(x['college'],x.get('college_code')),x['formula'],f'第{x["page"]}页'] for x in formulas])
    cutoffs=facts.get('cutoffs',[])
    if cutoffs:
        years=facts.get('cutoff_years') or sorted({int(k) for x in cutoffs for k in x if re.fullmatch(r'20\d{2}',str(k))})
        blocks['近三年复试线']=_table(f'{school}近三年复试线',['学院与专业',*map(str,years),'较上年变化','依据'],[[_college_label(x.get('college',''),x.get('college_code'))+f' {x.get("code","")} {x.get("name","")}',*[_shown(x.get(str(year))) for year in years],_shown(x.get('change')),f'第{x["page"]}页'] for x in cutoffs])
    admissions=facts.get('admission_2026',[])
    if admissions:
        programs={(x.get('college_code'),x.get('code')):x for x in programs}
        blocks['专业课分数']=_table(f'{school}专业课成绩统计',['学院','专业','方向+专业课','专业课最高分','专业课最低分','专业课平均分'],[[x['college'],f'{x["code"]} {x.get("name","")}',f'{x.get("name","")} + {_professional_subject(programs.get((x.get("college_code"),x.get("code")),{}))}',_shown(x.get('professional_max')),_shown(x.get('professional_min')),_shown(x.get('professional_average'))] for x in admissions])
    adjustment=facts.get('adjustment',[])
    if adjustment:blocks['调剂情况']=_table(f'{school}调剂情况',['学院','专业','调剂类型','说明'],[[x['scope'],x['program'],x['type'],x['note']] for x in adjustment])
    retest=facts.get('retest_details',[])
    if retest:blocks['复试内容']=_table(f'{school}复试内容',['学院','总成绩计算方式','复试要点'],[[x['college'],x['formula'],x['details']] for x in retest])
    history=facts.get('history',[])
    if history:blocks['往年录取情况']=_table(f'{school}近三年复试线与录取数据',['招生学院','专业代码及名称','专业课','2024复试线','2025复试线','2026复试线','2024录取人数','2025录取人数','2026录取人数','2024复录比','2025复录比','2026复录比','2024录取均分','2025录取均分','2026录取均分'],history)
    return blocks


def standard_placeholders(facts):
    return [{'key':key,'placeholder':f'[手册栏目:{key}]'} for key in standard_blocks(facts)]

