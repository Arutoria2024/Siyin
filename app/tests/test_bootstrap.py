import unittest,tempfile,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from bootstrap import prepare
class BootstrapTests(unittest.TestCase):
 def test_private_key_and_paths(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary).resolve();(root/'services').mkdir();(root/'models/voices/si').mkdir(parents=True)
   (root/'services/config.json').write_text(json.dumps({'gateway':{'token':''},'voices':{'si':{'ref_audio_path':'@APP_ROOT@/models/ref.wav'}}}),encoding='utf-8')
   (root/'models/voices/si/manifest.json').write_text('{"ar":"@APP_ROOT@/models/voice.gguf"}',encoding='utf-8')
   config=prepare(root);self.assertGreater(len(config['gateway']['token']),32);self.assertEqual(config['voices']['si']['ref_audio_path'],str(root/'models/ref.wav'))
   again=prepare(root);self.assertEqual(config['gateway']['token'],again['gateway']['token'])
   self.assertEqual(json.loads((root/'models/voices/si/manifest.json').read_text())['ar'],str(root/'models/voice.gguf'))
if __name__=='__main__':unittest.main()
