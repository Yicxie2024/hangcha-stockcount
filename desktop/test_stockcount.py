import unittest, tempfile, json
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import contextmanager
from pathlib import Path
from stockcount import read_exports, propose, totals, digest, locate, DEFAULT_HEADERS, DEFAULT_SHEET, detect_header, resolve_columns, header_matches, stock_value, parse_quantity, quantity_matches, scan

ROWS={2:{'erp':'E1','partNo':'P1','stock':120},3:{'erp':'E2','partNo':'P2','stock':60},4:{'erp':'E3','partNo':'P3','stock':15}}
def rec(id,qty=10,loc='A0104',**kw):
    return dict(id=id,qty=qty,location=loc,physicalFloor=1,erp='E1',partNo='P1',worker='A',session='2026',snapshotId='base',updatedAt='2026-11-24T09:00:00Z',deleted=False)|kw
class Tests(unittest.TestCase):
    def exports(self,*groups):
        with tempfile.TemporaryDirectory() as d:
            paths=[]
            for i,g in enumerate(groups):
                p=Path(d)/f'{i}.json'; p.write_text(json.dumps(dict(format='hangcha-stockcount-export',version=2,records=g))); paths.append(p)
            return read_exports(paths)
    def test_versions(self):
        a=rec('a'); b=rec('a',12,updatedAt='2026-11-24T10:00:00Z'); c=rec('a',12,updatedAt='2026-11-24T11:00:00Z',deleted=True)
        self.assertEqual(self.exports([a],[a,b])[0],[b]); self.assertEqual(self.exports([a,b],[c])[0],[])
    def test_equal_time_conflict(self):
        with self.assertRaises(ValueError): self.exports([rec('a'),rec('a',12)])
    def test_batches(self):
        with self.assertRaises(ValueError): self.exports([rec('a'),rec('b',session='other')])
    def test_snapshot(self):
        with self.assertRaises(ValueError): self.exports([rec('a'),rec('b',snapshotId='other')])
    def test_wrong_identity(self):
        self.assertIsNone(locate(rec('a',partNo='P2'),ROWS)[0])
    def test_unknown_identity(self):
        self.assertIsNone(locate(rec('a',erp='NEW',partNo='NEW'),ROWS)[0])
    def test_merge(self):
        a,b=rec('a',10),rec('b',20,'B0203'); x=totals(propose([a,b],ROWS,{}),ROWS)
        self.assertEqual(x[2]['qty'],30); self.assertEqual(x[3]['qty'],0); self.assertEqual(x[2]['locations'],{'A0104','B0203'})
        for i,v in x.items(): self.assertEqual(ROWS[i]['stock']-ROWS[i]['stock']+v['qty'],v['qty'])
    def test_overlap(self):
        a,b=rec('a',10),rec('b',12,'A010401'); items=propose([a,b],ROWS,{})
        self.assertTrue(all(x['status']=='pending' for x in items))
        with self.assertRaises(ValueError): totals(items,ROWS)
        x=totals(propose([a,b],ROWS,{digest(b):{'action':'exclude','reason':'duplicate'}}),ROWS); self.assertEqual(x[2]['qty'],10)
    def test_resolution(self):
        a,b=rec('a'),rec('b',12); d={digest(a):{'action':'accept','row':2,'qty':11,'location':'A0104','reason':'recount'},digest(b):{'action':'exclude','reason':'duplicate'}}
        self.assertEqual(totals(propose([a,b],ROWS,d),ROWS)[2]['qty'],11)
    def test_fractional_exports_and_totals(self):
        a,b,c=rec('a',0.1),rec('b',0.2,'B0104'),rec('c',0.5,'C0104')
        self.assertEqual(self.exports([a,b,c])[0],[a,b,c])
        self.assertEqual(totals(propose([a,b,c],ROWS,{}),ROWS)[2]['qty'],0.8)
    def test_fractional_resolution(self):
        a=rec('a',0.5)
        d={digest(a):{'action':'accept','row':2,'qty':1.5,'location':'A0104','reason':'recount'}}
        self.assertEqual(totals(propose([a],ROWS,d),ROWS)[2]['qty'],1.5)
    def test_invalid_fractional_exports(self):
        for q in (-0.5,True,'0.5',float('nan'),float('inf')):
            with self.subTest(q=q),self.assertRaises(ValueError): self.exports([rec('a',q)])
    def test_invalid_qty(self):
        with self.assertRaises(ValueError): self.exports([rec('a',-1)])
