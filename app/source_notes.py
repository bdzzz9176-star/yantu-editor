"""Move explicit source notes to a single final appendix without deleting evidence."""
import re

TITLE='资料来源与说明'

def sources_at_end(content: str) -> str:
    body=[]; notes=[]; appendix=[]; in_appendix=False; context=''
    for line in content.splitlines():
        stripped=line.strip()
        heading=re.match(r'^##\s+(数据说明|数据来源|资料来源与说明|参考资料|参考来源)\s*$',stripped)
        if heading:
            in_appendix=True
            continue
        if in_appendix and stripped.startswith('## '):
            in_appendix=False
        if in_appendix:
            appendix.append(line)
            continue
        if stripped.startswith('#'):
            context=re.sub(r'^#+\s*','',stripped)
        plain=re.sub(r'^[-*\s]+','',stripped).rstrip('* ')
        if re.match(r'^(?:数据|资料)?来源\**\s*[：:]',plain):
            note=f'{context}：{plain}' if context else plain
            if note not in notes: notes.append(note)
        else:
            body.append(line)
    if not notes and not appendix:
        return content.rstrip()+'\n'
    tail='\n'.join(appendix).strip()
    entries='\n\n'.join(notes)
    joined='\n\n'.join(x for x in (entries,tail) if x)
    chunks=[chunk.strip() for chunk in re.split(r'\n\s*\n',joined) if chunk.strip()]
    joined='\n\n'.join(dict.fromkeys(chunks))
    return '\n'.join(body).rstrip()+f'\n\n## {TITLE}\n\n'+joined+'\n'

