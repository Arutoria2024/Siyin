import React from 'react';
export function ConnectionStatus({status,unavailable,refresh}:{status:any,unavailable:boolean,refresh:()=>unknown}){
 const fresh=!!status.ts&&Date.now()/1000-status.ts<20&&!unavailable;
 const gateway=fresh?status.gateway_reachable??(status.gateway_ok?true:undefined):undefined;
 const api=fresh&&status.gateway_ok&&status.engine_ok;
 const starting=fresh&&status.state==='loading';
 const stateLabel=gateway===undefined?'等待检测':gateway?'已连接':'未连接';
 const apiLabel=!fresh?'等待检测':api?'可合成':starting?'正在准备':'暂不可用';
 return <div className="connection-summary"><div className="connection-cards"><div><span>HTTP 网关</span><strong data-level={gateway===undefined?'pending':gateway?'ok':'error'}><i/>{stateLabel}</strong><small>127.0.0.1:9881</small></div><div><span>语音合成 API</span><strong data-level={!fresh||starting?'pending':api?'ok':'error'}><i/>{apiLabel}</strong><small>{api?`${status.voice} · ${status.sample_rate/1000} kHz`:gateway?'等待引擎就绪后可合成':'请先启动本地服务'}</small></div></div><div className="connection-foot"><span>{fresh?'健康检查更新于 '+new Date(status.ts*1000).toLocaleTimeString('zh-CN',{hour12:false}):'尚未取得最新状态'} · {api?'健康检查通过，实际调用仍需有效密钥':'不会自动发送测试合成'}</span><button onClick={refresh}>刷新状态</button></div></div>
}
