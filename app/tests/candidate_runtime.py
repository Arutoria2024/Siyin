"""Isolated official patch test, never starts a second model beside production."""
import argparse,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from upgrade_probe import run
ROOT=Path(__file__).resolve().parents[1]
STAGE=Path(os.environ.get('SIYIN_UPGRADE_STAGE',str(ROOT.parent/'.upgrade')))
def ready(port,seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            result=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2))
            if result.get('ok'):return result
        except OSError:pass
        time.sleep(1)
    raise RuntimeError('candidate health timeout '+str(port))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',action='store_true');parser.add_argument('--benchmark',action='store_true');args=parser.parse_args()
    runtime=STAGE/('backup' if args.baseline else 'candidate')
    # Verify production engine is stopped before loading a candidate GPU model.
    try:urllib.request.urlopen('http://127.0.0.1:9880/health',timeout=1)
    except OSError:pass
    else:raise RuntimeError('production engine is running; stop its verified instance first')
    sys.path.insert(0,str(ROOT/'monitor'));import monitor
    children=[];logs=[]
    try:
        for name,command in [('sidecar',[str(ROOT/'python/python.exe'),str(runtime/'frontend/text_sidecar.py'),'--host','127.0.0.1','--port','19882']),('engine',[str(runtime/'engine/gsv_server.exe'),'--models',str(ROOT/'models'),'--device','vulkan','--port','19880','--sidecar','127.0.0.1:19882','--allow-path',str(ROOT)])]:
            log=(STAGE/(name+'.log')).open('wb');logs.append(log)
            children.append(subprocess.Popen(command,cwd=ROOT,env=monitor._env(),stdout=log,stderr=log,creationflags=0x08000000))
            ready(19882 if name=='sidecar' else 19880,100)
            print(name+' ready',flush=True)
        response=urllib.request.urlopen('http://127.0.0.1:19880/set_gpt_weights?weights_path=si',timeout=240).read()
        print('voice loaded',flush=True)
        if args.benchmark:
            import core,statistics,hashlib
            config=core.load_config(str(ROOT/'services/config.json'));config['engine']['port']=19880
            synth=core.Synth(config);measurements=[]
            for index in range(4):
                t0=time.perf_counter();first=None;pcm=bytearray()
                for chunk in synth.stream('你好，我是祀。这是一段语音合成测试，请仔细听清每一个字。','si',.88,24000,text_lang='zh'):
                    if first is None:first=time.perf_counter()-t0
                    pcm.extend(chunk)
                elapsed=time.perf_counter()-t0
                item={'iteration':index,'first_ms':round(first*1000),'total_ms':round(elapsed*1000),'rtf':elapsed/(len(pcm)/48000),'pcm_sha256':hashlib.sha256(pcm).hexdigest()}
                measurements.append(item);print(json.dumps(item),flush=True)
            label='baseline-warm' if args.baseline else 'candidate-warm'
            result={'measurements':measurements,'median_first_ms':statistics.median(m['first_ms'] for m in measurements[1:]),'median_total_ms':statistics.median(m['total_ms'] for m in measurements[1:]),'median_rtf':statistics.median(m['rtf'] for m in measurements[1:])}
            (STAGE/('validation/'+label+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        else:
            report=run('candidate',19880,STAGE/'validation')
            for item in report:
                assert not item.get('error'),item
                assert item['audio_s']>1 and item['peak']>.01,item
                assert abs(item['dc'])<.01 and .1<item['negative_fraction']<.9,item
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate();child.wait(timeout=15)
        for log in logs:log.close()
if __name__=='__main__':main()
