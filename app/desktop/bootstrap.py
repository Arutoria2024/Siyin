"""Resolve distributable paths and create a private per-install gateway token."""
import json,os,secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def prepare(root=ROOT):
    root=Path(root).resolve();config=root/'services/config.json'
    cfg=json.loads(config.read_text(encoding='utf-8'));previous=cfg.get('_app_root')
    def walk(value):
        if isinstance(value,dict):return {k:walk(v) for k,v in value.items()}
        if isinstance(value,list):return [walk(v) for v in value]
        if isinstance(value,str):
            if value.startswith('@APP_ROOT@'):return str(root)+value[len('@APP_ROOT@'):].replace('/',os.sep)
            if previous and previous!=str(root):
                normalized=value.replace('\\','/')
                prefix=previous.replace('\\','/').rstrip('/')+'/'
                if normalized.startswith(prefix):return str(root/normalized[len(prefix):])
        return value
    cfg=walk(cfg);cfg['_app_root']=str(root)
    # Keep internal API local; the authenticated optional LAN entry handles sharing.
    cfg.setdefault('gateway', {})['host']='127.0.0.1'
    cfg.setdefault('network', {'lan_enabled':False, 'lan_port':9890})
    if not cfg.get('gateway',{}).get('token'):cfg.setdefault('gateway',{})['token']=secrets.token_urlsafe(32)
    def save(path,value):
        updated=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
        if path.read_text(encoding='utf-8')!=updated:
            temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(updated,encoding='utf-8');os.replace(temp,path)
    save(config,cfg)
    for path in (root/'models/voices').glob('*/manifest.json'):save(path,walk(json.loads(path.read_text(encoding='utf-8'))))
    return cfg
if __name__=='__main__':prepare()
