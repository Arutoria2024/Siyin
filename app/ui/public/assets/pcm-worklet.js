class PCMPlayer extends AudioWorkletProcessor {
 constructor(){super();this.queue=[];this.offset=0;this.frames=0;this.started=false;this.ended=false;this.port.onmessage=e=>{if(e.data.end){this.ended=true;this.started=true}else{this.queue.push(e.data);this.frames+=e.data.length;if(this.frames>=sampleRate*.5)this.started=true}}}
 process(_,outputs){const out=outputs[0][0];if(this.started){let used=0;for(let i=0;i<out.length;i++){if(!this.queue.length){if(!this.ended)this.started=false;break}out[i]=this.queue[0][this.offset++];this.frames--;used++;if(this.offset===this.queue[0].length){this.queue.shift();this.offset=0}}this.port.postMessage({used})}return true}
}registerProcessor('pcm-player',PCMPlayer);
