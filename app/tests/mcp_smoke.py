import sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'services/mcp'),str(root/'services')]
import mcp_server as m
config=m.load_config();voice=config['default_voice'];v=config['voices'][voice]
calls=[('tts_status',{}),('tts_list_voices',{}),('tts_speak',{'text':'你好。'}),('tts_set_params',{'speed_factor':v['speed_factor'],'sample_steps':v['sample_steps'],'segment_pause_ms':config['audio']['segment_pause_ms']}),('tts_set_reference',{'voice':voice,'ref_audio_path':v['ref_audio_path'],'prompt_text':v['prompt_text']}),('tts_switch_voice',{'name':voice}),('tts_warmup',{})]
assert len(m.TOOLS)==7
for index,(name,args) in enumerate(calls):
    result=m.handle_request({'jsonrpc':'2.0','id':index+1,'method':'tools/call','params':{'name':name,'arguments':args}})
    assert not result.get('error'),name
    assert not result['result'].get('isError'),result
    print(name,'OK',flush=True)
