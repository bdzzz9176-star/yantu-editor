"""One canonical Markdown representation for tables, chart intent and Word export."""
import re
from decimal import Decimal, InvalidOperation
from admission_tables import admission_block,FULL_HEADERS,LEGACY_HEADERS,admission_values,reporting_row
from handbook_tables import standard_blocks
from source_notes import sources_at_end

FORMAT='admission_markers_v1'
MARKER=re.compile(r'^\[录取分段图:([^\]]+)\]\s*$',re.M)
SECTION=re.compile(r'^\[录取分析:([^\]]+)\]\s*$',re.M)
HANDBOOK_SECTION=re.compile(r'^\[手册栏目:([^\]]+)\]\s*$',re.M)
HEADERS=LEGACY_HEADERS
OLD_FULL_HEADERS=FULL_HEADERS+['依据']


def resolve_asset(token,assets):
    matches=[a for a in assets if a['key']==token or a['code']==token]
    if len(matches)!=1:
        raise ValueError('图表标记需明确学院、专业和页码，不能仅用重复专业代码：'+token)
    return matches[0]


def table_asset(identity,assets):
    # Anchoring prevents 电子学院 matching 软件与微电子学院.
    matches=[a for a in assets if re.match(r'^'+re.escape(a['college'])+r'\s*[－—–-]?\s*'+re.escape(a['code'])+r'(?!\d)',identity.strip())]
    if len(matches)>1:
        compact=lambda s:re.sub(r'\s+','',s.replace('（','(').replace('）',')'))
        identity_name=compact(identity.split(matches[0]['code'],1)[-1]) if matches else compact(identity)
        exact=[a for a in matches if compact(a['name'])==identity_name]
        if exact:matches=exact
        else:
            contained=[a for a in matches if compact(a['name']) in compact(identity)]
            if contained:
                longest=max(len(compact(a['name'])) for a in contained)
                matches=[a for a in contained if len(compact(a['name']))==longest]
    if len(matches)!=1:raise ValueError('录取汇总表身份无法唯一对应已确认事实：'+identity)
    return matches[0]


def remove_redundant_fact_tables(content):
    """Drop model-copied versions of tables that handbook placeholders own."""
    lines=content.splitlines();output=[];index=0
    while index<len(lines):
        if lines[index].strip().startswith('|') and index+1<len(lines) and re.fullmatch(r'\s*\|?[\s:|-]+\|?\s*',lines[index+1]):
            block=[]
            while index<len(lines) and lines[index].strip().startswith('|'):
                block.append(lines[index]);index+=1
            header=[c.strip() for c in block[0].strip().strip('|').split('|')]
            copied=(('专业代码' in header and any(x in header for x in ('拟招人数','统招人数'))) or
                    any('2024复试线' in x for x in header) or
                    ('专业课最高分' in header and '数学平均分' in header))
            if not copied:output.extend(block)
            continue
        output.append(lines[index]);index+=1
    return '\n'.join(output)


