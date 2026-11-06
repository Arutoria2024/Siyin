"""Persistent presentation metadata; never loads models."""
import hashlib,json,re,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def identity(voice,source='synthesis'):
    if source=='import':return {'voice':'','name':'导入音频','model':'本地音频','avatar':None}
    info={'voice':voice,'name':voice or '未知音色','model':'未知模型','avatar':None}
    if voice=='si':
        info.update(name='祀',model='GPT-SoVITS · v5turbo')
        image=ROOT/'ui/public/assets/character.jpg'
        if image.exists():
            digest=hashlib.sha256(image.read_bytes()).hexdigest()+'.jpg'
            folder=ROOT/'out/workbench/identities';folder.mkdir(parents=True,exist_ok=True)
            if not (folder/digest).exists():shutil.copyfile(image,folder/digest)
            info['avatar']='/media/voices/'+digest
    return info
def title_for(text,title='',filename=''):
    if title.strip():return title.strip()[:120],'custom'
    if filename:return Path(filename).stem[:120],'filename'
    text=re.sub(r'\s+',' ',text).strip()
    sentence=next((s.strip() for s in re.split(r'[。！？!?\n]',text) if any(c.isalnum() for c in s)),'')
    if sentence:return sentence[:24]+('…' if len(sentence)>24 else ''),'text'
    return '语音作品 '+time.strftime('%Y%m%d-%H%M%S'),'fallback'
def migrate(c):
    columns={r[1] for r in c.execute('PRAGMA table_info(tasks)')}
    for name in ('identity','source_type','title_source'):
        if name not in columns:c.execute('ALTER TABLE tasks ADD COLUMN '+name+' TEXT')
    for i,voice,text in c.execute('SELECT id,voice,text FROM tasks WHERE identity IS NULL').fetchall():
        source='synthesis' if text else 'import'
        c.execute('UPDATE tasks SET identity=?,source_type=?,title_source=? WHERE id=?',(json.dumps(identity(voice,source),ensure_ascii=False),source,'legacy',i))
