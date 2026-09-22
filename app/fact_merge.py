"""Merge overlapping handbook sources with explicit, reviewable conflict records."""
from copy import deepcopy

LIST_KEYS={'colleges':lambda x:(x.get('code'),x.get('name')),
           'programs':lambda x:(x.get('college_code'),x.get('code')),
           'admission_2026':lambda x:(x.get('college_code'),x.get('code'),x.get('name')),
           'cutoffs':lambda x:(x.get('college_code') or x.get('college'),x.get('code'),x.get('name')),
           'course_notes':lambda x:(x.get('college_code'),),
           'score_formulas':lambda x:(x.get('college_code'),)}
META={'schema_version','parser_mode','warnings','coverage','review_status','excluded_pages'}
REVIEWED_FIELDS=('reporting','scope_label','scope_note','reader_scope_note','ordinary_admitted','special_admitted')


def preserve_reviewed_overrides(existing,new):
    """Re-parsing source files must not erase an editor's prior scope decision."""
    old_rows={(x.get('college_code'),x.get('code'),x.get('name')):x for x in (existing or {}).get('admission_2026',[])}
    for row in new.get('admission_2026',[]):
        old=old_rows.get((row.get('college_code'),row.get('code'),row.get('name')))
        if not old:continue
        for field in REVIEWED_FIELDS:
            if field in old:row[field]=deepcopy(old[field])
    return new


def merge_fact_sets(school,sets):
    """Later selected material wins a conflicting field; every difference remains visible."""
    result={'schema_version':'1.3','parser_mode':'multi_source_merge','school':school};conflicts=[]
    for section,key_fn in LIST_KEYS.items():
        merged={}
        for material_id,facts in sets:
            for raw in facts.get(section,[]):
                item=deepcopy(raw);key=key_fn(item);previous=merged.get(key)
                if previous:
                    for field,value in item.items():
                        old=previous.get(field)
                        if field not in ('material_id','source_material_ids') and old not in (None,'') and value not in (None,'') and old!=value:
                            conflicts.append({'section':section,'identity':list(key),'field':field,'values':[old,value],'selected_material_id':material_id})
                    sources=list(dict.fromkeys(previous.get('source_material_ids',[previous.get('material_id')])+[material_id]))
                    previous.update({k:v for k,v in item.items() if v not in (None,'')});previous['source_material_ids']=[x for x in sources if x]
                else:
                    item['material_id']=material_id;item['source_material_ids']=[material_id];merged[key]=item
        result[section]=list(merged.values())
    profile={}
    for material_id,facts in sets:
        for field,value in (facts.get('school_profile') or {}).items():
            if field in profile and profile[field]!=value:conflicts.append({'section':'school_profile','identity':[school],'field':field,'values':[profile[field],value],'selected_material_id':material_id})
            profile[field]=deepcopy(value)
    result['school_profile']=profile
    result['source_conflicts']=conflicts
    result['source_material_ids']=[material_id for material_id,_ in sets]
    result['warnings']=['已合并多份资料；相同字段不重复，冲突字段采用任务中靠后的资料并保留冲突记录供确认。']
    if conflicts:
        result['warnings'].append(f'发现{len(conflicts)}项跨资料差异，确认事实前必须逐项核对。')
        result['warnings'] += [f"跨资料差异：{x['section']} / {x['field']}：{x['values'][0]} → {x['values'][1]}（当前采用后者）" for x in conflicts[:20]]
    result['excluded_pages']=[];result['review_status']='pending_user_review'
    return result

