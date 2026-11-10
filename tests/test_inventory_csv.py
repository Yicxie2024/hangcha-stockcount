import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from stockcount import build_inventory

class PublicDemoImportTest(unittest.TestCase):
 def test_demo_csv_import(self):
  catalog,notes=build_inventory(ROOT/'examples/演示ERP库存.csv')
  self.assertEqual(len(catalog['items']),5)
  self.assertEqual(catalog['items'][0]['partNo'],'DEMO-PART-001')
  self.assertEqual(catalog['format'],'hangcha-stockcount-catalog')

if __name__=='__main__':unittest.main()
