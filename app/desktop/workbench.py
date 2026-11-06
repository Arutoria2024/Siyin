"""Local workbench API. Does not load inference models."""
import base64, collections, hashlib, http.client, json, os, re, secrets, shutil, sqlite3, subprocess, threading, time, urllib.request, uuid, wave
from pathlib import Path
from identities import identity,title_for,migrate
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'))
from postprocess import profile, polish_file
from core import text_language
DATA = ROOT / 'out' / 'workbench'
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'library.sqlite'
TOKEN = secrets.token_urlsafe(32)
PAUSED = False
HOT = False
HISTORY = collections.deque(maxlen=450)
CURRENT = None
SAMPLE = {}
LAST_SEEN = 0.0
FORMATS = {'wav':None, 'pcm':'pcm_s16le', 'mp3':'libmp3lame', 'flac':'flac', 'm4a':'aac', 'ogg':'libopus'}
FFMPEG = str(ROOT/'tools/ffmpeg/ffmpeg.exe') if (ROOT/'tools/ffmpeg/ffmpeg.exe').exists() else shutil.which('ffmpeg')
AVAILABLE=['wav']
if FFMPEG:
    try:
        encoders=subprocess.check_output([FFMPEG,'-hide_banner','-encoders'],timeout=10,creationflags=0x08000000,stderr=subprocess.DEVNULL).decode('utf-8','replace')
        AVAILABLE += [fmt for fmt,codec in FORMATS.items() if codec and re.search(r'\b'+codec+r'\b',encoders)]
    except (OSError,subprocess.SubprocessError):pass
def db():
    c=sqlite3.connect(DB, timeout=15); c.row_factory=sqlite3.Row; return c
with db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, text TEXT, voice TEXT, speed REAL, sr INTEGER, state TEXT, done INTEGER DEFAULT 0, total INTEGER, created REAL, error TEXT DEFAULT "", first_ms REAL, total_ms REAL, duration REAL DEFAULT 0)')
    migrate(c)
    c.execute("UPDATE tasks SET state='interrupted' WHERE state IN ('queued','running','stopping')")
def rows():
    with db() as c:return [dict(r,identity=json.loads(r['identity'] or '{}')) for r in c.execute('SELECT * FROM tasks ORDER BY created DESC')]
def update(i, **fields):
    with db() as c:c.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', [*fields.values(),i])
def split(text, limit=1800):
    result=[]; chunk=''
    for sentence in re.findall(r'[^。！？!?\n]+[。！？!?\n]*|[。！？!?\n]+', text):
        if chunk and len(chunk)+len(sentence)>limit:
            result.append(chunk);chunk=''
        while sentence:
            take=sentence[:limit-len(chunk)];chunk+=take;sentence=sentence[len(take):]
            if len(chunk)==limit or sentence:result.append(chunk);chunk=''
        if len(chunk)>limit-200:result.append(chunk);chunk=''
    if chunk.strip():result.append(chunk)
    return result
