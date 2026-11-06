import React,{useEffect,useRef,useState} from 'react';
import {Check,Copy,Globe,Lock,Monitor,RefreshCw,ShieldCheck} from 'lucide-react';
import './network-settings.css';

type Api=(path:string,body?:unknown)=>Promise<any>;
export function NetworkSettings({api}:{api:Api}){
 const [info,setInfo]=useState<any>(null),[port,setPort]=useState(9890),[phase,setPhase]=useState(''),[message,setMessage]=useState('');
 const lock=useRef(false);
 const load=async(resetPort=true)=>{const data=await api('workbench/network');setInfo(data);if(resetPort)setPort(data.port);return data};
 useEffect(()=>{load().catch(e=>setMessage(e.message))},[]);
 const action=async(label:string,run:()=>Promise<void>)=>{if(lock.current)return;lock.current=true;setPhase(label);setMessage('');try{await run()}catch(e:any){setMessage(e.message)}finally{lock.current=false;setPhase('')}};
 const apply=async(enabled:boolean,nextPort:number)=>{
   await api('workbench/network',{enabled,port:nextPort});
   const state=await load();
   if(enabled&&state.firewall.state!=='allowed'){
     setPhase('等待防火墙授权');setMessage('请在 Windows 管理员提示中允许配置本地子网访问。');
     try{await api('workbench/network-firewall',{});await load()}catch(e:any){setMessage('局域网入口已开启，但防火墙未完成配置。'+e.message);return}
   }
   setMessage(enabled?'局域网访问已开启。其他设备可使用下方地址连接。':'局域网访问已关闭，本机工作台和 API 继续可用。');
 };
 const copy=async(value:string)=>{try{await navigator.clipboard.writeText(value);setMessage('已复制。')}catch{setMessage('请选中地址并手动复制，当前浏览器不支持自动复制。')}};
 const on=!!info?.enabled,busy=!!phase,canManage=!!info?.can_manage,validPort=Number.isInteger(port)&&port>=1024&&port<=65535,changed=!!info&&port!==info.port;
 return <section className="panel settings network-settings" aria-label="网络访问设置" aria-busy={busy}>
  <div className="network-heading"><div><span className="eyebrow">NETWORK ACCESS</span><h3>网络访问</h3><p>这台电脑提供服务，局域网设备按需连接。</p></div><button className="network-refresh" disabled={busy} onClick={()=>action('刷新中',async()=>{await load();setMessage('网络状态已刷新。')})}><RefreshCw size={14}/>刷新</button></div>
  <div className="network-access-cards">
   <div className="network-access-card"><div className="network-card-top"><span className="network-symbol"><Monitor size={19}/></span><div className="network-card-title"><strong>本机访问</strong><small>桌面工作台与本机 API</small></div><span className="network-toggle fixed" aria-label="本机访问始终开启"><i><Check size={12}/></i></span></div><div className="network-card-bottom"><span className="network-state on"><i/>默认开启</span><span>无需额外设置</span></div></div>
   <div className={'network-access-card '+(on?'enabled':'')}><div className="network-card-top"><span className="network-symbol"><Globe size={19}/></span><div className="network-card-title"><strong id="lan-toggle-label">局域网访问</strong><small>工作台页面与语音 API</small></div><button type="button" role="switch" aria-labelledby="lan-toggle-label" aria-checked={on} aria-describedby="lan-switch-hint" className={'network-toggle '+(on?'on':'')} disabled={busy||!canManage} onClick={()=>action(on?'正在关闭':'正在开启',()=>apply(!on,info.port))}><i>{on&&<Check size={12}/>}</i></button></div><div className="network-card-bottom"><span className={'network-state '+(info?.listening?'on':'') }><i/>{phase||(info?(on?(info.listening?'已开启':'监听未就绪'):'已关闭'):'正在读取状态')}</span><span>API Key 验证</span></div></div>
  </div>
  <p id="lan-switch-hint" className="network-hint">局域网开关点击即生效。本机访问始终保留；关闭后停止局域网入口，已配置的防火墙规则保留供下次使用。</p>
  <div className="network-config-row"><label htmlFor="lan-port">局域网端口 <input id="lan-port" type="number" min="1024" max="65535" value={port} disabled={busy||!canManage} onChange={e=>setPort(Number(e.target.value))}/></label><button className="network-port-save" disabled={busy||!canManage||!validPort||!changed} onClick={()=>action('保存端口中',()=>apply(on,port))}>保存端口</button><span>当前端口：{info?.port??'—'}</span></div>
  <div className="network-address-title">局域网连接地址 <small>{info?.addresses?.length?'自动识别本机网卡':'等待网络信息'}</small></div>
  <div className="network-addresses">{info?.addresses?.length?info.addresses.map((item:any)=><div key={item.interface+item.address}><span>{item.interface}</span><code>{'http://'+item.address+':'+info.port}</code><button aria-label={'复制 '+item.address+' 的局域网地址'} onClick={()=>copy('http://'+item.address+':'+info.port)}><Copy size={14}/></button></div>):<p>{info?'没有检测到可用的 IPv4 地址，请检查网络连接。':'正在读取本机 IP…'}</p>}</div>
  <p>浏览器打开上述地址，使用 API Key 登录。API 也使用该地址，例如 /v1/text-to-speech/si/stream。IP 变化后点击刷新。</p>
  <div className="network-security"><span className="network-security-icon"><ShieldCheck size={16}/></span><div><strong>防火墙</strong><small>{info?.firewall?.message||'正在读取状态'} · 仅放行本地子网</small></div><button disabled={busy||!canManage} onClick={()=>action('配置防火墙中',async()=>{setMessage('请允许 Windows 管理员提示。');await api('workbench/network-firewall',{});await load(false);setMessage('防火墙状态已更新。')})}>配置规则</button></div>
  <div className="network-security"><span className="network-security-icon"><Lock size={16}/></span><div><strong>API Key</strong><small>{info?(info.api_key_set?'已配置 · 工作台登录与 API 共用':'尚未配置'):'正在读取状态'}</small></div><button disabled={busy||!canManage} onClick={()=>action('复制中',async()=>{const value=await api('workbench/network-key',{});await copy(value.key)})}><Copy size={13}/>复制密钥</button></div>
  <p className="network-local-address">本机 API：{info?.local_api||'http://127.0.0.1:9881'}</p>
  {!canManage&&info&&<p>网络开关、端口与密钥管理请在服务电脑上操作。</p>}
  {(message||info?.error)&&<p role="status" className="network-message">{message||info.error}</p>}
 </section>
}
