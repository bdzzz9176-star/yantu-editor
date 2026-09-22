from __future__ import annotations

from typing import Any


def build_task_outline(task: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    from admission_model import normalize_facts
    facts=normalize_facts(facts,require_identity=False)
    school = task.get("school") or facts.get("school") or "目标院校"
    year = task.get("target_year") or "2027"
    programs = facts.get("programs", [])
    admissions = facts.get("admission_2026", [])
    cutoffs = facts.get("cutoffs", [])
    college_names = list(dict.fromkeys(item.get("college") for item in programs if item.get("college")))
    if not college_names and facts.get("college"):
        college_names = [facts["college"]]
    codes = list(dict.fromkeys(item.get("code") for item in programs if item.get("code")))
    program_label = "、".join(codes[:4]) or "电子通信相关专业"
    conclusions = []
    if programs:
        conclusions.append(f"手册覆盖{len(programs)}组招生专业/学院组合，择专业时应同时比较统招人数、初试科目和学院归属。")
    if admissions:
        lowest = min(admissions, key=lambda item: item["min"])
        highest = max(admissions, key=lambda item: item["average"])
        conclusions.extend([
            f"2026年录取最低分较低的是{lowest.get('college', '')}{lowest.get('code', '')}（{lowest['min']}分），但最低分不能代表普遍录取难度。",
            f"录取平均分较高的是{highest.get('college', '')}{highest.get('code', '')}（{highest['average']}分），需要结合复录比判断竞争强度。",
        ])
    if cutoffs:
        conclusions.append("近三年复试线存在专业间差异，正文应解释趋势，不把单年低分包装成稳妥上岸。")
    conclusions.append("所有判断仅依据已确认的手册字段；正式招生目录变化和待确认口径必须在发布前复核。")
    sections = [
        {"id": "school_profile", "heading": "学校简介与学科实力", "purpose": "简要介绍学校、学院和学科情况。", "data_points": college_names or [school]},
        {"id": "program_overview", "heading": f"{year}初复试科目", "purpose": "按学院比较专业代码、初试科目和复试科目。", "data_points": codes or ["专业代码待确认"]},
        {"id": "books", "heading": "考试科目及参考书目", "purpose": "集中列出专业课和复试参考书。", "data_points": ["考试科目", "参考书目"]},
    ]
    if cutoffs:
        sections.append({"id": "cutoff_trend", "heading": "近三年复试线", "purpose": "比较2024—2026复试线及变化。", "data_points": ["2024复试线", "2025复试线", "2026复试线"]})
    if admissions:
        sections.extend([
            {"id": "admission", "heading": "2026拟录取分析", "purpose": "比较最高、最低、中位、平均分以及复试和录取人数。", "data_points": ["最高/最低/中位/平均", "复试人数", "录取人数", "录取率"]},
            {"id": "subject", "heading": "专业课难度", "purpose": "简要比较不同专业课的知识结构和备考要求。", "data_points": ["考试科目", "参考书目"]},
        ])
    sections.extend([
        {"id":"adjustment","heading":"调剂情况","purpose":"有数据时简要说明调剂情况。","data_points":[]},
        {"id":"retest","heading":"复试内容","purpose":"说明复试科目、权重和总成绩计算。","data_points":["复试科目","总成绩公式"]},
        {"id":"history","heading":"往年录取情况","purpose":"有历年录取数据时简要比较。","data_points":[]},
        {"id":"overall","heading":"总体难度分析","purpose":"按范文方式概括专业课、复试线、招生规模和录取结果。","data_points":[]},
    ])
    tables = ["学院、专业代码与初复试科目总览表"]
    if cutoffs:
        tables.append("2024—2026复试线对比表")
    if admissions:
        tables.extend(["2026一志愿录取与分数统计表", "专业课分数与备考要求对比表"])
    charts = [{'type':'admission_bands','title':f'{r.get("college", "")} {r["code"]} {r.get("name", "")} 2026一志愿分数段','purpose':'原始人数核验后按汇总表、分段图、解读排列；图表显隐由正文标记控制。'} for r in admissions]
    return {
        "task_id": task["task_id"], "status": "pending", "recommended_title_id": "title_b", "selected_title_id": None,
        "title_options": [
            {"id": "title_a", "title": f"{school}电子通信考研分析：招生、复试线与录取难度", "style": "信息完整型", "reason": "搜索信息明确，适合作为长期择校资料。"},
            {"id": "title_b", "title": f"{school}电子通信考研值得报吗？{len(programs)}组招生方向怎么选", "style": "问题切入型", "reason": "直接回应是否值得报考及方向选择问题。"},
            {"id": "title_c", "title": f"{school}{year}考研：{program_label}差距有多大？", "style": "选择指导型", "reason": "突出不同学院和专业之间的真实差异。"},
        ],
        "audience": f"准备报考{school}电子通信相关专业的{year}考研学生",
        "opening_angle": f"{school}的电子通信相关招生分布在{len(college_names) or 1}个学院、{len(programs)}组专业组合中。真正影响选择的不是学校名称本身，而是学院归属、统招规模、考试科目、复试线和录取分数之间的差异。",
        "core_conclusions": conclusions, "sections": sections, "tables": tables, "charts": charts,
        "required_disclosures": [],
    }

