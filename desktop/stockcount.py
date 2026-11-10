#!/usr/bin/env python3
"""Hangcha StockCount desktop tool. Python 3.10+ standard library only.
Commands:
  python stockcount.py prepare inventory.xlsx --out inventory_2026.json
  python stockcount.py merge inventory.xlsx exports_folder --out comparison.xlsx
  python stockcount.py inspect inventory.xlsx
  python stockcount.py gui
Mapping customization in mapping.json next to stockcount.py.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,json,os,re,sys,traceback,zipfile
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL_NS='{http://schemas.openxmlformats.org/package/2006/relationships}'
ALIASES={
 'erp':['商品明细码ERP','商品明细码','ERP No.','ERP No','ERP','ERP-Nr','ERP Nummer','ERP 编码','ERP号','ERP编号'],
 'partNo':['Part.No.','Part No.','Part No','Part Number','Part-Nr','Part-Nr.','Item No','物料号','零件号','配件号','图号'],
 'name':['Description','Part Name','Name','Item Description','Description EN','名称','配件名称','零件名称','品名'],
 'location':['Rack No.','Rack No','Location','Storage Location','Bin Location','Warehouse Location','Lagerort','Lagerplatz','库位','库位号','货位','货位号'],
 'referenceWeight':['重量','Weight kg','Weight (kg)','Net Weight (kg)'],
 'referenceDimensions':['尺寸 cm','尺寸cm','尺寸','Dimensions (cm)','Dimensions cm'],
 'bookQty':['存','Stock Qty','Stock Quantity','Quantity','QTY','Available Stock','Inventory Qty','Balance','Stock','库存数量','库存','数量','结存数量']}
CONFIG_PATH=Path(__file__).with_name('mapping.json')
def normalized(s):return re.sub(r'[^a-z0-9\u4e00-\u9fff]+','',str(s or '').lower())
def cell_col(ref):
    x=0
    for c in re.match(r'[A-Z]+',ref).group():x=x*26+ord(c)-64
    return x-1

def xlsx_sheets(path):
    """Read cell values without third-party packages; supports ordinary XLSX worksheets."""
    with zipfile.ZipFile(path) as z:
        workbook=ET.fromstring(z.read('xl/workbook.xml'))
        relationships=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rels={r.attrib.get('Id'):r.attrib.get('Target') for r in relationships}
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si',NS):shared.append(''.join(t.text or '' for t in si.findall('.//m:t',NS)))
        for sh in workbook.findall('m:sheets/m:sheet',NS):
            name=sh.attrib['name'];rid=sh.attrib.get('{'+NS['r']+'}id')
            target=rels.get(rid,'')
            if target.startswith('/'):xmlpath=target.lstrip('/')
            elif target.startswith('xl/'):xmlpath=target
            else:xmlpath='xl/'+target
            if xmlpath not in z.namelist():continue
            root=ET.fromstring(z.read(xmlpath));rows=[]
            for row in root.findall('.//m:sheetData/m:row',NS):
                out={}
                for cell in row.findall('m:c',NS):
                    ref=cell.attrib.get('r','A1');index=cell_col(ref)
                    value=cell.find('m:v',NS)
                    inline=cell.find('m:is',NS)
                    typ=cell.attrib.get('t','')
                    if typ=='s' and value is not None:
                        try:text=shared[int(value.text)]
                        except (ValueError,IndexError,TypeError):text=''
                    elif typ=='inlineStr' and inline is not None:text=''.join(t.text or '' for t in inline.findall('.//m:t',NS))
                    elif value is not None:text=value.text or ''
                    else:text=''
                    out[index]=text
                if out:
                    width=max(out)+1
                    rows.append([out.get(i,'') for i in range(width)])
            yield name,rows

def csv_rows(path):
    for enc in ('utf-8-sig','utf-16','cp1252','gb18030'):
        try:
            with open(path,'r',encoding=enc,newline='') as f:
                sample=f.read(4000);f.seek(0)
                try:dialect=csv.Sniffer().sniff(sample,delimiters=',;\t')
                except csv.Error:dialect=csv.excel
                return list(csv.reader(f,dialect))
        except UnicodeError:continue
    raise ValueError('CSV 编码无法识别')

def source_sheets(path):
    ext=Path(path).suffix.lower()
    if ext=='.xlsx':return list(xlsx_sheets(path))
    if ext=='.csv':return [('Sp Stock CSV',csv_rows(path))]
    raise ValueError('库存清单只支持 .xlsx 或 .csv；请把 .xls 另存为 .xlsx')

def config():
    if CONFIG_PATH.exists():return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {}

def resolve_columns(rows,cfg):
    overrides=cfg.get('columns',{})
    best=None
    for i,row in enumerate(rows[:35]):
        headers=[normalized(x) for x in row]
        mapping={};score=0
        for field,aliases in ALIASES.items():
            choices=[overrides[field]] if field in overrides else aliases
            for a in choices:
                a=normalized(a)
                if a in headers:
                    mapping[field]=headers.index(a);score+=3;break
            if field not in mapping:
                for a in choices:
                    aa=normalized(a)
                    if len(aa)>=5:
                        matches=[j for j,h in enumerate(headers) if aa in h]
                        if len(matches)==1:mapping[field]=matches[0];score+=1;break
        if 'location' in mapping and ('erp' in mapping or 'partNo' in mapping):score+=8
        if best is None or score>best[0]:best=(score,i,mapping,row)
    if not best or 'location' not in best[2] or not ('erp' in best[2] or 'partNo' in best[2]):
        sample=' | '.join(' / '.join(map(str,r[:12])) for r in rows[:5]);raise ValueError('无法定位库位列及零件编号列。请用 inspect 查看表头，并编辑 mapping.json。表头样例：'+sample[:360])
    return best[1],best[2],best[3]

def value(row,idx):return str(row[idx]).strip() if idx is not None and idx<len(row) and row[idx] is not None else ''

def to_number(x):
    x=str(x).strip().replace(' ','')
    if not x:return None
    if ',' in x and '.' not in x:x=x.replace(',','.')
    else:x=x.replace(',','')
    try:return float(x)
    except ValueError:return None

def standardized_location(s):
    # Preserve original arbitrary suffix; spaces around visible delimiters only removed.
    return re.sub(r'\s+','',str(s or '')).upper()

def count_location_with_floor(r):
    """Separate incomplete locations on different physical floors, without inventing a rack level.

    Full locations (letter + row + rack-level digits) already encode the floor.
    """
    loc=standardized_location(r.get('location',''))
    if not re.match(r'^[A-P]\d{4}',loc):
        floor=r.get('physicalFloor')
        if str(floor) in ('1','2','3'):
            return f'{loc}（{floor}F，未指定货架层）'
    return loc

def location_candidates(raw):
    """Multiple rack references share ONE row quantity. Never allocate it across racks.
    Skip shorthand suffix segments that lack a distinct letter+row prefix.
    """
    raw=standardized_location(raw)
    parts=re.split(r'[/,，;；]+',raw)
    out=[]
    for item in parts:
        if re.match(r'^[A-P]\d{2}',item) and item not in out:
            out.append(item)
    return out

def build_inventory(path,include_all=False):
    cfg=config();sheets=source_sheets(path);filter_name=cfg.get('sheet_prefix','库存已有备件').lower();out=[];diagnostics=[]
    for name,rows in sheets:
        if not include_all and name!='Sp Stock CSV' and not name.lower().startswith(filter_name):continue
        if not rows:continue
        header_index,mapping,header=resolve_columns(rows,cfg)
        count=0
        for row in rows[header_index+1:]:
            erp=value(row,mapping.get('erp'));part=value(row,mapping.get('partNo'))
            loc=standardized_location(value(row,mapping.get('location')))
            if not loc or not(erp or part):continue
            if normalized(loc) in ('location','lagerort','库位','库位号'):continue
            out.append({'erp':erp,'partNo':part,'name':value(row,mapping.get('name')),'location':loc,'locations':location_candidates(loc),'bookQty':to_number(value(row,mapping.get('bookQty'))),'referenceWeight':value(row,mapping.get('referenceWeight')),'referenceDimensions':value(row,mapping.get('referenceDimensions')),'sourceSheet':name});count+=1
        diagnostics.append({'sheet':name,'rows':count,'headerRow':header_index+1,'columns':{k:header[v] if v<len(header) else '' for k,v in mapping.items()}})
    if not out:raise ValueError('未读取到有效库存行。请确认 Excel 包含「库存已有备件」工作表，并检查 mapping.json 中的 sheet_prefix 设置。')
    raw=json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    snapshot=hashlib.sha256(raw.encode()).hexdigest()[:16]
    return {'format':'hangcha-stockcount-catalog','version':1,'snapshotId':snapshot,'createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),'sourceName':Path(path).name,'items':out},diagnostics

def inspect(path):
    for name,rows in source_sheets(path):
        print(f'\n[{name}] {len(rows)} 行')
        for i,r in enumerate(rows[:7],1):print(f'  {i:>2}: '+ ' | '.join(str(x)[:35] for x in r[:20]))

def prepare(path,out):
    cat,diag=build_inventory(path);Path(out).parent.mkdir(parents=True,exist_ok=True);Path(out).write_text(json.dumps(cat,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'成功：{out}  行数：{len(cat["items"])}  基准ID：{cat["snapshotId"]}')
    for x in diag:print('  ',x)
    return cat

def records_from_folder(folder):
    # Re-exported snapshots may contain later edits or tombstones for the SAME record ID.
    # Different record IDs are independent counts, even for identical part/location/qty.
    chosen={};files=[];invalid=[];conflicting_ids=[]
    for p in sorted(Path(folder).rglob('*.json')):
        try:
            d=json.loads(p.read_text(encoding='utf-8-sig'))
            if d.get('format')!='hangcha-stockcount-export':continue
            files.append(p.name)
            for r in d.get('records',[]):
                ident=str(r.get('id','')).strip()
                if not ident:invalid.append([p.name,'缺少记录ID']);continue
                r={**r,'sourceFile':p.name}
                prev=chosen.get(ident)
                if prev is None:chosen[ident]=r;continue
                ts=str(r.get('updatedAt') or r.get('createdAt') or '')
                old_ts=str(prev.get('updatedAt') or prev.get('createdAt') or '')
                if ts>old_ts:chosen[ident]=r
                elif ts==old_ts and any(prev.get(k)!=r.get(k) for k in ('location','erp','partNo','qty','lengthCm','widthCm','heightCm','weightKg','deleted')):
                    conflicting_ids.append([ident,p.name,'同一ID、相同时间戳内容冲突：须人工复核'])
        except Exception as e:invalid.append([p.name,str(e)])
    results=[]
    blocked={x[0] for x in conflicting_ids}
    deleted_rows=[r for ident,r in chosen.items() if ident not in blocked and r.get('deleted')]
    for ident,r in chosen.items():
        if ident in blocked or r.get('deleted'):continue
        if not isinstance(r.get('qty'),int) or isinstance(r.get('qty'),bool) or r['qty']<0:
            invalid.append([r['sourceFile'],'数量必须为非负整数：'+ident]);continue
        results.append(r)
    return results,files,invalid,conflicting_ids,deleted_rows

def shelves_from_folder(folder):
    chosen={};problems=[];blocked=set()
    for p in sorted(Path(folder).rglob('*.json')):
        try:
            data=json.loads(p.read_text(encoding='utf-8-sig'))
            if data.get('format')!='hangcha-stockcount-export':continue
            for x in data.get('shelfCompletions',[]):
                ident=str(x.get('id','')).strip()
                if not ident:problems.append([p.name,'货架完成记录缺少ID']);continue
                current={**x,'sourceFile':p.name}
                old=chosen.get(ident)
                if old is None:chosen[ident]=current;continue
                new_ts=str(current.get('updatedAt') or current.get('completedAt') or '')
                old_ts=str(old.get('updatedAt') or old.get('completedAt') or '')
                if new_ts>old_ts:chosen[ident]=current
                elif new_ts==old_ts and current.get('deleted')!=old.get('deleted'):
                    problems.append([p.name,'货架完成记录同ID版本冲突：'+ident]);blocked.add(ident)
        except Exception as e:problems.append([p.name,'货架标记读取失败：'+str(e)])
    return [x for ident,x in chosen.items() if ident not in blocked and not x.get('deleted')],problems

def part_key(erp,part):return (str(erp or '').strip().upper(),str(part or '').strip().upper())
def normalize_part(erp,part,index):
    erp,part=part_key(erp,part)
    if erp and part:return (erp,part)
    if erp:
        matches=index.get(('erp',erp),set())
        if len(matches)==1:return next(iter(matches))
    if part:
        matches=index.get(('part',part),set())
        if len(matches)==1:return next(iter(matches))
    return (erp,part)

def summarize(cat,folder):
    rows,files,invalid,conflicting_ids,deleted_rows=records_from_folder(folder)
    shelf_marks,shelf_problems=shelves_from_folder(folder)
    invalid.extend(shelf_problems)
    stock=cat['items'];index=defaultdict(set)
    sessions={str(r.get('session','')).strip() for r in rows}
    if len(sessions)>1:
        raise ValueError('发现多个盘库批次：'+', '.join(sorted(sessions))+'。请分别放入文件夹后按批次汇总，防止跨年度重复累加。')
    for x in stock:
        k=part_key(x['erp'],x['partNo']);
        if k[0]:index[('erp',k[0])].add(k)
        if k[1]:index[('part',k[1])].add(k)
    baseline=defaultdict(float);stock_by_part=defaultdict(lambda:defaultdict(float));names={};unknown_book=[]
    for x in stock:
        k=normalize_part(x['erp'],x['partNo'],index);names.setdefault(k,x['name']);q=x['bookQty'];loc=standardized_location(x['location'])
        if q is None:unknown_book.append([x['erp'],x['partNo'],loc,x['sourceSheet']]);continue
        baseline[k]+=q
        # Multi-rack quantities belong to the part overall. Do not invent a rack-level split.
        if len(x.get('locations',[]))==1 and x['locations'][0]==loc:stock_by_part[k][loc]+=q
    count_groups=defaultdict(list);movement=[];snapshot_mismatch=[];raw=[]
    for r in rows:
        k=normalize_part(r.get('erp'),r.get('partNo'),index)
        loc=count_location_with_floor(r)
        qty=r['qty'];group=(str(r.get('session','')),loc,k)
        count_groups[group].append(r)
        raw.append([r.get('session',''),r.get('worker',''),r.get('location',''),r.get('physicalFloor',''),r.get('erp',''),r.get('partNo',''),r.get('partName',''),r.get('lengthCm') if r.get('lengthCm') is not None else '',r.get('widthCm') if r.get('widthCm') is not None else '',r.get('heightCm') if r.get('heightCm') is not None else '',r.get('weightKg') if r.get('weightKg') is not None else '',qty,r.get('mode',''),r.get('originalLocation',''),r.get('note',''),r.get('updatedAt',''),r.get('id',''),r['sourceFile']])
        if r.get('snapshotId') and r['snapshotId']!=cat['snapshotId']:snapshot_mismatch.append([r['sourceFile'],r['id'],r['snapshotId'],cat['snapshotId']])
        if r.get('mode') in ('temp','move'):movement.append([r.get('worker'),r.get('erp'),r.get('partNo'),r.get('originalLocation'),loc,qty,r.get('mode'),r.get('note'),r.get('id')])
    conflicts=[];actual=defaultdict(float);counted_locations=defaultdict(set);counted_parts=set();complete_parts=set()
    for (session,loc,k),group in count_groups.items():
        counted_parts.add(k)
        if len(group)>1:
            conflicts.append([session,loc,k[0],k[1],len(group),'、'.join(str(r['qty']) for r in group),'、'.join(str(r.get('worker','')) for r in group),'、'.join(r['id'] for r in group)])
            continue
        actual[k]+=group[0]['qty'];counted_locations[k].add(loc)
    conflicted_parts={part_key(x[2],x[3]) for x in conflicts}
    comparison=[];locations=[]
    for k in sorted(set(baseline)|counted_parts):
        known=k in baseline and k not in {normalize_part(x[0],x[1],index) for x in unknown_book}
        conflict=k in conflicted_parts
        counted=k in counted_parts
        real=actual.get(k,0)
        booked=baseline.get(k,0)
        if conflict:status='重复盘点待复核';real_col='';difference=''
        elif not counted:status='未盘点';real_col='';difference=''
        elif not known:status='未完整匹配ERP账面数量';real_col=real;difference=''
        else:status='数量一致' if real==booked else '数量差异（须确认盘点范围）';real_col=real;difference=real-booked
        comparison.append([k[0],k[1],names.get(k,''),booked if known else '',real_col,difference,status,len(counted_locations.get(k,set()))])
        if counted and not conflict:
            old=stock_by_part.get(k,{})
            for loc in sorted(set(old)|counted_locations.get(k,set())):
                actual_at=next((g[0]['qty'] for (s,l,kk),g in count_groups.items() if kk==k and l==loc and len(g)==1),None)
                before=old.get(loc)
                if actual_at is None:locstatus='该库位未盘点'
                elif before is None:locstatus='ERP未登记此位置（或ERP仅有合并库位数量）'
                elif before!=actual_at:locstatus='数量或位置差异'
                else:locstatus='一致'
                locations.append([k[0],k[1],loc,before if before is not None else '',actual_at if actual_at is not None else '',locstatus])
    summary=[['项目','结果'],['库存基准ID',cat['snapshotId']],['库存基准明细行',len(stock)],['导入盘点文件数',len(files)],['有效记录数',len(rows)],['已删除记录数',len(deleted_rows)],['重复盘点分组',len(conflicts)],['货架完成标记',len(shelf_marks)],['ERP快照版本不匹配记录',len(snapshot_mismatch)],['异常源文件/记录',len(invalid)+len(conflicting_ids)],['注意','未盘点不能当作0；重复盘点不能直接相加；货架完成标记仅说明员工声明该货架盘完，不证明全部货物齐全']]
    sheets={
      '汇总':summary,
      '库存对比':[['ERP No.','Part No.','零件名称','ERP账面合计','已确认实盘合计','数量差异','状态','已盘库位数']]+comparison,
      '库位核对':[['ERP No.','Part No.','库位','ERP此库位数量','实盘此库位数量','状态']]+locations,
      '重复盘点待复核':[['批次','库位','ERP No.','Part No.','记录条数','各次盘点数量','盘点人','记录ID']]+conflicts,
      '货架完成记录':[['批次','物理楼层','货架','盘点人','完成时间','记录ID','源文件']]+[[x.get('session',''),x.get('physicalFloor',''),x.get('shelf',''),x.get('worker',''),x.get('completedAt',''),x.get('id',''),x.get('sourceFile','')] for x in shelf_marks],
      '移库申请与临时存放':[['盘点人','ERP No.','Part No.','ERP原库位','实际库位','数量','操作类型','备注','记录ID']]+movement,
      '原始盘点记录':[['批次','盘点人','实际库位','物理楼层','ERP No.','Part No.','零件名','长 cm','宽 cm','高 cm','重量 kg','数量','操作类型','原库位','备注','记录时间','记录ID','源文件']]+raw,
      '快照版本不一致':[['源文件','记录ID','手机快照ID','当前ERP快照ID']]+snapshot_mismatch,
      '已删除记录':[['批次','盘点人','库位','物理楼层','ERP No.','Part No.','原数量','删除时间','记录ID','源文件']]+[[r.get('session',''),r.get('worker',''),r.get('location',''),r.get('physicalFloor',''),r.get('erp',''),r.get('partNo',''),r.get('qty',''),r.get('updatedAt',''),r.get('id',''),r.get('sourceFile','')] for r in deleted_rows],
      '读取问题':[['来源','问题']]+invalid+conflicting_ids,
      'ERP数量缺失':[['ERP No.','Part No.','库位','来源工作表']]+unknown_book,
    }
    return sheets,{'files':len(files),'records':len(rows),'conflicts':len(conflicts),'mismatch':len(snapshot_mismatch)}

def excel_col(n):
    s='';n+=1
    while n:s=chr(65+(n-1)%26)+s;n=(n-1)//26
    return s

def xml_sheet(rows):
    z=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><sheetData>']
    for i,row in enumerate(rows,1):
        z.append(f'<row r="{i}">')
        for j,value in enumerate(row):
            if value is None or value=='':continue
            cell=f'{excel_col(j)}{i}';style=' s="1"' if i==1 else ''
            if isinstance(value,(float,int)) and not isinstance(value,bool):z.append(f'<c r="{cell}"{style}><v>{value}</v></c>')
            else:z.append(f'<c r="{cell}"{style} t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        z.append('</row>')
    z.append('</sheetData><autoFilter ref="A1:'+excel_col(max((len(r) for r in rows),default=1)-1)+str(max(len(rows),1))+'"/></worksheet>')
    return ''.join(z).encode('utf-8')

def write_xlsx(out,sheets):
    """Create a standards-compliant XLSX with stdlib only; no pip installs."""
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        types=['<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        w=['<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
        r=['<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        for i,(name,rows) in enumerate(sheets.items(),1):
            z.writestr(f'xl/worksheets/sheet{i}.xml',xml_sheet(rows));types.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>');w.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>');r.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        n=len(sheets)+1
        r.append(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>');r.append('</Relationships>');w.append('</sheets></workbook>');types.append('</Types>')
        z.writestr('[Content_Types].xml',''.join(types));z.writestr('xl/workbook.xml',''.join(w));z.writestr('xl/_rels/workbook.xml.rels',''.join(r));z.writestr('_rels/.rels','<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/styles.xml','<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF15324E"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs></styleSheet>')

def merge(inventory,folder,out):
    cat,_=build_inventory(inventory);sheets,stats=summarize(cat,folder);Path(out).parent.mkdir(parents=True,exist_ok=True);write_xlsx(out,sheets);print('成功生成：',out,stats);return stats

def gui():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('Hangcha StockCount · 电脑端');root.geometry('660x510');root.configure(bg='#f1f5f9')
    frame=ttk.Frame(root,padding=22);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='杭叉离线盘库 · 管理员工具',font=('Segoe UI',18,'bold')).pack(anchor='w',pady=(4,8))
    ttk.Label(frame,text='① 选择库存 Excel → 导出手机用 JSON；② 收齐员工 JSON 后合并生成 Excel。',wraplength=590).pack(anchor='w',pady=(0,14))
    inv=tk.StringVar();folder=tk.StringVar();status=tk.StringVar(value='就绪')
    def file_row(label,var,filemode=True):
        ttk.Label(frame,text=label).pack(anchor='w',pady=(10,3));box=ttk.Frame(frame);box.pack(fill='x');ttk.Entry(box,textvariable=var).pack(side='left',fill='x',expand=True)
        ttk.Button(box,text='浏览...',command=lambda:var.set(filedialog.askopenfilename(filetypes=[('Excel / CSV','*.xlsx *.csv')]) if filemode else filedialog.askdirectory())).pack(side='left',padx=5)
    file_row('ERP 库存文件（选择 .xlsx / .csv）',inv)
    def prep():
        if not Path(inv.get()).is_file():messagebox.showerror('缺少文件','请选择库存 Excel');return
        dest=filedialog.asksaveasfilename(title='保存手机库存 JSON',defaultextension='.json',initialfile='stockcount_inventory.json',filetypes=[('JSON','*.json')]);
        if not dest:return
        try:cat=prepare(inv.get(),dest);status.set(f'库存导出成功：{len(cat["items"])} 行');messagebox.showinfo('成功','已生成手机用库存 JSON。请传到每位同事手机并导入。')
        except Exception as e:messagebox.showerror('失败',str(e));status.set('库存导出失败')
    ttk.Button(frame,text='① 生成手机库存 JSON',command=prep).pack(fill='x',pady=11,ipady=8)
    file_row('员工盘库 JSON 文件夹（所有同事文件放在这里）',folder,False)
    def finish():
        if not Path(inv.get()).is_file() or not Path(folder.get()).is_dir():messagebox.showerror('缺少输入','请先选择库存 Excel 和员工记录文件夹');return
        dest=filedialog.asksaveasfilename(title='保存盘库差异 Excel',defaultextension='.xlsx',initialfile='StockCount_盘库对比.xlsx',filetypes=[('Excel','*.xlsx')]);
        if not dest:return
        try:s=merge(inv.get(),folder.get(),dest);status.set(f'完成：{s["records"]}条记录；{s["conflicts"]}组重复盘点');messagebox.showinfo('成功',f'报告已生成：\n{dest}\n\n{status.get()}')
        except Exception as e:messagebox.showerror('失败',str(e));status.set('合并失败')
    ttk.Button(frame,text='② 汇总盘点文件并生成差异 Excel',command=finish).pack(fill='x',pady=12,ipady=9)
    ttk.Label(frame,textvariable=status,foreground='#2e688c',wraplength=590).pack(anchor='w',pady=12)
    ttk.Label(frame,text='提示：此版本针对「库存已有备件」工作表适配。多库位共用数量不会被重复拆分。',foreground='#687e90',wraplength=590).pack(anchor='w')
    root.mainloop()

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command');a=sub.add_parser('inspect');a.add_argument('inventory');a=sub.add_parser('prepare');a.add_argument('inventory');a.add_argument('--out',default='stockcount_inventory.json');a=sub.add_parser('merge');a.add_argument('inventory');a.add_argument('folder');a.add_argument('--out',default='StockCount_盘库对比.xlsx');sub.add_parser('gui');args=p.parse_args()
    try:
        if args.command=='prepare':prepare(args.inventory,args.out)
        elif args.command=='merge':merge(args.inventory,args.folder,args.out)
        elif args.command=='inspect':inspect(args.inventory)
        else:gui()
    except Exception as e:print('出错：',str(e),file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
