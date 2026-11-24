# -*- coding: utf-8 -*-
"""v0.5.3: independent employee count reconciliation, no Excel matching."""
import json, os, re, tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from itertools import combinations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from stockcount import (read_export_documents, digest, norm, valid_quantity,
                        parse_quantity, MAX_QTY, App as LegacyApp, filehash)

PROJECT='hangcha-stockcount-merge-project'
MERGED='hangcha-stockcount-merged-inventory'
VERSION=1

def now(): return datetime.now(timezone.utc).isoformat()

def atomic_json(path,data):
    p=Path(path)
    fd,tmp=tempfile.mkstemp(prefix='.stockcount_',suffix='.tmp',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def location_tokens(location,floor):
    """Parse components, not arbitrary string prefixes (suffix 1 != 10)."""
    s=norm(location)
    m=re.fullmatch(r'([A-P])(?:(\d{2})(?:(\d{2})(?:(\d{2})(?:-(III|II|I)(?:-(.+))?)?)?)?)?',s)
    if not m: raise ValueError(f'无效库位：{location}')
    col,row,level,slot,partition,suffix=m.groups()
    if type(floor) is not int or floor not in (1,2,3): raise ValueError('楼层须为1、2或3')
    if row and not 1<=int(row)<= (8 if col in 'FG' else 13 if col=='H' else 12): raise ValueError(f'货架号无效：{s}')
    if level and (not 1<=int(level)<=12 or (int(level)-1)//4+1!=floor): raise ValueError(f'高度不属于 {floor}F：{s}')
    if slot and not 1<=int(slot)<=5: raise ValueError(f'箱号无效：{s}')
    return tuple(x for x in (col,row,level,slot,partition,suffix) if x is not None)

def identity(r): return (norm(r.get('erp')),norm(r.get('partNo')))

def overlap_tokens(a,b): return a[:min(len(a),len(b))]==b[:min(len(a),len(b))]

def pair_id(a,b): return digest(sorted([a['effectiveKey'],b['effectiveKey']]))

def ack_reason(value):
    return str(value.get('reason','') if isinstance(value,dict) else value or '').strip()

def effective_records(records,decisions):
    result=[]
    for r in records:
        key=digest(r); d=decisions.get(key,{})
        action=d.get('action','')
        if action not in ('','edit','exclude'): raise ValueError('无效人工决定')
        if action and not str(d.get('reason','')).strip(): raise ValueError('人工决定缺少依据')
        e=dict(r)
        if action=='edit':
            for k in ('qty','location','physicalFloor'):
                if k in d:e[k]=d[k]
            # LocationFields no longer describe the corrected location; retain in raw record only.
            if e['location']!=r['location'] or e['physicalFloor']!=r['physicalFloor']:e.pop('locationFields',None)
        e['location']=norm(e['location'])
        if not valid_quantity(e['qty']):raise ValueError('无效确认数量')
        tokens=location_tokens(e['location'],e['physicalFloor'])
        result.append(dict(key=key,record=r,effective=e,tokens=tokens,excluded=action=='exclude',decision=d,effectiveKey=digest([key,e])))
    return result

def analyze(records,decisions,acknowledgements):
    items=effective_records(records,decisions); buckets=defaultdict(list); seen=set(); conflicts=[]
    for x in items:
        if x['excluded']:continue
        r=x['effective']
        for field,value in zip(('erp','partNo'),identity(r)):
            if value:buckets[(r['physicalFloor'],field,value)].append(x)
    for group in buckets.values():
        for a,b in combinations(group,2):
            k=pair_id(a,b)
            if k in seen:continue
            seen.add(k)
            if not overlap_tokens(a['tokens'],b['tokens']):continue
            ra,rb=a['effective'],b['effective']
            same=identity(ra)==identity(rb)
            kind=('同员工' if norm(ra['worker'])==norm(rb['worker']) else '跨员工')+' · '+('同库位' if a['tokens']==b['tokens'] else '上下级库位重叠')
            if not same:kind+=' · 编号部分相同'
            conflicts.append(dict(key=k,a=a,b=b,reason=kind,confirmed=bool(ack_reason(acknowledgements.get(k)))))
    return items,sorted(conflicts,key=lambda c:(c['a']['effective']['physicalFloor'],c['a']['effective']['location'],c['key']))

def decimal_sum(values):
    q=sum((Decimal(str(v)) for v in values),Decimal(0))
    if q>MAX_QTY:raise ValueError('数量合计超出安全范围')
    return int(q) if q==q.to_integral_value() else float(q)

def unique_values(rows,fields):
    values={}
    for r in rows:
        v={k:r.get(k) for k in fields}
        if any(x is not None and x!='' for x in v.values()):
            key=digest(v); values.setdefault(key,dict(v,recordIds=[]))['recordIds'].append(r['id'])
    return list(values.values())

def aggregate(items,conflicts):
    if any(not c['confirmed'] for c in conflicts):raise ValueError('仍有未解决的重复盘点冲突')
    groups=defaultdict(list)
    for x in items:
        if not x['excluded']:groups[identity(x['effective'])].append(x['effective'])
    output=[]
    for (erp,part),rs in sorted(groups.items()):
        locs=defaultdict(list)
        for r in rs:locs[(r['physicalFloor'],r['location'])].append(r)
        locations=[dict(physicalFloor=f,location=l,qty=decimal_sum(r['qty'] for r in sub),recordIds=[r['id'] for r in sub],workers=sorted({r['worker'] for r in sub})) for (f,l),sub in sorted(locs.items())]
        positive=sorted({x['location'] for x in locations if x['qty']>0})
        output.append(dict(erp=erp,partNo=part,qty=decimal_sum(r['qty'] for r in rs),rackNo='/'.join(positive),locations=locations,recordIds=[r['id'] for r in rs],workers=sorted({r['worker'] for r in rs}),names=unique_values(rs,['partName']),measurements=unique_values(rs,['lengthCm','widthCm','heightCm','weightKg']),notes=[dict(recordId=r['id'],worker=r['worker'],note=r['note']) for r in rs if r.get('note')]))
    return output

def coverage(items,shelves):
    """Advisory only: shelf coverage / multiple employees, not quantity evidence."""
    groups=defaultdict(lambda:dict(workers=set(),records=[],markers=[]))
    for x in items:
        if x['excluded']:continue
        r=x['effective']; k=(r['physicalFloor'],''.join(x['tokens'][:2])); g=groups[k];g['workers'].add(r['worker']);g['records'].append(r['id'])
    for s in shelves:
        if s.get('deleted'):continue
        k=(s['physicalFloor'],norm(s['shelf']));g=groups[k];g['workers'].add(s['worker']);g['markers'].append(s['id'])
    return [dict(physicalFloor=f,shelf=l,workers=sorted(g['workers']),recordIds=g['records'],completionIds=g['markers']) for (f,l),g in sorted(groups.items()) if len(g['workers'])>1 or len(g['markers'])>1]

def make_output(documents,decisions,acknowledgements):
    records,allrecords,shelves,batch,snapshot=read_export_documents([(x['name'],x['data']) for x in documents])
    items,conflicts=analyze(records,decisions,acknowledgements)
    grouped=aggregate(items,conflicts)
    if not grouped:raise ValueError('没有可合并的有效盘库记录')
    return dict(format=MERGED,version=VERSION,createdAt=now(),session=batch,snapshotId=snapshot,scope='counted-items-only',unrecordedPolicy='unknown-not-zero',identityPolicy='normalized-exact-erp-partNo-pair',items=grouped,acceptedRecords=[x['effective'] for x in items if not x['excluded']],latestSourceRecords=allrecords,shelfCompletions=shelves,sourceExports=[dict(name=x['name'],contentSha256=digest(x['data']),exportedAt=x['data'].get('exportedAt')) for x in documents],recordDecisions=[dict(recordId=x['record']['id'],sourceKey=x['key'],**x['decision']) for x in items if x['decision']],overlapDecisions=[dict(recordIds=[c['a']['record']['id'],c['b']['record']['id']],key=c['key'],reason=ack_reason(acknowledgements[c['key']])) for c in conflicts if c['confirmed']],coverageAdvisories=coverage(items,shelves))

class Manager:
    def __init__(self,root):
        self.root=root;self.docs=[];self.decisions={};self.acks={};self.items=[];self.conflicts=[];self.dirty=False
        root.title('Hangcha StockCount · 员工盘库合并 v0.5.3');root.geometry('1320x780');root.minsize(850,520)
        root.protocol('WM_DELETE_WINDOW',self.close)
        bar=ttk.Frame(root,padding=9);bar.pack(fill='x')
        self.buttons(bar,[('1 导入员工 JSON',self.imports),('保存项目',self.save),('打开项目',self.load),('新建项目',self.clear),('生成手机基准（可选）',self.catalog),('3 生成合并库存 JSON',self.export)])
        self.info=tk.StringVar();ttk.Label(root,textvariable=self.info,padding=8).pack(fill='x')
        ttk.Label(root,text='本阶段不导入或匹配旧库存 Excel；只处理员工之间及同一员工的疑似重复盘点。',padding=(10,0,10,5)).pack(fill='x')
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=10,pady=8)
        conflict_tab=ttk.Frame(self.tabs);record_tab=ttk.Frame(self.tabs);preview_tab=ttk.Frame(self.tabs);cover_tab=ttk.Frame(self.tabs)
        for t,l in [(conflict_tab,'2 重复盘点冲突'),(record_tab,'全部盘点记录'),(preview_tab,'合并库存预览'),(cover_tab,'库位覆盖提示')]:self.tabs.add(t,text=l)
        bar=ttk.Frame(conflict_tab,padding=5);bar.pack(fill='x');self.buttons(bar,[('处理选中冲突',self.resolve),('撤销该冲突决定',self.reset_conflict)])
        self.ct=self.table(conflict_tab,['状态','原因','ERP / Part No. A','员工 A','楼层/库位 A','数量 A','ERP / Part No. B','员工 B','楼层/库位 B','数量 B'],[75,190,200,80,110,65,200,80,110,65]);self.ct.bind('<Double-1>',lambda e:self.safe(self.resolve))
        bar=ttk.Frame(record_tab,padding=5);bar.pack(fill='x');self.buttons(bar,[('查看记录详情',self.details),('修改数量 / 库位',self.edit),('排除记录',self.exclude),('撤销记录决定',self.reset_record)])
        self.rt=self.table(record_tab,['状态','员工','ERP','Part No.','楼层','实际库位','数量','名称','备注'],[85,100,150,180,60,120,70,180,220]);self.rt.bind('<Double-1>',lambda e:self.safe(self.details))
        self.pt=self.table(preview_tab,['ERP','Part No.','盘库总数量','Rack No.（正库存）','库位明细数','记录数'],[170,220,105,320,100,100])
        self.st=self.table(cover_tab,['楼层','货架','涉及员工','盘点记录数','完成标记数'],[80,130,320,150,150]);ttk.Label(cover_tab,text='多员工同货架或重复完成标记仅供复核；不同零件可以放在同一库位，不因此阻断合并。',padding=6).pack(fill='x')
        self.refresh()
    def buttons(self,bar,buttons):
        for text,fn in buttons:ttk.Button(bar,text=text,command=lambda f=fn:self.safe(f)).pack(side='left',padx=3)
    def table(self,parent,labels,widths):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True);cols=list(map(str,range(len(labels))));t=ttk.Treeview(frame,columns=cols,show='headings',selectmode='browse')
        for k,l,w in zip(cols,labels,widths):t.heading(k,text=l);t.column(k,width=w,minwidth=50)
        y=ttk.Scrollbar(frame,orient='vertical',command=t.yview);x=ttk.Scrollbar(frame,orient='horizontal',command=t.xview);t.configure(yscrollcommand=y.set,xscrollcommand=x.set);y.pack(side='right',fill='y');x.pack(side='bottom',fill='x');t.pack(fill='both',expand=True)
        t.tag_configure('pending',background='#ffe1c2');t.tag_configure('excluded',foreground='#888888');return t
    def safe(self,fn):
        try:fn()
        except Exception as e:messagebox.showerror('操作失败',str(e),parent=self.root)
    def state(self,docs=None,decisions=None,acks=None):
        docs=self.docs if docs is None else docs;decisions=self.decisions if decisions is None else decisions;acks=self.acks if acks is None else acks
        records,allrecords,shelves,batch,snapshot=read_export_documents([(x['name'],x['data']) for x in docs]);items,conflicts=analyze(records,decisions,acks)
        return records,allrecords,shelves,batch,snapshot,items,conflicts
    def refresh(self):
        records,allrecords,shelves,batch,snapshot,self.items,self.conflicts=self.state();self.bykey={x['key']:x for x in self.items};self.byconf={c['key']:c for c in self.conflicts}
        pending=[c for c in self.conflicts if not c['confirmed']];pending_keys={x['key'] for c in pending for x in (c['a'],c['b'])}
        self.info.set(f'文件 {len(self.docs)} | 有效原始记录 {len(records)} | 排除 {sum(x["excluded"] for x in self.items)} | 待处理冲突 {len(pending)} | 员工 {len({r["worker"] for r in records})} | 批次 {batch or "未填写"} | 删除记录 {sum(bool(r.get("deleted")) for r in allrecords)}')
        for t in (self.ct,self.rt,self.pt,self.st):t.delete(*t.get_children())
        for c in sorted(self.conflicts,key=lambda c:c['confirmed']):
            vals=[]
            for x in (c['a'],c['b']):
                r=x['effective'];vals.extend([' / '.join(identity(r)),r['worker'],f'{r["physicalFloor"]}F {r["location"]}',r['qty']])
            self.ct.insert('','end',iid=c['key'],values=['已确认分开' if c['confirmed'] else '待处理',c['reason'],*vals],tags=(() if c['confirmed'] else ('pending',)))
        for x in self.items:
            r=x['effective'];status='excluded' if x['excluded'] else 'pending' if x['key'] in pending_keys else 'ok';self.rt.insert('','end',iid=x['key'],values=({'excluded':'已排除','pending':'待处理','ok':'有效'}[status],r['worker'],r.get('erp',''),r.get('partNo',''),r['physicalFloor'],r['location'],r['qty'],r.get('partName',''),r.get('note','')),tags=(status,))
        if not pending:
            for x in aggregate(self.items,self.conflicts):self.pt.insert('','end',values=(x['erp'],x['partNo'],x['qty'],x['rackNo'],len(x['locations']),len(x['recordIds'])))
        else:self.pt.insert('','end',values=('请先解决全部重复冲突',))
        for x in coverage(self.items,shelves):self.st.insert('','end',values=(x['physicalFloor'],x['shelf'],' / '.join(x['workers']),len(x['recordIds']),len(x['completionIds'])))
    def imports(self):
        paths=filedialog.askopenfilenames(filetypes=[('员工导出','*.json')]);
        if not paths:return
        known={digest(x['data']) for x in self.docs};docs=list(self.docs)
        for p in paths:
            d=json.loads(Path(p).read_text(encoding='utf-8-sig'));h=digest(d)
            if h not in known:docs.append(dict(name=Path(p).name,data=d));known.add(h)
        self.state(docs=docs);self.docs=docs;self.dirty=True;self.refresh()
    def selected(self,tree,mapping):
        sel=tree.selection()
        if not sel:raise ValueError('请选择一条记录')
        return mapping[sel[0]]
    def resolve(self):
        c=self.selected(self.ct,self.byconf);a,b=c['a'],c['b'];d=tk.Toplevel(self.root);d.title('确认疑似重复盘点');d.transient(self.root);d.grab_set();d.geometry('800x450')
        ttk.Label(d,text=c['reason'],padding=10).pack(fill='x')
        for label,x in [('A',a),('B',b)]:
            r=x['effective'];ttk.Label(d,text=f'{label} | {r["worker"]} | {r["physicalFloor"]}F {r["location"]} | 数量 {r["qty"]}\nERP: {r.get("erp","")}   Part No.: {r.get("partNo","")}\n{r.get("partName","")}  备注: {r.get("note","")}\n时间: {r["updatedAt"]}',padding=10,wraplength=760).pack(fill='x')
        ttk.Label(d,text='选择保留一条会排除另一条整个记录，并重新检查它涉及的所有冲突。\n若实际是两批货物，可确认两条都保留；不会自动相加重复记录。',padding=8,wraplength=760).pack(fill='x')
        def choose(action):
            reason=simpledialog.askstring('处理依据','请填写复核依据',parent=d)
            if not reason or not reason.strip():return
            if action=='both':self.acks[c['key']]=dict(reason=reason.strip(),recordKeys=[a['key'],b['key']])
            else:
                rejected=b if action=='a' else a;self.decisions[rejected['key']]=dict(action='exclude',reason=reason.strip())
            self.dirty=True;d.destroy();self.refresh()
        bar=ttk.Frame(d,padding=8);bar.pack(fill='x');self.buttons(bar,[('保留 A，排除 B',lambda:choose('a')),('保留 B，排除 A',lambda:choose('b')),('确认两条均有效',lambda:choose('both')),('取消',d.destroy)])
    def reset_conflict(self):
        c=self.selected(self.ct,self.byconf);self.acks.pop(c['key'],None);self.dirty=True;self.refresh()
    def details(self):
        x=self.selected(self.rt,self.bykey);d=tk.Toplevel(self.root);d.title('记录原始数据及人工决定');t=tk.Text(d,width=100,height=32);t.pack(fill='both',expand=True);t.insert('1.0',json.dumps(dict(original=x['record'],effective=x['effective'],decision=x['decision']),ensure_ascii=False,indent=2));t.config(state='disabled')
    def edit(self):
        x=self.selected(self.rt,self.bykey);r=x['effective'];q=simpledialog.askstring('复盘数量','实际数量（支持小数）',initialvalue=str(r['qty']),parent=self.root)
        if q is None:return
        q=parse_quantity(q);floor=simpledialog.askinteger('楼层','实际物理楼层',initialvalue=r['physicalFloor'],minvalue=1,maxvalue=3,parent=self.root)
        if floor is None:return
        loc=simpledialog.askstring('库位','实际库位',initialvalue=r['location'],parent=self.root)
        if loc is None:return
        location_tokens(loc,floor);reason=simpledialog.askstring('依据','请输入修改依据',parent=self.root)
        if not reason or not reason.strip():return
        self.decisions[x['key']]=dict(action='edit',qty=q,physicalFloor=floor,location=norm(loc),reason=reason.strip());self.dirty=True;self.refresh()
    def exclude(self):
        x=self.selected(self.rt,self.bykey);reason=simpledialog.askstring('排除记录','请输入排除依据',parent=self.root)
        if not reason or not reason.strip():return
        self.decisions[x['key']]=dict(action='exclude',reason=reason.strip());self.dirty=True;self.refresh()
    def reset_record(self):
        x=self.selected(self.rt,self.bykey);self.decisions.pop(x['key'],None)
        # Remove acknowledgements involving this source version, including prior edited states.
        related={c['key'] for c in self.conflicts if x['key'] in (c['a']['key'],c['b']['key'])}
        self.acks={k:v for k,v in self.acks.items() if k not in related and not (isinstance(v,dict) and x['key'] in v.get('recordKeys',[]))}
        self.dirty=True;self.refresh()
    def save(self):
        p=filedialog.asksaveasfilename(defaultextension='.json',initialfile='stockcount_merge_project.json',filetypes=[('项目','*.json')]);
        if not p:return
        atomic_json(p,dict(format=PROJECT,version=VERSION,documents=self.docs,recordDecisions=self.decisions,overlapAcknowledgements=self.acks));self.dirty=False
    def can_discard(self):return not self.dirty or messagebox.askyesno('未保存的项目','尚有未保存修改。确定放弃？',parent=self.root)
    def load(self):
        p=filedialog.askopenfilename(filetypes=[('项目','*.json')]);
        if not p or not self.can_discard():return
        d=json.loads(Path(p).read_text(encoding='utf-8-sig'))
        if d.get('format')!=PROJECT or d.get('version')!=VERSION:raise ValueError('不是 v0.5.3 合并项目；请重新导入原员工 JSON，旧 Excel 行匹配决定不能复用。')
        self.state(d['documents'],d['recordDecisions'],d['overlapAcknowledgements']);self.docs=d['documents'];self.decisions=d['recordDecisions'];self.acks=d['overlapAcknowledgements'];self.dirty=False;self.refresh()
    def clear(self):
        if not self.can_discard():return
        self.docs=[];self.decisions={};self.acks={};self.dirty=False;self.refresh()
    def close(self):
        if self.can_discard():self.root.destroy()
    def export(self):
        result=make_output(self.docs,self.decisions,self.acks)
        if not messagebox.askyesno('确认合并','确认已收集本批次全部员工最终导出？\n本文件只包括有效盘点记录，不代表未盘点零件为零。',parent=self.root):return
        p=filedialog.asksaveasfilename(defaultextension='.json',initialfile='stockcount_merged_inventory.json',filetypes=[('合并库存','*.json')]);
        if not p:return
        if Path(p).exists():raise ValueError('请选择新文件名，避免覆盖原始记录或项目')
        atomic_json(p,result);messagebox.showinfo('已生成',f'已合并 {len(result["items"])} 个 ERP/Part No. 组合。\n{p}\n原库存 Excel 未修改。',parent=self.root)
    # Existing Excel reading is offered only as an independent optional catalog utility.
    detect_base=LegacyApp.detect_base;choose_column=LegacyApp.choose_column;set_base=LegacyApp.set_base
    def catalog(self):
        try:import win32com.client
        except ImportError:raise ValueError('生成手机基准需要 Windows 桌面 Excel 和 pywin32。可运行 py -3 -m pip install pywin32。员工合并不需要安装。')
        p=filedialog.askopenfilename(filetypes=[('Excel','*.xlsx *.xlsm')]);
        if not p:return
        selected=self.detect_base(p)
        if selected is None:return
        self.set_base(p,*selected);LegacyApp.catalog(self)

def main():
    root=tk.Tk();Manager(root);root.mainloop()
if __name__=='__main__':main()
