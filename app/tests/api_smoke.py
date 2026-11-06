import json,re,time,urllib.request,urllib.error,wave
BASE='http://127.0.0.1:9888'
html=urllib.request.urlopen(BASE).read().decode()
token=re.search(r'name="session-token" content="([^"]+)"',html)[1]
def api(path,body=None):
    req=urllib.request.Request(BASE+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=180))
try:urllib.request.urlopen(BASE+'/api/workbench');raise AssertionError('unauthenticated read accepted')
except urllib.error.HTTPError as e:assert e.code==403
i=api('workbench/submit',{'text':'你好，我是祀。这是一段语音工作台验收测试。','title':'工作台验收'})['id']
for _ in range(90):
    task=next(t for t in api('workbench')['tasks'] if t['id']==i)
    if task['state'] in ('completed','failed'):break
    time.sleep(1)
assert task['state']=='completed',task
print(json.dumps(task,ensure_ascii=False))
for fmt in ('wav','mp3','flac','m4a','ogg','pcm'):
    result=api('workbench/export',{'id':i,'format':fmt})
    response=urllib.request.urlopen(BASE+result['url']);assert int(response.headers['Content-Length'])>0
    print(fmt,'OK',response.headers['Content-Length'])