def cfg():return json.loads((ROOT/'services/config.json').read_text(encoding='utf-8'))
def add(body):
    text=str(body.get('text','')).strip()
    if not text or len(text)>500000:raise ValueError('请输入文本，单个文稿最多 50 万字')
    config=cfg();voice=body.get('voice',config.get('default_voice','si'))
    if voice not in config['voices']:raise ValueError('音色不存在')
    speed=float(body.get('speed',config['voices'][voice].get('speed_factor',.88)));sr=int(body.get('sr',24000))
    if not .6<=speed<=1.2 or sr not in (24000,48000):raise ValueError('语速或采样率超出范围')
    language=text_language(body.get('text_lang','zh')) or 'zh'
    options=body.get('postprocess_options',{})
    if not isinstance(options,dict) or any(k not in ('breath_guard','eq') for k in options):raise ValueError('无效后处理选项')
    finishing=profile(config,voice,body.get('postprocess'))
    finishing.update(options)
    finishing=profile({'postprocess':finishing},voice)
    i=uuid.uuid4().hex
    title,origin=title_for(text,str(body.get('title') or ''),str(body.get('filename') or ''))
    if body.get('filename') and title==Path(str(body['filename'])).stem:origin='filename'
    with db() as c:
        c.execute('INSERT INTO tasks(id,title,text,voice,speed,sr,state,total,created,title_source,source_type,identity,text_lang,postprocess,postprocess_config) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (i,title,text,voice,speed,sr,'queued',len(split(text)),time.time(),origin,'synthesis',json.dumps(identity(voice),ensure_ascii=False),language,int(finishing['enabled']),json.dumps(finishing)))
    return {'id':i}
def merge_audio(segments,target,sr):
    partial=target.with_name(target.name+'.part')
    with wave.open(str(partial),'wb') as out:
        out.setparams((1,2,sr,0,'NONE','not compressed'))
        for segment in segments:
            with wave.open(str(segment),'rb') as source:
                if source.getparams()[:3]!=(1,2,sr):raise ValueError('分段音频格式不一致')
                while True:
                    data=source.readframes(32768)
                    if not data:break
                    out.writeframesraw(data)
    os.replace(partial,target)

def worker():
    global CURRENT,HOT
    while True:
        time.sleep(.3)
        temp=(SAMPLE.get('gpu') or {}).get('temp_c')
        if temp is not None:
            if temp>=80:HOT=True
            elif temp<=75:HOT=False
        if PAUSED or HOT:continue
        task=next((r for r in reversed(rows()) if r['state']=='queued'),None)
        if not task:continue
        i=task['id'];CURRENT=i;t0=time.monotonic();update(i,state='running',error='')
        folder=DATA/i;folder.mkdir(exist_ok=True)
        try:
            raw_folder=folder/'raw_segments';raw_folder.mkdir(exist_ok=True)
            finishing=json.loads(task.get('postprocess_config') or '{}')
            finishing['enabled']=bool(task.get('postprocess'))
            processing_ms=task.get('post_ms') or 0
            with (folder/'live.pcm').open('wb') as live:
                for previous in sorted(folder.glob('[0-9]*.wav'))[:task['done']]:
                    raw_previous=raw_folder/previous.name
                    with wave.open(str(raw_previous if raw_previous.exists() else previous),'rb') as source:
                        while True:
                            chunk=source.readframes(32768)
                            if not chunk:break
                            live.write(chunk)
            for index,text in enumerate(split(task['text'])):
                if next(r for r in rows() if r['id']==i)['state']=='stopping':break
                target=folder/f'{index:05}.wav'
                if index<task['done'] and target.exists():continue
                raw_target=raw_folder/target.name
                body=json.dumps({'text':text,'speed':task['speed'],'text_lang':task.get('text_lang') or 'zh'}).encode()
                req=urllib.request.Request(f'http://127.0.0.1:9881/v1/text-to-speech/{task["voice"]}/stream?output_format=pcm&sample_rate={task["sr"]}',data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+cfg()['gateway'].get('token','')})
                carry=b'';count=0
                if raw_target.exists():
                    with wave.open(str(raw_target),'rb') as source,(folder/'live.pcm').open('ab',buffering=0) as live:
                        while True:
                            chunk=source.readframes(32768)
                            if not chunk:break
                            live.write(chunk)
                else:
                    receive_segment(req,raw_target,folder/'live.pcm',task['sr'],i,index,task['done'],t0)
                if next(r for r in rows() if r['id']==i)['state']=='stopping':break
                result=polish_file(raw_target,target,task['sr'],{'postprocess':finishing},task['voice'])
                processing_ms+=result['elapsed_ms']
                update(i,done=index+1,post_ms=processing_ms)
            latest=next(r for r in rows() if r['id']==i)
            if latest['state']=='stopping':update(i,state='cancelled');continue
            segments=sorted(folder.glob('[0-9]*.wav'))
            merge_audio(segments,folder/'master.wav',task['sr'])
            merge_audio([raw_folder/s.name if (raw_folder/s.name).exists() else s for s in segments],folder/'raw.wav',task['sr'])
            with wave.open(str(folder/'master.wav'),'rb') as audio:duration=audio.getnframes()/audio.getframerate()
            update(i,state='completed',duration=duration,total_ms=round((time.monotonic()-t0)*1000),raw_available=1)
        except Exception as exc:update(i,state='failed',error=str(exc))
        finally:CURRENT=None

def receive_segment(req,target,live_path,sr,i,index,done,t0):
    carry=b'';count=0
    with urllib.request.urlopen(req,timeout=180) as response, wave.open(str(target)+'.part','wb') as out, live_path.open('ab',buffering=0) as live:
        out.setparams((1,2,sr,0,'NONE','not compressed'))
        while True:
            raw=response.read1(8192)
            if not raw:break
            if count==0 and index==done:update(i,first_ms=round((time.monotonic()-t0)*1000))
            raw=carry+raw;n=len(raw)&~1;carry=raw[n:];out.writeframesraw(raw[:n]);live.write(raw[:n]);count+=n
        if carry or not count:raise ValueError('音频流不完整或为空')
    os.replace(str(target)+'.part',target)
