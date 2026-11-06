import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'monitor'))
import monitor
class ConnectionTests(unittest.TestCase):
 def check(self,engine,gateway):
  with patch.object(monitor,'_http_json',side_effect=[engine,gateway]),patch.object(monitor,'gpu_info',return_value=None),patch.object(monitor,'read_cfg',return_value={}),patch.object(monitor,'token',return_value=''):
   return monitor.status()
 def test_ready(self):
  s=self.check({'ok':True},{'ok':True});self.assertTrue(s['gateway_reachable']);self.assertTrue(s['gateway_ok']);self.assertTrue(s['engine_ok'])
 def test_gateway_online_engine_not_ready(self):
  s=self.check({'ok':False},{'ok':False});self.assertTrue(s['gateway_reachable']);self.assertFalse(s['gateway_ok'])
 def test_gateway_offline(self):
  s=self.check({'ok':True},OSError('offline'));self.assertFalse(s['gateway_reachable']);self.assertFalse(s['gateway_ok'])
if __name__=='__main__':unittest.main()
