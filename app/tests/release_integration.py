"""Real GPU tests, strictly sequential. Output contains no credentials."""
import json,re,time,urllib.request,urllib.error,wave,subprocess
from pathlib import Path
BASE='http://127.0.0.1:9888'
html=urllib.request.urlopen(BASE).read().decode();token=re.search(r'name="session-token" content="([^"]+)"',html)[1]
def api(action,body=None):
 req=urllib.request.Request(BASE+'/api/'+action,data=json.dumps(body).encode() if body is not None else None,headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(req,timeout=180))
text=('清晨的风吹过山间，远处传来轻轻的回声。我们沿着小路慢慢向前，听见溪水流过石头。'*60)
assert len(text)>2000
i=api('workbench/submit',{'text':text,'title':'长文与队列验收','sr':24000})['id']
j=api('workbench/submit',{'text':'你好，四十八千赫兹验收。','title':'取消重试与48k验收','sr':48000})['id']
api('workbench/cancel',{'id':j});assert next(t for t in api('workbench')['tasks'] if t['id']==j)['state']=='cancelled'
end=time.time()+900;last=None
while time.time()<end:
 tasks=api('workbench')['tasks'];assert sum(t['state']=='running' for t in tasks)<=1
 t=next(t for t in tasks if t['id']==i)
 if t['done']!=last:print('long document',t['done'],'/',t['total'],flush=True);last=t['done']
 if t['state'] in ('completed','failed'):break
 time.sleep(2)
assert t['state']=='completed',t
assert t['done']==t['total'] and t['total']>1
api('workbench/retry',{'id':j})
for _ in range(90):
 t=next(t for t in api('workbench')['tasks'] if t['id']==j)
 if t['state'] in ('completed','failed'):break
 time.sleep(1)
assert t['state']=='completed',t
path=Path(__file__).resolve().parents[1]/'out/workbench'/j/'master.wav'
with wave.open(str(path)) as f:assert f.getframerate()==48000 and f.getnchannels()==1
request=urllib.request.Request(BASE+f'/audio/{j}/master.wav',headers={'Range':'bytes=0-43'})
with urllib.request.urlopen(request) as r:assert r.status==206 and r.read()[:4]==b'RIFF'
print('PASS: long document, serial queue, queued cancel/retry, 48k WAV, range playback',flush=True)
