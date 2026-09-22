"""Offline OCR fallback for PDF pages whose tables have no usable text layer."""
from __future__ import annotations
import os,subprocess,tempfile,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
PDFTOPPM=RUNTIME/'native/poppler/Library/bin/pdftoppm.exe'
NODE=RUNTIME/'node/bin/node.exe'
TESSERACT_JS=RUNTIME/'node/node_modules/tesseract.js/src/index.js'
LANG=ROOT/'vendor/ocr/node_modules/@tesseract.js-data/chi_sim/4.0.0_best_int'


def available()->bool:
    return all(x.is_file() for x in (PDFTOPPM,NODE,TESSERACT_JS,LANG/'chi_sim.traineddata.gz'))


def ocr_pdf_page(pdf:Path,page_number:int,top_fraction:float|None=None,start_fraction:float=0,psm:str='6')->str:
    if not available():return ''
    with tempfile.TemporaryDirectory(prefix='yantu_ocr_') as folder:
        target=Path(folder)/'page'
        subprocess.run([str(PDFTOPPM),'-f',str(page_number),'-l',str(page_number),'-r','320','-png','-singlefile',str(pdf),str(target)],check=True,capture_output=True,timeout=90)
        image=Path(str(target)+'.png')
        if top_fraction:
            from PIL import Image
            with Image.open(image) as source:
                source.crop((0,int(source.height*start_fraction),source.width,int(source.height*top_fraction))).save(image)
        env=os.environ.copy();env.update({'TESSERACT_JS':str(TESSERACT_JS),'TESSERACT_LANG_PATH':str(LANG),'TESSERACT_CACHE_PATH':str(ROOT/'vendor/ocr/cache'),'TESSERACT_PSM':psm})
        result=subprocess.run([str(NODE),str(ROOT/'tools/ocr_page.mjs'),str(image)],check=True,capture_output=True,text=True,encoding='utf-8',env=env,timeout=180)
        return result.stdout.strip()


def enrich_sparse_admission_pages(pdf:Path,pages:list[dict])->list[dict]:
    """OCR only sparse pages that visibly belong to an admission table."""
    for page in pages:
        text=page.get('text','')
        admission_candidate=len(text)<1600 and bool(re.search(r'20\d{2}\s*年\s*[|｜]?\s*一志愿',text))
        cutoff_candidate=len(text)<1600 and bool(re.search(r'(?:近[\u4e00-三两\d]年)?(?:复试|录取)(?:分数)?线(?:变化)?(?:情况)?',text))
        if admission_candidate or cutoff_candidate:
            ocr=ocr_pdf_page(pdf,int(page['page_number']),0.36 if cutoff_candidate and not admission_candidate else None,0.08 if cutoff_candidate and not admission_candidate else 0,'11' if cutoff_candidate and not admission_candidate else '6')
            if ocr and len(ocr)>len(text)*0.4:
                page['ocr_text']=ocr;page['extraction_mode']='text+ocr'
    return pages


