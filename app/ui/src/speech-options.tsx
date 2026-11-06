import React from 'react';
export type SpeechOptions={text_lang:string};
export const defaultSpeechOptions:SpeechOptions={text_lang:'zh'};
export function SpeechSettings({value,onChange}:{value:SpeechOptions,onChange:(v:SpeechOptions)=>void}){
 return <section className="panel speech-options"><label htmlFor="speech-language">文本语言</label><select id="speech-language" value={value.text_lang} onChange={e=>onChange({...value,text_lang:e.target.value})}><option value="zh">中文</option><option value="en">English · 英文</option><option value="auto">中英混合 · 自动识别</option></select></section>
}
