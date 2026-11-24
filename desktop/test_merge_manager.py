import unittest, tempfile, json
from pathlib import Path
from merge_manager import (analyze, aggregate, make_output, location_tokens, coverage, atomic_json, MERGED)
from stockcount import digest
from test_stockcount import rec

def docs(*groups):
    return [dict(name=f'employee{i}.json',data=dict(format='hangcha-stockcount-export',version=2,records=g,shelfCompletions=[])) for i,g in enumerate(groups)]

class MergeTests(unittest.TestCase):
    def test_no_excel_and_unknown_part(self):
        a=rec('a',12,'A010203',erp='91.06.06.910677230',partNo='AMDL120-610000-000')
        result=make_output(docs([a]),{},{});self.assertEqual(result['format'],MERGED);self.assertEqual(result['items'][0]['qty'],12);self.assertEqual(result['items'][0]['rackNo'],'A010203')
        self.assertEqual(result['unrecordedPolicy'],'unknown-not-zero')
    def test_same_employee_and_cross_employee(self):
        for worker in ('A','B'):
            a,b=rec('a',12),rec('b',12,worker=worker);items,c=analyze([a,b],{},{});self.assertEqual(len(c),1);self.assertFalse(c[0]['confirmed']);self.assertIn('同员工' if worker=='A' else '跨员工',c[0]['reason'])
            with self.assertRaises(ValueError):aggregate(items,c)
    def test_different_quantity_conflict(self):
        a,b=rec('a',12),rec('b',10,worker='B');self.assertEqual(len(analyze([a,b],{}, {})[1]),1)
    def test_different_parts_same_location(self):
        a,b=rec('a',12),rec('b',4,worker='B',erp='E2',partNo='P2');items,c=analyze([a,b],{},{});self.assertEqual(c,[]);self.assertEqual(len(aggregate(items,c)),2);self.assertEqual(len(coverage(items,[])),1)
    def test_same_part_other_location_decimal(self):
        a,b,c=rec('a',0.1),rec('b',0.2,'B0104'),rec('c',0.5,'C0104');x=make_output(docs([a],[b,c]),{}, {})['items'][0];self.assertEqual(x['qty'],0.8);self.assertEqual(len(x['locations']),3);self.assertEqual(x['rackNo'],'A0104/B0104/C0104')
    def test_zero_not_absent(self):
        a=rec('a',0);x=make_output(docs([a]),{}, {})['items'][0];self.assertEqual(x['qty'],0);self.assertEqual(x['rackNo'],'');self.assertEqual(x['locations'][0]['qty'],0)
    def test_parent_and_sibling(self):
        a,b=rec('a',12,'A0104'),rec('b',4,'A010401-II');self.assertEqual(len(analyze([a,b],{}, {})[1]),1)
        a,b=rec('a',12,'A010401-I-1'),rec('b',4,'A010401-I-10');self.assertEqual(analyze([a,b],{}, {})[1],[])
        a,b=rec('a',12,'A010401-I'),rec('b',4,'A010401-II');self.assertEqual(analyze([a,b],{}, {})[1],[])
    def test_floor_distinction(self):
        self.assertEqual(analyze([rec('a',loc='A01'),rec('b',loc='A01',physicalFloor=2)],{}, {})[1],[])
    def test_partial_id_overlap(self):
        a,b=rec('a'),rec('b',erp='',partNo='P1');self.assertIn('编号部分相同',analyze([a,b],{}, {})[1][0]['reason'])
        b['location']='B0104';items,c=analyze([a,b],{}, {});self.assertEqual(len(aggregate(items,c)),2)
    def test_pair_confirm_not_global(self):
        a,b,c=rec('a'),rec('b',12),rec('c',5);_,pairs=analyze([a,b],{},{});ack={pairs[0]['key']:'不同两批货'}
        items,pairs=analyze([a,b],{},ack);self.assertEqual(aggregate(items,pairs)[0]['qty'],22)
        items,pairs=analyze([a,b,c],{},ack);self.assertEqual(sum(not p['confirmed'] for p in pairs),2)
        with self.assertRaises(ValueError):aggregate(items,pairs)
    def test_revised_record_invalidates_ack(self):
        a,b=rec('a'),rec('b');_,c=analyze([a,b],{},{});ack={c[0]['key']:'两批'}
        b=dict(b,qty=3,updatedAt='2026-11-24T10:00:00Z');self.assertFalse(analyze([a,b],{},ack)[1][0]['confirmed'])
    def test_edit_invalidates_ack(self):
        a,b=rec('a'),rec('b');_,c=analyze([a,b],{},{});ack={c[0]['key']:'两批'}
        d={digest(a):dict(action='edit',qty=1.5,reason='复盘')};self.assertFalse(analyze([a,b],d,ack)[1][0]['confirmed'])
    def test_exclude_and_manual_recount(self):
        a,b=rec('a',10),rec('b',12);d={digest(a):dict(action='edit',qty=11.5,location='A0104',physicalFloor=1,reason='复盘'),digest(b):dict(action='exclude',reason='重复')};out=make_output(docs([a],[b]),d,{})
        self.assertEqual(out['items'][0]['qty'],11.5);self.assertEqual(len(out['latestSourceRecords']),2);self.assertEqual(len(out['acceptedRecords']),1);self.assertEqual(len(out['recordDecisions']),2)
    def test_corrected_location_rechecks(self):
        a,b=rec('a'),rec('b',loc='B0104');d={digest(b):dict(action='edit',qty=12,location='A0104',physicalFloor=1,reason='纠正')};self.assertEqual(len(analyze([a,b],d,{})[1]),1)
    def test_deleted_latest_not_duplicate(self):
        a,b=rec('a'),rec('b');deleted=dict(b,deleted=True,updatedAt='2026-11-24T10:00:00Z');out=make_output(docs([a,b],[a,deleted]),{},{});self.assertEqual(out['items'][0]['qty'],10);self.assertTrue(out['latestSourceRecords'][1]['deleted'])
    def test_measurements_notes_and_provenance(self):
        a,b=rec('a',lengthCm=2,weightKg=0.5,note='实测',partName='wheel'),rec('b',loc='B0104',lengthCm=3,weightKg=0.5,worker='B');out=make_output(docs([a,b]),{},{});x=out['items'][0];self.assertEqual(len(x['measurements']),2);self.assertEqual(x['notes'][0]['note'],'实测');self.assertEqual(x['workers'],['A','B']);self.assertEqual(x['recordIds'],['a','b'])
    def test_shelf_markers_advisory(self):
        a=rec('a');d=docs([a]);d[0]['data']['shelfCompletions']=[dict(id='s1',shelf='A01',physicalFloor=1,worker='A',session='2026',snapshotId='base',updatedAt=a['updatedAt']),dict(id='s2',shelf='A01',physicalFloor=1,worker='B',session='2026',snapshotId='base',updatedAt=a['updatedAt'])];out=make_output(d,{},{});self.assertEqual(len(out['coverageAdvisories']),1);self.assertEqual(out['items'][0]['qty'],10)
    def test_atomic_roundtrip(self):
        out=make_output(docs([rec('a',0.5)]),{},{});
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'merged.json';atomic_json(p,out);self.assertEqual(json.loads(p.read_text()),out)
    def test_location_validation(self):
        for loc,f in [('F0904',1),('A0105',1),('A010406',1),('A0104-II',1),('A010401-IV',1)]:
            with self.subTest(loc=loc),self.assertRaises(ValueError):location_tokens(loc,f)
        self.assertEqual(location_tokens('H130901-III-1-2',3),('H','13','09','01','III','1-2'))
    def test_no_valid_records(self):
        a=rec('a');
        with self.assertRaises(ValueError):make_output(docs([a]),{digest(a):dict(action='exclude',reason='错误')},{})
if __name__=='__main__':unittest.main()
