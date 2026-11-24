# -*- coding: utf-8 -*-
"""StockCount v0.5 management workstation; phone export v2 compatible."""
import json, hashlib, math, re, os, tempfile, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from contextlib import contextmanager
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

ZERO='盘库前归零'; IN='盘库入库'
def norm(v):
    if isinstance(v,float) and v.is_integer(): v=int(v)
    return str(v if v is not None else '').strip().upper()
def digest(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def filehash(p):
    with open(p,'rb') as f: return hashlib.file_digest(f,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(f.read()).hexdigest()
def timekey(v):
    t=datetime.fromisoformat(v.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('时间缺少时区')
    return t

def read_exports(paths):
    versions=defaultdict(list); shelves=defaultdict(list)
    for p in paths:
        d=json.loads(Path(p).read_text(encoding='utf-8-sig'))
        if d.get('format')!='hangcha-stockcount-export' or d.get('version')!=2 or not isinstance(d.get('records'),list): raise ValueError(f'不支持的导出格式: {p}')
        for collection,target in [(d['records'],versions),(d.get('shelfCompletions',[]),shelves)]:
            for r in collection:
                if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id']: raise ValueError(f'记录 ID 无效: {p}')
                timekey(r['updatedAt']); target[r['id']].append(r)
    def latest(groups):
        result=[]
        for rid,rows in sorted(groups.items()):
            t=max(timekey(r['updatedAt']) for r in rows)
            top={digest(r):r for r in rows if timekey(r['updatedAt'])==t}
            if len(top)>1: raise ValueError(f'同 ID 同时间内容不同，请核对原始导出: {rid}')
            result.append(next(iter(top.values())))
        return result
    all_records=latest(versions); all_shelves=latest(shelves)
    active=[r for r in all_records if not r.get('deleted')]
    for r in active:
        if type(r.get('qty')) is not int or r['qty']<0 or r['qty']>2**53-1: raise ValueError(f'数量无效: {r["id"]}')
        if not norm(r.get('location')) or not (norm(r.get('erp')) or norm(r.get('partNo'))) or not norm(r.get('worker')): raise ValueError(f'零件/库位/员工缺失: {r["id"]}')
        if r.get('physicalFloor') not in (1,2,3): raise ValueError(f'物理楼层无效: {r["id"]}')
    live=active+[r for r in all_shelves if not r.get('deleted')]
    batches={str(r.get('session') or '').strip() for r in live}; snapshots={str(r.get('snapshotId') or '') for r in live}
    if len(batches)>1 or len(snapshots)>1: raise ValueError('存在多个盘库批次或库存基准版本，请分开处理')
    return active,all_records,all_shelves,next(iter(batches),''),next(iter(snapshots),'')

def locate(r,rows):
    e,p=norm(r.get('erp')),norm(r.get('partNo'))
    em={i for i,x in rows.items() if e and norm(x['erp'])==e}; pm={i for i,x in rows.items() if p and norm(x['partNo'])==p}
    candidates=em & pm if e and p else em or pm
    if len(candidates)==1 and (not e or len(em)==1) and (not p or len(pm)==1): return next(iter(candidates)),'自动匹配'
    return None, '编号冲突/重复库存行' if em or pm else '新零件/未匹配'

def overlap(a,b):
    a,b=norm(a),norm(b)
    return a==b or a.startswith(b) or b.startswith(a)

def propose(records,rows,decisions):
    items=[]
    for r in records:
        row,reason=locate(r,rows); key=digest(r); d=decisions.get(key)
        item=dict(record=r,key=key,row=row,qty=r['qty'],location=norm(r['location']),status='auto' if row else 'pending',reason=reason)
        if d:
            item.update(d); item['status']='resolved' if d.get('action')=='accept' else 'excluded'
            if item['status']=='resolved' and item['row'] not in rows: item['status']='pending'; item['reason']='目标库存行已不存在'
        items.append(item)
    groups=defaultdict(list)
    for x in items:
        if x['status']!='excluded' and x['row'] is not None: groups[x['row']].append(x)
    for group in groups.values():
        for i,a in enumerate(group):
            for b in group[i+1:]:
                if a['record']['physicalFloor']==b['record']['physicalFloor'] and overlap(a['location'],b['location']):
                    for x in (a,b):
                        if x['status']=='auto': x['status']='pending'; x['reason']='同零件库位重叠，需逐条确认'
    return items

def totals(items,rows):
    if any(x['status']=='pending' for x in items): raise ValueError('仍有未解决冲突')
    result={i:{'qty':0,'locations':set(),'records':[]} for i in rows}
    for x in items:
        if x['status']=='excluded': continue
        q=x['qty']; i=x['row']
        if type(q) is not int or q<0 or i not in rows: raise ValueError('无效的确认结果')
        y=result[i]; y['qty']+=q; y['records'].append(x)
        if y['qty']>2**53-1: raise ValueError('合计数量超过安全整数范围')
        if q: y['locations'].add(x['location'])
    return result

@contextmanager
def excel(path):
    import win32com.client
    app=win32com.client.DispatchEx('Excel.Application'); app.Visible=False; app.DisplayAlerts=False; app.EnableEvents=False; app.AutomationSecurity=3
    app.AutoCorrect.AutoFillFormulasInLists=False; app.AutoCorrect.AutoExpandListRange=False
    wb=None
    try:
        wb=app.Workbooks.Open(str(Path(path).resolve()),UpdateLinks=0,ReadOnly=True)
        yield app,wb
    finally:
        if wb is not None: wb.Close(False)
        app.Quit()

def scan(path,sheet,header,mapping):
    with excel(path) as (app,wb):
        ws=wb.Worksheets(sheet); used=ws.UsedRange; lastcol=used.Column+used.Columns.Count-1; lastrow=used.Row+used.Rows.Count-1
        headers=[norm(ws.Cells(header,c).Value2) for c in range(1,lastcol+1)]
        if norm(ZERO) in headers or norm(IN) in headers: raise ValueError('源表已包含盘库调整列，请使用未调整的盘库前原表')
        cols={}
        for k,v in mapping.items():
            if not v: continue
            matches=[i+1 for i,h in enumerate(headers) if h==norm(v)]
            if len(matches)!=1: raise ValueError(f'表头 {v} 不存在或不唯一')
            cols[k]=matches[0]
        if not all(k in cols for k in ('erp','partNo','stock')) or len(set(cols.values()))!=len(cols): raise ValueError('ERP、Part No.、存必须配置且不可重复映射')
        if lastrow<=header: raise ValueError('无数据行')
        app.CalculateFullRebuild()
        values=ws.Range(ws.Cells(header+1,1),ws.Cells(lastrow,lastcol)).Value2
        formulas=ws.Range(ws.Cells(header+1,cols['stock']),ws.Cells(lastrow,cols['stock'])).Formula
        if not isinstance(formulas,tuple): formulas=((formulas,),)
        rows={}
        for offset,vals in enumerate(values):
            i=header+1+offset; e,p=norm(vals[cols['erp']-1]),norm(vals[cols['partNo']-1]);
            if not(e or p): continue
            q=vals[cols['stock']-1]; f=formulas[offset][0]
            if not isinstance(f,str) or not f.startswith('=') or not isinstance(q,(float,int)) or not math.isfinite(q) or abs(q)>2**53-1 or q!=int(q): raise ValueError(f'第 {i} 行存不是有效整数公式，请先修复或排除非零件行')
            rows[i]={'erp':e,'partNo':p,'stock':int(q),'formula':f,'location':str(vals[cols['location']-1] or '') if 'location' in cols else '', 'name':str(vals[cols['name']-1] or '') if 'name' in cols else ''}
        if not rows: raise ValueError('未发现有效零件')
        return rows,cols,lastcol

def write_stock(path,out,sheet,header,cols,lastcol,rows,result,expected_hash,update_location):
    if filehash(path)!=expected_hash: raise ValueError('库存源表已发生变化，请重新建立盘库项目')
    if Path(path).resolve()==Path(out).resolve() or Path(out).exists(): raise ValueError('输出必须是尚不存在的新文件')
    if Path(out).suffix.lower()!=Path(path).suffix.lower(): raise ValueError('输出扩展名必须与源表一致')
    tmp=Path(out).with_name('.stockcount_'+os.urandom(6).hex()+Path(out).suffix)
    try:
        with excel(path) as (app,wb):
            ws=wb.Worksheets(sheet); app.CalculateFullRebuild()
            z,n=lastcol+1,lastcol+2
            if n>16384: raise ValueError('Excel 列数已达上限')
            ws.Cells(header,z).Value2=ZERO; ws.Cells(header,n).Value2=IN
            for c in (z,n):
                ws.Cells(header,c).Font.Bold=True; ws.Columns(c).ColumnWidth=17
            for i,x in rows.items():
                cell=ws.Cells(i,cols['stock'])
                if cell.Formula!=x['formula'] or cell.Value2!=x['stock']: raise ValueError(f'源表第 {i} 行公式或计算值发生变化')
                ws.Cells(i,z).Value2=-x['stock']; ws.Cells(i,n).Value2=result[i]['qty']
                cell.Formula=f'=({x["formula"][1:]})+{ws.Cells(i,z).Address(False,False)}+{ws.Cells(i,n).Address(False,False)}'
                if update_location and 'location' in cols and result[i]['records']:
                    loc=ws.Cells(i,cols['location']); loc.NumberFormat='@'; loc.Value2='/'.join(sorted(result[i]['locations']))
            app.CalculateFullRebuild()
            for i,x in result.items():
                if ws.Cells(i,cols['stock']).Value2!=x['qty']: raise ValueError(f'第 {i} 行公式校验失败，未生成文件')
            wb.SaveCopyAs(str(tmp.resolve()))
        if filehash(path)!=expected_hash: raise ValueError('生成期间源表发生变化')
        if Path(out).exists(): raise ValueError('输出文件已存在')
        os.rename(tmp,out)
    finally:
        if tmp.exists(): tmp.unlink()

class App:
    def __init__(self,root):
        self.root=root; root.title('Hangcha StockCount · 年度盘库管理 v0.5.0'); root.geometry('1280x760'); self.rows={}; self.decisions={}; self.paths=[]; self.items=[]; self.source=''; self.hash=''; self.new={}
        bar=ttk.Frame(root,padding=10); bar.pack(fill='x')
        for text,fn in [('1 导入库存表',self.baseline),('2 导入员工 JSON',self.imports),('3 保存项目',self.save),('打开项目',self.load),('生成手机基准',self.catalog),('4 生成新库存表',self.generate)]: ttk.Button(bar,text=text,command=lambda f=fn:self.safe(f)).pack(side='left',padx=3)
        self.info=tk.StringVar(value='请先导入冻结的盘库前库存 Excel'); ttk.Label(root,textvariable=self.info,padding=8).pack(fill='x')
        buttons=ttk.Frame(root,padding=5); buttons.pack(fill='x')
        for text,fn in [('确认/修改选中记录',self.accept),('排除选中记录',self.exclude),('撤销选中决定',self.reset),('仅显示待处理',lambda:self.refresh(True)),('显示全部',lambda:self.refresh(False)),('未盘点零件清单',self.missing)]: ttk.Button(buttons,text=text,command=lambda f=fn:self.safe(f)).pack(side='left',padx=3)
        frame=ttk.Frame(root); frame.pack(fill='both',expand=True,padx=10,pady=8)
        cols=('status','worker','erp','part','location','qty','row','reason','note'); self.tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='extended')
        for k,label,w in zip(cols,['状态','员工','ERP','Part No.','实际库位','数量','Excel行','说明','备注'],[90,100,150,160,125,65,70,220,180]): self.tree.heading(k,text=label); self.tree.column(k,width=w,minwidth=55)
        y=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview); x=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview); self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set); y.pack(side='right',fill='y'); x.pack(side='bottom',fill='x'); self.tree.pack(fill='both',expand=True)
        self.tree.tag_configure('pending',background='#ffe1c2'); self.tree.tag_configure('excluded',foreground='#888888'); self.tree.bind('<Double-1>',lambda e:self.safe(self.accept)); self.only=False
    def safe(self,fn):
        try: fn()
        except Exception as e: messagebox.showerror('操作失败',str(e))
    def baseline(self):
        p=filedialog.askopenfilename(filetypes=[('Excel','*.xlsx *.xlsm')]);
        if not p:return
        sheet=simpledialog.askstring('工作表','库存工作表名称（精确）'); header=simpledialog.askinteger('表头','表头所在行',initialvalue=1,minvalue=1)
        if not sheet or header is None:return
        mapping={}
        for key,label,default in [('erp','ERP 编号','Code No.'),('partNo','零件编号','Part No.'),('stock','存','存'),('location','库位（可留空）','库位'),('name','名称（可留空）','')]:
            v=simpledialog.askstring('表头映射',label,initialvalue=default)
            if v is None:return
            mapping[key]=v.strip()
        self.set_base(p,sheet,header,mapping); self.decisions={}; self.paths=[]; self.refresh()
    def set_base(self,p,sheet,header,mapping):
        h=filehash(p); rows,cols,last=scan(p,sheet,header,mapping)
        if filehash(p)!=h: raise ValueError('读取期间源文件变化')
        self.source=p; self.sheet=sheet; self.header=header; self.mapping=mapping; self.rows=rows; self.cols=cols; self.lastcol=last; self.hash=h
    def imports(self):
        if not self.rows: raise ValueError('先导入库存表')
        paths=filedialog.askopenfilenames(filetypes=[('员工导出','*.json')]);
        if not paths:return
        combined=sorted(set(self.paths)|set(paths)); read_exports(combined); self.paths=combined; self.refresh()
    def refresh(self,only=None):
        if only is not None:self.only=only
        self.records,self.allrecords,self.shelves,self.batch,self.snapshot=read_exports(self.paths)
        self.items=propose(self.records,self.rows,self.decisions); self.tree.delete(*self.tree.get_children()); self.bykey={x['key']:x for x in self.items}
        labels={'auto':'自动匹配','pending':'待处理','resolved':'已确认','excluded':'已排除'}
        for x in self.items:
            if self.only and x['status']!='pending':continue
            r=x['record']; self.tree.insert('', 'end',iid=x['key'],values=(labels[x['status']],r.get('worker'),r.get('erp'),r.get('partNo'),x['location'],x['qty'],x['row'] or '',x['reason'],r.get('note','')),tags=(x['status'],))
        self.info.set(f'库存行 {len(self.rows)} | 文件 {len(self.paths)} | 有效记录 {len(self.records)} | 待处理 {sum(x["status"]=="pending" for x in self.items)} | 批次 {self.batch or "未填写"} | 员工 {len({r.get("worker") for r in self.records})} | 删除记录 {sum(bool(r.get("deleted")) for r in self.allrecords)}')
    def accept(self):
        keys=self.tree.selection()
        if len(keys)!=1:raise ValueError('请选择一条记录')
        x=self.bykey[keys[0]]; r=x['record']; row=simpledialog.askinteger('目标库存行',f'ERP: {r.get("erp")} / Part: {r.get("partNo")}\n请输入原库存 Excel 行号（未匹配零件需先在基准表新增并核准）',initialvalue=x['row'],minvalue=1)
        if row is None:return
        if row not in self.rows:raise ValueError('不是有效库存行')
        target=self.rows[row]; qty=simpledialog.askinteger('确认实际数量',f'目标：{target["erp"]} / {target["partNo"]}\n原记录数量 {r["qty"]}；重复记录可排除其余条目',initialvalue=x['qty'],minvalue=0,maxvalue=2**53-1)
        if qty is None:return
        loc=simpledialog.askstring('确认库位','实际库位',initialvalue=x['location']);
        if loc is None:return
        if not loc.strip():raise ValueError('库位不能为空')
        reason=simpledialog.askstring('处理依据','填写确认依据（例如复盘、两批不同实物）');
        if not reason or not reason.strip():return
        self.decisions[x['key']]={'action':'accept','row':row,'qty':qty,'location':norm(loc),'reason':reason.strip()}; self.refresh()
    def exclude(self):
        keys=self.tree.selection();
        if not keys:return
        reason=simpledialog.askstring('排除记录','填写原因（例如重复盘点）')
        if not reason or not reason.strip():return
        for k in keys:self.decisions[k]={'action':'exclude','reason':reason.strip()}
        self.refresh()
    def reset(self):
        for k in self.tree.selection():self.decisions.pop(k,None)
        self.refresh()
    def missing(self):
        seen={x['row'] for x in self.items if x['status'] in ('auto','resolved')}; missing=[(i,x) for i,x in self.rows.items() if i not in seen]
        top=tk.Toplevel(self.root); top.title(f'未盘点/未确认库存行：{len(missing)}'); t=tk.Text(top,width=110,height=30); t.pack(fill='both',expand=True)
        t.insert('end','Excel行\tERP\tPart No.\t原库存\t库位\n'+'\n'.join(f'{i}\t{x["erp"]}\t{x["partNo"]}\t{x["stock"]}\t{x["location"]}' for i,x in missing)); t.config(state='disabled')
    def save(self):
        if not self.source:raise ValueError('没有项目')
        p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('项目','*.json')]);
        if p: Path(p).write_text(json.dumps(dict(source=self.source,hash=self.hash,sheet=self.sheet,header=self.header,mapping=self.mapping,paths=self.paths,decisions=self.decisions),ensure_ascii=False,indent=2),encoding='utf-8')
    def load(self):
        p=filedialog.askopenfilename(filetypes=[('项目','*.json')]);
        if not p:return
        d=json.loads(Path(p).read_text(encoding='utf-8-sig'))
        if filehash(d['source'])!=d['hash']:raise ValueError('库存基准已变化，不能恢复旧决定')
        read_exports(d['paths']); self.set_base(d['source'],d['sheet'],d['header'],d['mapping']); self.paths=d['paths']; self.decisions=d['decisions']; self.refresh()
    def catalog(self):
        if not self.rows:raise ValueError('先导入库存表')
        p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('手机基准','*.json')]);
        if p:Path(p).write_text(json.dumps({'format':'hangcha-stockcount-catalog','version':1,'snapshotId':self.hash,'items':[{'erp':x['erp'],'partNo':x['partNo'],'name':x['name'],'location':x['location'],'locations':x['location'].split('/') if x['location'] else [],'bookQty':x['stock']} for x in self.rows.values()]},ensure_ascii=False),encoding='utf-8')
    def generate(self):
        self.refresh()
        if not self.records:raise ValueError('没有有效盘库记录，禁止全表归零')
        result=totals(self.items,self.rows); missing=sum(not x['records'] for x in result.values())
        if self.snapshot!=self.hash and not messagebox.askyesno('基准不一致','手机基准 ID 与当前文件 SHA256 不同（旧版本基准可能采用其他 ID）。请核对确实是同一冻结库存表，是否继续？'):return
        if missing and not messagebox.askyesno('未盘点零件',f'{missing} 行无有效盘点记录，将归零且盘库入库为 0。请先核实未盘点清单。是否确认？'):return
        if not messagebox.askyesno('最终确认','确认所有员工最终导出均已收到、盘库期间出入库已冻结，且已解决冲突？'):return
        update='location' in self.cols and messagebox.askyesno('库位更新','是否用确认的正库存库位覆盖已盘点零件的库位？未盘点行保留原库位。')
        out=filedialog.asksaveasfilename(defaultextension=Path(self.source).suffix,filetypes=[('Excel','*'+Path(self.source).suffix)]);
        if not out:return
        audit=Path(out+'.audit.json')
        if audit.exists():raise ValueError('审计文件已存在，请更换输出名称')
        write_stock(self.source,out,self.sheet,self.header,self.cols,self.lastcol,self.rows,result,self.hash,update)
        audit.write_text(json.dumps({'sourceHash':self.hash,'batch':self.batch,'snapshot':self.snapshot,'records':self.allrecords,'shelves':self.shelves,'decisions':self.decisions,'totals':{i:{'qty':x['qty'],'locations':sorted(x['locations']),'before':self.rows[i]['stock']} for i,x in result.items()}},ensure_ascii=False,indent=2),encoding='utf-8')
        messagebox.showinfo('成功','新库存 Excel 已生成并通过库存数量公式校验。\n'+out)

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
