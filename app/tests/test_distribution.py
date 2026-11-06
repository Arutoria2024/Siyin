import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app/desktop'))
from bootstrap import prepare


class DistributionTests(unittest.TestCase):
    def test_install_template_is_private_and_lan_opt_in(self):
        config = json.loads((ROOT / 'packaging/staging/app/services/config.json').read_text(encoding='utf-8'))
        self.assertFalse(config['gateway']['token'])
        self.assertEqual(config['gateway']['host'], '127.0.0.1')
        self.assertFalse(config['network']['lan_enabled'])
        self.assertEqual(config['network']['lan_port'], 9890)
        for voice in config['voices'].values():
            self.assertTrue(voice['ref_audio_path'].startswith('@APP_ROOT@/'))

    def test_two_installations_get_independent_keys_and_paths(self):
        template = (ROOT / 'packaging/staging/app/services/config.json').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as temporary:
            configs = []
            for name in ('应用 一', 'Second Location'):
                root = Path(temporary) / name
                (root / 'services').mkdir(parents=True)
                (root / 'models/voices').mkdir(parents=True)
                (root / 'services/config.json').write_text(template, encoding='utf-8')
                config = prepare(root)
                self.assertEqual(config['gateway']['host'], '127.0.0.1')
                self.assertFalse(config['network']['lan_enabled'])
                self.assertTrue(config['voices']['si']['ref_audio_path'].startswith(str(root.resolve())))
                configs.append(config)
            self.assertNotEqual(configs[0]['gateway']['token'], configs[1]['gateway']['token'])


if __name__ == '__main__':
    unittest.main()
