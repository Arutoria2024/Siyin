"""Explicit real-GPU upgrade probe. Writes only the requested validation folder."""
import argparse,json,math,os,shutil,struct,sys,time,urllib.request,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'))
import core
from postprocess import polish_file

def run(label,port,output):
    config=core.load_config(str(ROOT/'services/config.json'))
    config['engine']['port']=port
    synth=core.Synth(config)
    output.mkdir(parents=True,exist_ok=True)
    samples=[('zh','你好，我是祀。这是一段语音合成测试，请仔细听清每一个字。'),('en','Hello, this is a voice synthesis test. Please listen carefully to every word.'),('auto','你好，welcome to Siyin。This is a test of English and Chinese speech.')]
    report=[]
    for lang,text in samples:
        t0=time.perf_counter();first=None;pcm=bytearray()
        try:
            for chunk in synth.stream(text,'si',.88,24000,text_lang=lang):
                if first is None:first=time.perf_counter()-t0
                pcm.extend(chunk)
            elapsed=time.perf_counter()-t0
            if not pcm:raise ValueError('empty audio')
            path=output/(label+'-'+lang+'.wav')
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'));wav.writeframes(pcm)
            import numpy as np
            values=np.frombuffer(pcm,dtype='<i2').astype(float)/32768
            item={'label':label,'language':lang,'first_ms':round(first*1000),'generation_ms':round(elapsed*1000),'audio_s':round(len(values)/24000,3),'rtf':round(elapsed/(len(values)/24000),4),'dc':round(float(values.mean()),6),'peak':round(float(np.max(np.abs(values))),4),'negative_fraction':round(float(np.mean(values<0)),4),'path':str(path)}
            item['finishing']=polish_file(path,output/(label+'-'+lang+'-processed.wav'),24000,config)
            report.append(item)
            print(json.dumps(item,ensure_ascii=True),flush=True)
        except Exception as exc:
            report.append({'label':label,'language':lang,'error':str(exc)})
            print(json.dumps(report[-1],ensure_ascii=True),flush=True)
    (output/(label+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--port',type=int,default=9880);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.label,a.port,a.output)
