import json,sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from stockcount import records_from_folder,summarize


def rec(id='r1',qty=12,ts='2026-11-10T12:00:00.000Z',deleted=False):
 return {'id':id,'session':'2026年度盘库','worker':'A','location':'A0102','physicalFloor':1,
 'erp':'ERP001','partNo':'PART001','partName':'演示零件','qty':qty,
 'createdAt':'2026-11-10T11:00:00.000Z','updatedAt':ts,'deleted':deleted}

CAT={'snapshotId':'sample','items':[{'erp':'ERP001','partNo':'PART001','name':'演示零件',
 'bookQty':12,'location':'A0102','locations':['A0102'],'sourceSheet':'演示'}]}

class StockCountDesktopIntegrationTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.dir=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def export(self,name,items):
  (self.dir/name).write_text(json.dumps({'format':'hangcha-stockcount-export','version':2,
   'records':items,'shelfCompletions':[]},ensure_ascii=False),'utf-8')
 def test_newer_tombstone_removes_old_export_and_is_audited(self):
  self.export('old.json',[rec()]);self.export('new.json',[rec(ts='2026-11-10T12:01:00.000Z',deleted=True)])
  rows,files,errors,conflicts,deleted=records_from_folder(self.dir)
  self.assertEqual((len(rows),len(deleted),len(conflicts)),(0,1,0))
  sheets,stats=summarize(CAT,self.dir)
  self.assertEqual(len(sheets['原始盘点记录']),1)
  self.assertEqual(len(sheets['已删除记录']),2)
  self.assertEqual(sheets['库存对比'][1][6],'未盘点')
 def test_undo_after_deletion_restores_same_id(self):
  self.export('1.json',[rec()]);self.export('2.json',[rec(ts='2026-11-10T12:01:00.000Z',deleted=True)])
  self.export('3.json',[rec(qty=13,ts='2026-11-10T12:02:00.000Z')])
  rows,_,_,conflicts,deleted=records_from_folder(self.dir)
  self.assertEqual((len(rows),len(deleted),len(conflicts)),(1,0,0))
  self.assertEqual(rows[0]['qty'],13)
 def test_different_record_ids_are_not_deduplicated(self):
  self.export('a.json',[rec('r1'),rec('r2',13)])
  rows,_,_,_,deleted=records_from_folder(self.dir)
  self.assertEqual(len(rows),2)
  sheets,stats=summarize(CAT,self.dir)
  self.assertEqual(stats['conflicts'],1)
  self.assertEqual(sheets['库存对比'][1][6],'重复盘点待复核')
 def test_equal_timestamp_conflict_excluded(self):
  self.export('1.json',[rec()]);self.export('2.json',[rec(deleted=True)])
  rows,_,_,conflicts,deleted=records_from_folder(self.dir)
  self.assertEqual(len(rows),0)
  self.assertEqual(len(deleted),0)
  self.assertTrue(conflicts)
 def test_modification_is_one_latest_valid_record(self):
  self.export('1.json',[rec(qty=12)]);self.export('2.json',[rec(qty=15,ts='2026-11-10T12:03:00.000Z')])
  rows,_,_,_,deleted=records_from_folder(self.dir)
  self.assertEqual([r['qty'] for r in rows],[15])

if __name__=='__main__':unittest.main()
