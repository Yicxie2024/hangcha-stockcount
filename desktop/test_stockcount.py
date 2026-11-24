import unittest, tempfile, json
from pathlib import Path
from stockcount import read_exports, propose, totals, digest, locate

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
    def test_invalid_qty(self):
        with self.assertRaises(ValueError): self.exports([rec('a',-1)])
if __name__=='__main__':unittest.main()
