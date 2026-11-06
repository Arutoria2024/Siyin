import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class BrandingTests(unittest.TestCase):
 def test_single_brand_name(self):
  source=(ROOT/'app/ui/src/main.tsx').read_text(encoding='utf-8')
  self.assertIn('<span className="seal">祀</span><div>音 <small>',source)
  self.assertNotIn('<div>祀音 <small>',source)
 def test_chinese_release_name(self):
  installer=(ROOT/'packaging/installer.iss').read_text(encoding='utf-8')
  self.assertIn('#define AppName "祀音"',installer)
  self.assertIn('OutputBaseFilename=祀音安装包-1.0.0',installer)
  self.assertIn('祀音.exe',installer)
  self.assertIn("create_window('祀音'",(ROOT/'app/desktop/launch.py').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