def extract_admission_grids(pdf:Path,page_number:int)->list[dict]:
    """Read compact max/min/median/average/admitted-retest summary tables."""
    if not available():return []
    from PIL import Image,ImageOps
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='yantu_admission_grid_') as folder:
        prefix=Path(folder)/'page'
        subprocess.run([str(PDFTOPPM),'-f',str(page_number),'-l',str(page_number),'-r','160','-png','-singlefile',str(pdf),str(prefix)],check=True,capture_output=True,timeout=90)
        image=Image.open(str(prefix)+'.png').convert('RGB');gray=np.array(image.convert('L'));height,width=gray.shape
        lines=[int((a+b)/2) for a,b in _groups(np.where((gray<150).sum(1)>width*.30)[0]) if b-a<=3]
        tables=[]
        for index in range(len(lines)-2):
            top,middle,bottom=lines[index:index+3]
            if not (45<=middle-top<=120 and 25<=bottom-middle<=80):continue
            area=gray[top:bottom+1]
            columns=[int((a+b)/2) for a,b in _groups(np.where((area<150).sum(0)>area.shape[0]*.70)[0])]
            if len(columns)<6:continue
            # Choose six consecutive boundaries spanning five similarly sized cells.
            window=None
            for start in range(len(columns)-5):
                candidate=columns[start:start+6];gaps=[b-a for a,b in zip(candidate,candidate[1:])]
                if min(gaps)>40 and max(gaps)<min(gaps)*2.4:window=candidate;break
            if window:tables.append((middle,bottom,window))
        files=[];threshold_files=[]
        for table_index,(middle,bottom,columns) in enumerate(tables):
            for cell,(left,right) in enumerate(zip(columns,columns[1:])):
                crop=image.crop((left+2,middle+1,right-2,bottom-1)).resize(((right-left)*5,(bottom-middle)*5))
                path=Path(folder)/f'{table_index}_{cell}.png';gray_crop=ImageOps.autocontrast(crop.convert('L'));gray_crop.save(path);files.append(path)
                threshold_path=Path(folder)/f'{table_index}_{cell}_threshold.png';gray_crop.point(lambda x:0 if x<140 else 255).save(threshold_path);threshold_files.append(threshold_path)
        if not files:return []
        env=os.environ.copy();env.update({'TESSERACT_JS':str(TESSERACT_JS),'TESSERACT_LANG_PATH':str(LANG),'TESSERACT_CACHE_PATH':str(ROOT/'vendor/ocr/cache')})
        def recognize(mode):
            result=subprocess.run([str(NODE),str(ROOT/'tools/ocr_cells.mjs'),mode,*map(str,files)],check=True,capture_output=True,text=True,encoding='utf-8',env=env,timeout=180)
            return json.loads(result.stdout)
        cells=recognize('number');text_cells=recognize('text')
        original_files=files;files=threshold_files;threshold_cells=recognize('single');files=original_files;rows=[]
        def repair_zero_six(value,path):
            if not re.fullmatch(r'\d{3}',value):return value
            array=np.array(Image.open(path).convert('L'));mask=array<130;ys,xs=np.where(mask)
            if not len(xs):return value
            y0,y1=np.percentile(ys,[5,95]).astype(int);band=mask[y0:y1+1];columns=np.where(band.sum(0)>2)[0];groups=[]
            for x in columns:
                if not groups or x>groups[-1][-1]+2:groups.append([int(x)])
                else:groups[-1].append(int(x))
            groups=[g for g in groups if len(g)>3]
            if len(groups)!=len(value):return value
            chars=list(value)
            for position,char in enumerate(chars):
                if char!='0':continue
                glyph=band[:,groups[position][0]:groups[position][-1]+1];h,w=glyph.shape
                if glyph[:max(1,h//3),w//2:].mean()<.25:chars[position]='6'
            return ''.join(chars)
        for index in range(len(tables)):
            raw=cells[index*5:(index+1)*5];alternate=text_cells[index*5:(index+1)*5];threshold=threshold_cells[index*5:(index+1)*5]
            scores=[]
            def score_match(value):
                return re.search(r'(?<!\d)([2-4]\d{2}(?:\.\d+)?)(?!\d)',value) or re.match(r'([2-4]\d{2})(?:\d)$',value.strip())
            for offset,(value,text_value,threshold_value) in enumerate(zip(raw[:4],alternate[:4],threshold[:4])):
                match=score_match(value);text_match=score_match(text_value);threshold_match=score_match(threshold_value)
                number_text=match.group(1) if match else (text_match.group(1) if text_match else (threshold_match.group(1) if threshold_match else ''))
                number_text=repair_zero_six(number_text,original_files[index*5+offset])
                number=float(number_text) if number_text else None;text_number=float(text_match.group(1)) if text_match else None
                if number is None:number=text_number
                elif text_number is not None and number%10==0 and text_number==number+6:number=text_number
                scores.append(number)
            ratio_text=alternate[4] if '/' in alternate[4] else raw[4]
            ratio=re.search(r'(\d+)\s*/\s*(\d+)',ratio_text);admitted=retest=None
            if ratio:
                admitted_digits=ratio.group(1);digits=ratio.group(2)
                candidates=[]
                for left in range(1,min(3,len(admitted_digits))+1):
                    for right in range(1,min(3,len(digits))+1):
                        a=int(admitted_digits[:left]);r=int(digits[:right])
                        if 0<a<=r<=500 and r/a<=5:candidates.append((left+right,left,right,a,r))
                if candidates:_,_,_,admitted,retest=max(candidates,key=lambda x:(x[0],x[1],x[2]))
            else:
                digits=''.join(re.findall(r'\d',raw[4]));candidates=[]
                for left in range(1,min(3,len(digits)-1)+1):
                    for right in range(1,min(3,len(digits)-left)+1):
                        a=int(digits[:left]);r=int(digits[left:left+right])
                        if 0<a<=r<=500 and r/a<=5:candidates.append((len(digits)-left-right,a,r))
                if candidates:_,admitted,retest=min(candidates,key=lambda x:(x[0]==0,x[0],x[2]/x[1]))
            valid_scores=(scores[0] is not None and scores[1] is not None and scores[0]>=scores[1]
                          and all(value is None or scores[1]<=value<=scores[0] for value in scores[2:]))
            if sum(x is not None for x in scores)>=3 and valid_scores and admitted is not None and retest is not None and admitted<=retest:
                rows.append({'max':scores[0],'min':scores[1],'median':scores[2],'average':scores[3],
                             'admitted':admitted,'retest_count':retest,'ocr_cells':raw,'ocr_text_cells':alternate,'ocr_threshold_cells':threshold})
        return rows


def _groups(values):
    groups=[]
    for value in values:
        if not groups or value>groups[-1][-1]+1:groups.append([value])
        else:groups[-1].append(value)
    return [(x[0],x[-1]) for x in groups]


def extract_cutoff_grid(pdf:Path,page_number:int)->list[dict]:
    """Read score cells from a ruled year table without relying on PDF order."""
    if not available():return []
    from PIL import Image,ImageOps
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='yantu_grid_') as folder:
        prefix=Path(folder)/'page'
        subprocess.run([str(PDFTOPPM),'-f',str(page_number),'-l',str(page_number),'-r','240','-png','-singlefile',str(pdf),str(prefix)],check=True,capture_output=True,timeout=90)
        image=Image.open(str(prefix)+'.png').convert('RGB');gray=np.array(image.convert('L'));height,width=gray.shape
        horizontal=_groups(np.where((gray<170).sum(1)>width*.25)[0])
        wide=[g for g in horizontal if g[1]-g[0]>8]
        thin=[g for g in horizontal if g[1]-g[0]<=3]
        if len(wide)>=2:
            table_top=wide[0][1];table_bottom=wide[1][0]
            row_lines=[int((a+b)/2) for a,b in thin if table_top<a<table_bottom]
        elif wide:
            # Some profiles use one coloured title band and let the table run
            # to the edge of the embedded image. Infer the bottom from the
            # regular row separators instead of requiring a second band.
            table_top=wide[0][1]
            row_lines=[int((a+b)/2) for a,b in thin if table_top<a<height*.72]
            if len(row_lines)<4:return []
            gaps=[b-a for a,b in zip(row_lines[1:],row_lines[2:]) if 8<b-a<100]
            row_height=int(sorted(gaps)[len(gaps)//2]) if gaps else 0
            table_bottom=min(height,row_lines[-1]+row_height)
        else:return []
        if len(row_lines)<3:return []
        # Data rows start after the two header separators and end at footer.
        data_lines=row_lines[1:]+[table_bottom]
        if len(data_lines)<2:return []
        area=gray[table_top:table_bottom]
        vertical_fraction=.45 if len(wide)>=2 else .72
        vertical=_groups(np.where((area<170).sum(0)>area.shape[0]*vertical_fraction)[0])
        columns=[int((a+b)/2) for a,b in vertical]
        if len(columns)<6:return []
        header_text=ocr_pdf_page(pdf,page_number,.45,.08,'11')
        period=re.search(r'(20\d{2})\s*[-—–]\s*(20\d{2})',header_text)
        short_period=re.search(r'(?<!\d)(2\d)\s*[-—–]\s*(2\d)(?!\d)',header_text)
        if period:years=list(range(int(period.group(1)),int(period.group(2))+1))
        elif short_period:years=list(range(2000+int(short_period.group(1)),2000+int(short_period.group(2))+1))
        else:years=sorted(set(int(x) for x in re.findall(r'20\d{2}',header_text)))[:3]
        if len(years)<2:return []
        # Locate the program-name column by geometry. It is the widest
        # full-height cell; score columns immediately follow it. This works
        # with or without a separate merged college column.
        gaps=[b-a for a,b in zip(columns,columns[1:])]
        identity_index=max(range(len(gaps)),key=gaps.__getitem__)
        if identity_index+len(years)+1>=len(columns):return []
        identity=(columns[identity_index],columns[identity_index+1])
        score_columns=list(zip(columns[identity_index+1:identity_index+1+len(years)],columns[identity_index+2:identity_index+2+len(years)]))
        id_files=[];score_files=[];delta_files=[];delta_signs=[];row_ranges=list(zip(data_lines[:-1],data_lines[1:]))
        for index,(top,bottom) in enumerate(row_ranges):
            crop=image.crop((identity[0]+2,top+2,identity[1]-2,bottom-2));path=Path(folder)/f'id_{index}.png';ImageOps.autocontrast(crop.convert('L')).save(path);id_files.append(path)
            for col,(left,right) in enumerate(score_columns):
                crop=image.crop((left+2,top+2,right-2,bottom-2)).resize(((right-left)*4,(bottom-top)*4));path=Path(folder)/f'n_{index}_{col}.png';ImageOps.autocontrast(crop.convert('L')).save(path);score_files.append(path)
            delta_left=columns[identity_index+1+len(years)];delta_right=columns[identity_index+2+len(years)]
            crop=image.crop((delta_left+2,top+2,delta_right-2,bottom-2))
            pixels=np.array(crop);colored=pixels[(pixels.max(2)-pixels.min(2)>35)&(pixels.min(2)<150)]
            color_vote=float((colored[:,0]-colored[:,1]).mean()) if len(colored) else 0
            delta_signs.append(1 if color_vote>8 else -1 if color_vote<-8 else 0)
            crop=crop.resize(((delta_right-delta_left)*4,(bottom-top)*4));path=Path(folder)/f'd_{index}.png';ImageOps.autocontrast(crop.convert('L')).save(path);delta_files.append(path)
        env=os.environ.copy();env.update({'TESSERACT_JS':str(TESSERACT_JS),'TESSERACT_LANG_PATH':str(LANG),'TESSERACT_CACHE_PATH':str(ROOT/'vendor/ocr/cache')})
        def run(mode,files):
            result=subprocess.run([str(NODE),str(ROOT/'tools/ocr_cells.mjs'),mode,*map(str,files)],check=True,capture_output=True,text=True,encoding='utf-8',env=env,timeout=180)
            return json.loads(result.stdout)
        identities=run('text',id_files);numbers=run('text',score_files);change_cells=run('text',delta_files);rows=[]
        for i,identity_text in enumerate(identities):
            code=re.search(r'0?([018]\d{5}|\d{4}[A-Z]\d)',identity_text.replace(' ','').replace('O','0'))
            values=[];deltas=[];raw_cells=numbers[i*len(years):(i+1)*len(years)]
            for raw in raw_cells:
                match=re.search(r'(?<!\d)([2-4]\d{2})(?!\d)',raw)
                if not match:
                    compact=re.search(r'(?<!\d)([2-4]\d0\d)(?!\d)',raw)
                    value=int(compact.group(1).replace('0','',1)) if compact else None
                else:value=int(match.group(1))
                values.append(value)
                delta=re.search(r'([+-])\s*(\d{1,3})',raw)
                if delta:
                    magnitude=int(delta.group(2));sign=1 if delta.group(1)=='+' else -1
                    if magnitude>100:
                        candidates=(int(delta.group(2)[:2]),int(delta.group(2)[-2:]))
                        previous=values[-2] if len(values)>1 else None
                        magnitude=min(candidates,key=lambda x:abs((values[-1]-sign*x)-(previous or values[-1])))
                    deltas.append(sign*magnitude)
                else:deltas.append(None)
            separate_delta=re.search(r'([+-])?\s*(\d{1,3})',change_cells[i])
            if separate_delta and int(separate_delta.group(2))>0 and values[-2] is not None:
                magnitude=int(separate_delta.group(2));raw_change=change_cells[i]
                sign=-1 if ('-' in raw_change or any(x in raw_change for x in ('下降','减少','降','下','干干','干库'))) else 1 if ('+' in raw_change or any(x in raw_change for x in ('增加','上涨','加','涨'))) else delta_signs[i] or 1
                previous_candidates=[values[-2]]+([values[-2]+6] if values[-2]%10==0 else [])
                current_candidates=([values[-1]]+([values[-1]+6] if values[-1] is not None and values[-1]%10==0 else [])) if values[-1] is not None else []
                pair=next(((a,b) for a in previous_candidates for b in current_candidates if b-a==sign*magnitude),None)
                if pair:values[-2],values[-1]=pair
                else:
                    inferred=values[-2]+sign*magnitude
                    if 200<=inferred<=500:values[-1]=inferred
            for column in range(1,len(values)):
                if values[column] is not None and deltas[column] is not None:values[column-1]=values[column]-deltas[column]
            for column in range(len(values)-1):
                if values[column] is not None and values[column]%10==0 and values[column+1]==values[column]+6:
                    values[column]=values[column+1]
            rows.append({'code':code.group(1) if code else '','years':years,'values':values,'ocr_identity':identity_text,'ocr_cells':raw_cells,'ocr_change':change_cells[i]})
        return rows