class FractionTests(unittest.TestCase):
    def test_stock_formula_value(self):
        for q in (0.5,12.5,-0.5,0,120,0.125):
            self.assertEqual(stock_value(q,'=A2-B2',9555),q)
            self.assertEqual(q + -q,0)
        for q,f in [(None,'=A2'),('0.5','=A2'),(True,'=A2'),(float('nan'),'=A2'),(1.5,'1.5')]:
            with self.assertRaises(ValueError): stock_value(q,f,9555)
    def test_scan_keeps_fractional_values(self):
        class Worksheet:
            UsedRange=SimpleNamespace(Column=1,Row=1,Columns=SimpleNamespace(Count=3),Rows=SimpleNamespace(Count=3))
            def Cells(self,r,c):return (r,c)
            def Range(self,a,b):
                return {((1,1),(1,3)):SimpleNamespace(Value2=(('商品明细码ERP','Part.No.','存'),)),((2,1),(3,3)):SimpleNamespace(Value2=(('E1','P1',12.5),('E2','P2',-0.5))),((2,3),(3,3)):SimpleNamespace(Formula=(('=A2-B2',),('=A3-B3',)))}[(a,b)]
        @contextmanager
        def fake_excel(path):yield SimpleNamespace(CalculateFullRebuild=lambda:None),SimpleNamespace(Worksheets=lambda name:Worksheet())
        with patch('stockcount.excel',fake_excel):
            rows,_,_=scan('fake.xlsx',DEFAULT_SHEET,1,{'erp':'商品明细码ERP','partNo':'Part.No.','stock':'存'})
        self.assertEqual([r['stock'] for r in rows.values()],[12.5,-0.5])
    def test_manual_decimal(self):
        for value,expected in [('0.5',0.5),('1,5',1.5),('0',0),('.5',0.5)]:self.assertEqual(parse_quantity(value),expected)
        for value in ['-0.5','NaN','1.2.3','', '1e2']:
            with self.assertRaises(ValueError):parse_quantity(value)
    def test_formula_validation(self):
        self.assertTrue(quantity_matches(0.1+0.2,0.3))
        self.assertTrue(quantity_matches(1.5,1.5))
        self.assertFalse(quantity_matches(1,1.5))
        self.assertFalse(quantity_matches(0,0.5))
        self.assertFalse(quantity_matches(True,1))
class HeaderTests(unittest.TestCase):
    def test_actual_headers(self):
        h=['重量','尺寸 cm','Rack No.','商品明细码ERP','Part.No.','Description','Des china']+['日期入库']*5+['','']+['日期入库']*7+["Q'TY 总计",'销','存','物料码\u00a0  备注','成本单价 USD','成本单价 EUR','当前库存成本总计 EUR','','']
        self.assertEqual(DEFAULT_SHEET,'库存已有备件')
        self.assertEqual(detect_header({1:h,2:['物料数据']}),1)
        c=resolve_columns(h,DEFAULT_HEADERS)
        self.assertEqual((c['erp'],c['partNo'],c['stock'],c['location']),(4,5,24,3))
    def test_shifted_headers(self):
        h=list(reversed(list(DEFAULT_HEADERS.values())))
        self.assertEqual(detect_header({4:['标题'],5:h}),5)
        self.assertEqual(resolve_columns(h,DEFAULT_HEADERS)['erp'],len(h))
    def test_duplicate_header(self):
        h=list(DEFAULT_HEADERS.values())+['存']
        with self.assertRaises(ValueError): resolve_columns(h,DEFAULT_HEADERS)
        m=dict(DEFAULT_HEADERS,stock={'column':len(h),'header':'存'})
        self.assertEqual(resolve_columns(h,m)['stock'],len(h))
        with self.assertRaises(ValueError): resolve_columns(h,dict(m,stock={'column':2,'header':'存'}))
    def test_missing_and_manual_mapping(self):
        h=list(DEFAULT_HEADERS.values());h[0]='ERP新名称'
        self.assertEqual(detect_header({3:h}),3)
        with self.assertRaises(ValueError): resolve_columns(h,DEFAULT_HEADERS)
        self.assertEqual(resolve_columns(h,dict(DEFAULT_HEADERS,erp={'column':1,'header':'ERP新名称'}))['erp'],1)
    def test_ambiguous_header_rows(self):
        h=list(DEFAULT_HEADERS.values())
        self.assertIsNone(detect_header({2:h,10:h}))
        self.assertIsNone(detect_header({1:['重量','备注']}))
    def test_optional_skip_and_no_reuse(self):
        h=list(DEFAULT_HEADERS.values())
        m={k:v for k,v in DEFAULT_HEADERS.items() if k!='weight'}
        self.assertNotIn('weight',resolve_columns(h,m))
        with self.assertRaises(ValueError):resolve_columns(h,dict(m,weight='存'))
if __name__=='__main__':unittest.main()
