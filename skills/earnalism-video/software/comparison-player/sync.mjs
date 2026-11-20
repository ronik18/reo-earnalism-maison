export function createSyncPair(earlier,latest,onStatus=()=>{}) {
 let wanted=false,starting=false,closed=false,completed=false;
 earlier.muted=true;latest.muted=false;
 const pause=()=>{wanted=false;earlier.pause();latest.pause();if(!earlier.ended&&!latest.ended&&Number.isFinite(latest.currentTime)&&Math.abs(earlier.currentTime-latest.currentTime)>.001)earlier.currentTime=latest.currentTime;onStatus('Paused');};
 async function start(){
  if(starting||closed||!wanted)return;
  const active=[earlier,latest].filter(v=>!v.ended);
  if(!active.length){finish();return;}
  if(active.some(v=>v.readyState<3)){onStatus('Buffering both videos…');return;}
  starting=true;earlier.muted=true;
  if(active.length===2&&Math.abs(earlier.currentTime-latest.currentTime)>.015)earlier.currentTime=latest.currentTime;
  try{await Promise.all(active.map(v=>v.play()));if(!wanted){earlier.pause();latest.pause();}else if(earlier.ended||latest.ended)finish();else onStatus('Playing together · one soundtrack');}
  catch(error){
   if(!wanted){earlier.pause();latest.pause();onStatus('Paused');}
   // Pair buffering intentionally pauses pending play() requests. Keep the
   // user's playback intent so canplay/tick resumes after that AbortError.
   else if(error?.name==='AbortError'){earlier.pause();latest.pause();onStatus('Buffering both videos…');}
   else{pause();onStatus('Press Play to start both videos.');}
  }finally{starting=false;}
 }
 const play=async()=>{if(completed||(earlier.ended&&latest.ended))seek(0);wanted=true;await start();};
 function seek(t){completed=false;const duration=Math.min(earlier.duration||Infinity,latest.duration||Infinity);t=Math.max(0,Math.min(t,duration));earlier.currentTime=t;latest.currentTime=t;onStatus(wanted?'Playing together · one soundtrack':'Ready · press Play');}
 function finish(){if(completed||closed)return;if(!earlier.ended||!latest.ended){onStatus('Finishing both videos…');return;}completed=true;wanted=false;onStatus('Finished · Replay starts both again');}
 function buffer(){if(!wanted)return;earlier.pause();latest.pause();onStatus('Buffering both videos…');}
 function tick(){if(wanted&&!starting){if(earlier.ended||latest.ended){finish();if(wanted&&[earlier,latest].some(v=>!v.ended&&v.paused))start();}else if(earlier.readyState>=3&&latest.readyState>=3){if(earlier.paused||latest.paused)start();else if(Math.abs(earlier.currentTime-latest.currentTime)>.045)earlier.currentTime=latest.currentTime;}}return Math.abs(earlier.currentTime-latest.currentTime);}
 earlier.addEventListener('volumechange',()=>{if(!earlier.muted)earlier.muted=true;});
 for(const v of [earlier,latest]){v.addEventListener('waiting',buffer);v.addEventListener('canplay',()=>{if(wanted)start();});v.addEventListener('ended',finish);v.addEventListener('error',()=>{pause();onStatus('Video could not load. Reload this private page.');});}
 return {play,pause,seek,tick,replay:async()=>{seek(0);await play();},get playing(){return wanted;},close:()=>{pause();closed=true;}};
}