def compile_draft(content,facts,assets,add_default_charts=False,require_handbook_sections=False):
    """Validate tables; normalize legacy markers; never infer charts on a revision."""
    content=remove_redundant_fact_tables(content)
    for row in facts.get('admission_2026',[]):
        if row.get('scope_note'):content=content.replace(row['scope_note'],'')
    by_key={a['key']:r for a,r in zip(assets,facts.get('admission_2026',[]))}
    def expand(match):
        asset=resolve_asset(match[1],assets);row=by_key[asset['key']]
        chart='\n'+f'[录取分段图:{asset["key"]}]\n' if asset.get('bands') else ''
        return admission_block(facts['school'],row['college'],row['name'],row,[])+chart
    content=SECTION.sub(expand,content)
    blocks=standard_blocks(facts);used=[]
    def expand_handbook(match):
        key=match[1]
        if key not in blocks:raise ValueError('当前手册事实中不存在栏目：'+key)
        if key in used:return ''
        used.append(key);return blocks[key]
    content=HANDBOOK_SECTION.sub(expand_handbook,content)
    requested={resolve_asset(m[1],assets)['key'] for m in MARKER.finditer(content)}
    use_defaults=add_default_charts
    lines=content.splitlines();output=[];seen=set();index=0
    while index<len(lines):
        line=lines[index]
        if MARKER.fullmatch(line.strip()):index+=1;continue
        if line.strip().startswith('|') and index+1<len(lines) and re.fullmatch(r'\s*\|?[\s:|-]+\|?\s*',lines[index+1]):
            block=[]
            while index<len(lines) and lines[index].strip().startswith('|'):
                block.append(lines[index]);index+=1
            cells=[[c.strip() for c in x.strip().strip('|').split('|')] for x in block]
            header=cells[0] if cells else []
            admission_fields=set(HEADERS[1:]+FULL_HEADERS[1:])
            looks_admission=bool(header and header[0] in ('学院及专业','学院与专业') and admission_fields.intersection(header[1:]))
            if header in (HEADERS,FULL_HEADERS,OLD_FULL_HEADERS):
                if len(cells)!=3 or len(cells[2])!=len(header):
                    raise ValueError('录取汇总表必须使用完整标准列并按学院专业单独列出')
                asset=table_asset(cells[2][0],assets);key=asset['key'];row=by_key[key]
                if key in seen:raise ValueError('同一录取样本的汇总表重复：'+key)
                if header in (FULL_HEADERS,OLD_FULL_HEADERS):
                    expected=admission_values(cells[2][0],row)[1:]
                    actual=cells[2][1:-1] if header==OLD_FULL_HEADERS else cells[2][1:]
                    if row.get('reporting'):
                        source=dict(row);source.pop('reporting',None)
                        source_expected=admission_values(cells[2][0],source)[1:]
                        if actual==source_expected:actual=expected
                    if actual==expected:
                        cells[2]=[cells[2][0]]+expected
                        block=['| '+' | '.join(FULL_HEADERS)+' |','|---|---:|---:|---:|---:|---:|','| '+' | '.join(str(x) for x in cells[2])+' |']
                else:
                    display=reporting_row(row)
                    expected=[display['retest_count'],display['admitted'],f'{display["retest_count"]/display["admitted"]:.2f}' if display['admitted'] and display.get('retest_count') is not None else '—',display['max'],display['min'],display['average']]
                for value,want in zip(actual if header in (FULL_HEADERS,OLD_FULL_HEADERS) else cells[2][1:],expected):
                    try:equal=Decimal(value)==Decimal(str(want))
                    except InvalidOperation:equal=value==str(want)
                    if not equal:raise ValueError(f'{key}录取表数字与已确认事实不一致：{value}，应为{want}')
                seen.add(key);output.extend(block)
                if asset.get('bands') and (use_defaults or key in requested) and reporting_row(row).get('retest_count',0)>=10:
                    output.extend(['',f'[录取分段图:{key}]'])
            elif looks_admission:
                raise ValueError('录取汇总表必须使用完整标准列并按学院专业单独列出')
            else:
                if '依据' in header:
                    source_index=header.index('依据');public=[[v for i,v in enumerate(row) if i!=source_index] for row in cells]
                    output.extend(['| '+' | '.join(public[0])+' |','|'+'|'.join('---' for _ in public[0])+'|'])
                    output.extend('| '+' | '.join(row)+' |' for row in public[2:])
                    sources=[row[source_index] for row in cells[2:] if len(row)>source_index]
                    if sources:output.extend(['',f'来源：表格数据：'+ '、'.join(dict.fromkeys(sources))+'。'])
                else:output.extend(block)
            continue
        output.append(line);index+=1
    missing=set(by_key)-seen
    if missing:raise ValueError('缺少学院专业独立录取汇总表：'+'、'.join(sorted(missing)))
    if require_handbook_sections and set(blocks)-set(used):raise ValueError('缺少手册标准栏目：'+'、'.join(set(blocks)-set(used)))
    return sources_at_end('\n'.join(output))