EXPORT_LOCK=threading.Lock()
def install(monitor):
    original=monitor.H
    class Handler(original):
        def local_host(self):
            return self.headers.get('Host','').split(':')[0] in ('127.0.0.1','localhost')
        def allowed(self):
            origin=self.headers.get('Origin')
            port=self.server.server_port
            return self.headers.get('X-Workbench-Token')==TOKEN and (not origin or origin in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'))
        def do_GET(self):
            global LAST_SEEN
            if not self.local_host():return self._send(403,'{}')
            path=self.path.split('?')[0]
            if path=='/api/workbench/network':
                if not self.allowed():return self._send(403,'{}')
                result=monitor.LAN.status()
                result['local_workbench']=f'http://127.0.0.1:{monitor.MONITOR_PORT}'
                result['can_manage']=not getattr(self,'is_lan',False)
                return self._send(200,json.dumps(result,ensure_ascii=False))
            if path=='/api/workbench/instance':
                return self._send(200,json.dumps({'application':'siyin-workbench','protocol':1,'root':str(ROOT),'pid':os.getpid()}))
            if path.startswith('/media/voices/'):
                name=path.rsplit('/',1)[1]
                if not re.fullmatch(r'[a-f0-9]{64}\.jpg',name):return self._send(404,'')
                file=DATA/'identities'/name
                return self._send(200,file.read_bytes(),'image/jpeg') if file.is_file() else self._send(404,'')
            if path.startswith('/api/workbench/waveform/'):
                if not self.allowed():return self._send(403,'{}')
                i=path.rsplit('/',1)[1]
                if not re.fullmatch('[a-f0-9]{32}',i):return self._send(400,'{}')
                try:
                    import array
                    peaks=[]
                    with wave.open(str(DATA/i/'master.wav'),'rb') as f:
                        frames=f.getnframes()
                        for index in range(180):
                            f.setpos(min(frames,index*frames//180))
                            values=array.array('h',f.readframes(min(1024,max(1,frames//180))))
                            peaks.append(max((abs(v)/32768 for v in values),default=0))
                    return self._send(200,json.dumps(peaks))
                except (OSError,wave.Error):return self._send(404,'[]')
            if path=='/api/status':return self._send(200,json.dumps(SAMPLE,ensure_ascii=False))
            if path=='/api/workbench':
                if not self.allowed():return self._send(403,'{}')
                LAST_SEEN=time.time()
                return self._send(200,json.dumps({'tasks':rows(),'status':SAMPLE,'history':[p for p in HISTORY if time.time()-p['ts']<=900],'paused':PAUSED,'hot':HOT,'formats':AVAILABLE,'config':{'voice':cfg().get('default_voice'),'voices':list(cfg()['voices']),'voice_details':{v:identity(v) for v in cfg()['voices']}}},ensure_ascii=False))
            if path.startswith('/audio/'):
                parts=path.split('/')
                if len(parts)!=4 or not re.fullmatch('[a-f0-9]{32}',parts[2]):return self._send(404,'{}')
                if parts[3]=='live':
                    if not self.allowed():return self._send(403,'{}')
                    self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Connection','close');self.end_headers();self.close_connection=True
                    position=0
                    while True:
                        file=DATA/parts[2]/'live.pcm'
                        try:
                            with file.open('rb') as f:
                                f.seek(position);chunk=f.read(32768)
                            if chunk:self.wfile.write(chunk);self.wfile.flush();position+=len(chunk);continue
                        except FileNotFoundError:pass
                        task=next((r for r in rows() if r['id']==parts[2]),None)
                        if not task or task['state'] not in ('running','queued'):return
                        time.sleep(.05)
                file=DATA/parts[2]/parts[3]
                if not file.is_file() or file.suffix not in ('.wav','.mp3','.flac','.m4a','.ogg','.pcm'):return self._send(404,'{}')
                size=file.stat().st_size;start=0;end=size-1
                request_range=self.headers.get('Range')
                if request_range:
                    match=re.fullmatch(r'bytes=(\d+)-(\d*)',request_range)
                    if not match:return self._send(416,'')
                    start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
                    if start>end:return self._send(416,'')
                self.send_response(206 if request_range else 200)
                self.send_header('Accept-Ranges','bytes')
                if request_range:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.send_header('Content-Type','audio/wav' if file.suffix=='.wav' else 'application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.end_headers()
                with file.open('rb') as f:
                    f.seek(start);remaining=end-start+1
                    while remaining:
                        chunk=f.read(min(65536,remaining))
                        if not chunk:break
                        self.wfile.write(chunk);remaining-=len(chunk)
                return
            if path=='/' or path.startswith('/assets/'):
                file=ROOT/'ui/dist'/('index.html' if path=='/' else path.lstrip('/'))
                if file.is_file() and (ROOT/'ui/dist').resolve() in file.resolve().parents:
                    import mimetypes
                    data=file.read_bytes()
                    if path=='/':data=data.replace(b'__SESSION_TOKEN__',TOKEN.encode())
                    return self._send(200,data,mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
            return super().do_GET()
        def do_POST(self):
            global PAUSED
            if not self.local_host():return self._send(403,'{}')
            if not self.allowed():return self._send(403,json.dumps({'error':'会话已失效，请重新打开工作台'}))
            path=self.path.split('?')[0]
            if not path.startswith('/api/workbench/') :return super().do_POST()
            try:
                n=int(self.headers.get('Content-Length',0))
                if n>2000000:raise ValueError('请求过大')
                body=json.loads(self.rfile.read(n) or '{}');action=path.rsplit('/',1)[1]
                if action=='network':
                    if CURRENT:raise ValueError('当前正在合成，请完成后再修改网络设置。')
                    result=monitor.LAN.configure(body.get('enabled'),body.get('port'))
                elif action=='network-firewall':
                    enabled,_=__import__('lan_access').settings(cfg())
                    result={'firewall':monitor.LAN.firewall_apply(enabled)}
                elif action=='network-key':result={'key':cfg()['gateway'].get('token','')}
                elif action=='submit':result=add(body)
                elif action=='pause':PAUSED=not PAUSED;result={'paused':PAUSED}
                elif action in ('cancel','retry'):
                    task=next(r for r in rows() if r['id']==body['id'])
                    if action=='retry' and task['state'] not in ('failed','interrupted','cancelled'):raise ValueError('此任务不可重试')
                    if action=='cancel' and task['state'] not in ('queued','running'):raise ValueError('此任务不可取消')
                    update(task['id'],state=('queued' if action=='retry' else 'stopping' if task['state']=='running' else 'cancelled'));result={}
                elif action=='export':
                    i=body['id'];fmt=body.get('format','wav')
                    if not re.fullmatch('[a-f0-9]{32}',i) or fmt not in AVAILABLE:raise ValueError('无效格式或编码器不可用')
                    source=DATA/i/'master.wav';target=source.with_name('export.'+fmt)
                    if not source.exists():raise ValueError('请等待作品合成完成')
                    with EXPORT_LOCK:
                        while CURRENT:time.sleep(.2)
                        if fmt=='wav':target=source
                        else:
                            if not FFMPEG:raise ValueError('未找到 FFmpeg，请在 tools/ffmpeg 放入 ffmpeg.exe')
                            args=[FFMPEG,'-v','error','-y','-i',str(source),'-c:a',FORMATS[fmt],'-threads','2']
                            if fmt in ('mp3','m4a','ogg'):args+=['-b:a',{'mp3':'192k','m4a':'128k','ogg':'64k'}[fmt]]
                            if fmt=='pcm':args+=['-f','s16le']
                            subprocess.run(args+[str(target)],check=True,timeout=600,creationflags=0x08000000,capture_output=True)
                    result={'url':f'/audio/{i}/{target.name}'}
                elif action=='mcp':result={'mcpServers':{'gsv-tts':{'command':str(ROOT/'python/python.exe'),'args':[str(ROOT/'services/mcp/mcp_server.py')]}}}
                elif action=='params':
                    import sys
                    sys.path.insert(0,str(ROOT/'services/mcp'))
                    import mcp_server
                    result=mcp_server.tool_tts_set_params({k:v for k,v in body.items() if k in ('speed_factor','sample_steps','default_voice','segment_pause_ms')})
                    result['restart_required']=True
                elif action=='reference':
                    import sys
                    sys.path.insert(0,str(ROOT/'services/mcp'))
                    import mcp_server
                    result=mcp_server.tool_tts_set_reference(body)
                    result['restart_required']=True
                else:raise ValueError('未知操作')
                return self._send(200,json.dumps(result,ensure_ascii=False))
            except Exception as exc:return self._send(400,json.dumps({'error':str(exc)},ensure_ascii=False))
    monitor.H=Handler
    from lan_access import LanAccess
    monitor.LAN=LanAccess(ROOT, Handler, TOKEN, getattr(monitor,'prepare_local_gateway',None))
    monitor.LAN.restore()
    def sample():
        global SAMPLE
        import psutil
        while True:
            try:
                SAMPLE=monitor.status();SAMPLE['cpu']=psutil.cpu_percent();SAMPLE['memory']=psutil.virtual_memory().percent
                HISTORY.append({'ts':time.time(),'gpu':(SAMPLE.get('gpu') or {}).get('util_pct'),'cpu':SAMPLE['cpu']})
            except Exception:SAMPLE={}
            time.sleep(2 if time.time()-LAST_SEEN<8 else 10)
    threading.Thread(target=sample,daemon=True).start();threading.Thread(target=worker,daemon=True).start()
