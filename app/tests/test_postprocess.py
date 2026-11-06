import math,sys,tempfile,unittest,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import core,postprocess
from unittest.mock import patch

class FinishingTests(unittest.TestCase):
    def test_empty_engine_is_not_successful_silence(self):
        synth=core.Synth({})
        synth.engine.iter_pcm=lambda *args:iter(())
        with self.assertRaises(core.TTSError):list(synth.stream('Hello world.'))

    def test_missing_ffmpeg_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder)/'raw.wav';target=Path(folder)/'master.wav'
            raw.write_bytes(b'original')
            with patch.object(postprocess,'ffmpeg_path',return_value=None):
                with self.assertRaises(RuntimeError):postprocess.polish_file(raw,target,24000,{})
            self.assertEqual(raw.read_bytes(),b'original')
            self.assertFalse(target.exists())

    def test_disabled_pcm_is_identical(self):
        data=b'\x00\x00\x01\x00'*500
        output,meta=postprocess.polish_pcm(data,24000,{},enabled=False)
        self.assertIs(output,data)
        self.assertFalse(meta['enabled'])

    def test_limits_and_voice_override(self):
        with self.assertRaises(ValueError):postprocess.profile({'postprocess':{'ratio':9}})
        with self.assertRaises(ValueError):postprocess.profile({},enabled='yes')
        self.assertFalse(postprocess.profile({'postprocess':{'voices':{'si':{'enabled':False}}}})['enabled'])

    def test_chain_order(self):
        chain=postprocess.filters(postprocess.profile({}),24000)
        self.assertLess(chain.index('agate'),chain.index('afftdn'))
        self.assertLess(chain.index('afftdn'),chain.index('equalizer'))
        self.assertIn('level=false',chain)

    def test_language_and_reference_are_independent(self):
        config={'voices':{'si':{'ref_audio_path':'ref.wav','prompt_text':'你好','prompt_lang':'zh','sample_steps':4}},'default_voice':'si'}
        payload=core.Engine(config).payload('Hello world',text_lang='en')
        self.assertEqual(payload['text_lang'],'en')
        self.assertEqual(payload['prompt_lang'],'zh')
        self.assertEqual(payload['sample_steps'],4)
        self.assertEqual(payload['dit_window'],0)
        with self.assertRaises(ValueError):core.text_language('invalid')

    def test_english_segments_keep_words(self):
        import re
        text='Please preserve the beginning and ending of every English word during speech synthesis. '*4
        segments=core.Segmenter().split(text)
        self.assertEqual(''.join(segments).replace(' ',''),text.replace(' ',''))
        self.assertEqual(re.findall('[A-Za-z]+',' '.join(segments)),re.findall('[A-Za-z]+',text))

    @unittest.skipUnless(postprocess.ffmpeg_path(),'FFmpeg unavailable')
    def test_real_ffmpeg_and_source_preserved(self):
        import struct
        for sr in (24000,48000):
            with self.subTest(sr=sr),tempfile.TemporaryDirectory(prefix='祀音 test ') as folder:
                raw=Path(folder)/'原声.wav';target=Path(folder)/'成品.wav'
                pcm=b''.join(struct.pack('<h',int(4500*math.sin(2*math.pi*330*i/sr))) for i in range(sr*2))
                with wave.open(str(raw),'wb') as wav:
                    wav.setparams((1,2,sr,0,'NONE','not compressed'));wav.writeframes(pcm)
                original=raw.read_bytes()
                meta=postprocess.polish_file(raw,target,sr,{})
                self.assertTrue(meta['enabled']);self.assertEqual(raw.read_bytes(),original)
                with wave.open(str(target),'rb') as wav:
                    self.assertEqual(wav.getparams()[:3],(1,2,sr))
                    self.assertLess(abs(wav.getnframes()-sr*2),sr*.05)
                self.assertFalse(list(Path(folder).glob('*.processing')))

if __name__=='__main__':unittest.main()
