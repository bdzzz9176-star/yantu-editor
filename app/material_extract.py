"""Extract a target school's chapter from a Word handbook."""
import re
from pathlib import Path


def extract_docx_school_section(path:Path,school:str)->str:
    from docx import Document
    from docx.oxml.ns import qn
    chunks=[]
    try:
        doc=Document(path)
        for child in doc.element.body.iterchildren():
            if child.tag.endswith('tbl'):
                for cell in child.iter(qn('w:tc')):
                    value=''.join(node.text for node in cell.iter(qn('w:t')) if node.text).strip()
                    if value:chunks.append(value)
            else:
                values=[node.text for node in child.iter(qn('w:t')) if node.text]
                if values:chunks.append(''.join(values))
    except (KeyError, ValueError):
        # Some third-party Word files contain broken relationships (for example
        # a target named NULL) although word/document.xml is still intact.
        from zipfile import ZipFile, BadZipFile
        from xml.etree import ElementTree as ET
        try:
            with ZipFile(path) as package:data=package.read('word/document.xml')
        except (BadZipFile,KeyError) as error:raise ValueError(f'Word文件结构损坏，无法提取正文：{error}') from error
        root=ET.fromstring(data);ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        for block in root.iter():
            if block.tag == ns+'p':
                value=''.join(node.text or '' for node in block.iter(ns+'t')).strip()
                if value:chunks.append(value)
    text='\n'.join(chunks);positions=[m.start() for m in re.finditer(re.escape(school),text)]
    if not positions:raise ValueError(f'Word资料中未找到学校章节：{school}')
    markers=('院校基本信息','初复试介绍','拟录取分析','录取分数线')
    def section_score(pos):
        sample=text[pos:pos+3000];distances=[sample.find(marker) for marker in markers if marker in sample]
        return (len(distances),-min(distances) if distances else -999999,pos)
    start=max(positions,key=section_score)
    remainder=text[start+len(school):]
    next_section=re.search(r'\n[^\n]{0,26}?(?:大学|学院)\n(?:[^\n]*\n){0,4}(?:一、)?院校基本信息',remainder)
    # A single school chapter is never expected to consume the remainder of a
    # very large handbook. The cap prevents a malformed heading from feeding
    # hundreds of thousands of unrelated characters into the parser.
    end=start+len(school)+(next_section.start() if next_section else min(len(remainder),100_000))
    return text[start:end].strip()

