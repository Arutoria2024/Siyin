"""Opt-in live integration: creates labelled validation works, never alters defaults."""
import json,os,re,sys,time,urllib.request,urllib.error,wave,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
import desktop_server
port=json.loads((ROOT/'run/desktop-server.json').read_text(encoding='utf-8'))['port']
session=desktop_server.probe(port,ROOT)
assert session
BASE=session['base_url']
def api(path,body=None):
    request=urllib.request.Request(BASE+'/api/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Workbench-Token':session['token']})
    return json.load(urllib.request.urlopen(request,timeout=180))
def wait(i):
    end=time.monotonic()+180
    while time.monotonic()<end:
        task=next(t for t in api('workbench')['tasks'] if t['id']==i)
        if task['state'] in ('completed','failed'):assert task['state']=='completed',task['error'];return task
        time.sleep(.5)
    raise AssertionError('task timed out')
report=[]
for lang,sr,finish,text in [('en',24000,True,'Hello, this is an English speech test.'),('auto',48000,True,'你好，welcome to Siyin。请听清每个字。'),('zh',24000,False,'关闭后处理时，请保留原始声音。')]:
    payload={'text':text,'title':'升级验收 '+lang,'text_lang':lang,'sr':sr}
    if not finish:payload['postprocess']=False
    i=api('workbench/submit',payload)['id']
    t=wait(i);folder=ROOT/'out/workbench'/i
    assert t['raw_available'] and t['postprocess']==int(finish)
    for name in ('raw.wav','master.wav'):
        with wave.open(str(folder/name),'rb') as f:assert f.getparams()[:3]==(1,2,sr);assert f.getnframes()>sr
    if not finish:assert (folder/'raw.wav').read_bytes()==(folder/'master.wav').read_bytes()
    assert len(api('workbench/waveform/'+i))==180
    for fmt in api('workbench')['formats']:
        result=api('workbench/export',{'id':i,'format':fmt})
        assert urllib.request.urlopen(BASE+result['url']).status==200
        if fmt!='pcm':
            target=folder/('master.wav' if fmt=='wav' else 'export.'+fmt)
            out=subprocess.check_output([str(ROOT/'tools/ffmpeg/ffprobe.exe'),'-v','error','-show_entries','stream=codec_name,sample_rate,channels','-of','json',str(target)],creationflags=0x08000000)
            stream=json.loads(out)['streams'][0];assert stream['channels']==1
            expected_sr=48000 if fmt=='ogg' else sr
            assert int(stream['sample_rate'])==expected_sr,(fmt,stream)
    report.append({k:t[k] for k in ['id','title','text_lang','sr','postprocess','first_ms','post_ms','total_ms','duration']})
    print(lang+' workbench, automatic finishing, waveform and exports OK',flush=True)

config=json.loads((ROOT/'services/config.json').read_text(encoding='utf-8'))
headers={'Authorization':'Bearer '+config['gateway']['token'],'Content-Type':'application/json'}
for body,code in [({'text':'Hello.','text_lang':'invalid'},400),({'text':'Hello.','postprocess':True},400)]:
    req=urllib.request.Request('http://127.0.0.1:9881/v1/text-to-speech/si/stream?output_format=pcm&sample_rate=24000',data=json.dumps(body).encode(),headers=headers)
    try:urllib.request.urlopen(req);raise AssertionError('invalid stream request accepted')
    except urllib.error.HTTPError as e:assert e.code==code
for finish in (False,True):
    req=urllib.request.Request('http://127.0.0.1:9881/v1/tts',data=json.dumps({'text':'Hello, welcome.','text_lang':'en','postprocess':finish}).encode(),headers=headers)
    with urllib.request.urlopen(req,timeout=120) as response:
        import io
        data=response.read()
        with wave.open(io.BytesIO(data),'rb') as audio:
            assert audio.getparams()[:3]==(1,2,24000) and audio.getnframes()>2400
        assert response.headers['X-Postprocess']==('finished' if finish else 'raw')
report_dir=Path(os.environ.get('SIYIN_UPGRADE_REPORT_DIR',str(ROOT/'out/upgrade-validation')))
report_dir.mkdir(parents=True,exist_ok=True)
(report_dir/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Whole WAV postprocess on/off and invalid parameter errors OK',flush=True)
