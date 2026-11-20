import test from 'node:test';
import assert from 'node:assert/strict';
import {createSyncPair} from './sync.mjs';

class Video extends EventTarget {
 _time=0;duration=76;readyState=4;paused=true;muted=false;ended=false;
 playCalls=0;seekWrites=0;
 get currentTime(){return this._time;}
 // Seeking is not native completion; the old mock concealed this distinction.
 set currentTime(value){this._time=value;this.ended=false;this.seekWrites++;}
 async play(){this.playCalls++;if(this.ended)this.currentTime=0;this.paused=false;}
 pause(){this.paused=true;}
 finishNaturally(){this._time=this.duration;this.ended=true;this.paused=true;this.dispatchEvent(new Event('ended'));}
}
const settle=async()=>{await Promise.resolve();await Promise.resolve();};

class PendingFirstPlay extends Video {
 pending=null;
 play(){
  this.playCalls++;this.paused=false;
  if(this.playCalls>1)return Promise.resolve();
  return new Promise((resolve,reject)=>{this.pending={resolve,reject};});
 }
 pause(){
  super.pause();if(this.pending){const {reject}=this.pending;this.pending=null;reject(new DOMException('The play request was interrupted by pause.','AbortError'));}
 }
}

test('starts with one soundtrack, corrects ordinary drift and shares pause, seek and replay',async()=>{
 const a=new Video(),b=new Video(),messages=[],p=createSyncPair(a,b,s=>messages.push(s));
 await p.play();assert.ok(messages.includes('Playing together · one soundtrack'));
 assert.equal(a.muted,true);assert.equal(b.muted,false);assert.ok(!a.paused&&!b.paused);
 b.currentTime=12;a.currentTime=11.8;p.tick();assert.equal(a.currentTime,12);
 p.seek(30);assert.equal(a.currentTime,30);assert.equal(b.currentTime,30);
 p.pause();assert.ok(a.paused&&b.paused);
 await p.replay();assert.equal(a.currentTime,0);assert.equal(b.currentTime,0);assert.ok(!a.paused&&!b.paused);
});

test('buffers as a pair and cannot unmute the earlier soundtrack',async()=>{
 const a=new Video(),b=new Video(),p=createSyncPair(a,b);
 await p.play();a.readyState=2;a.dispatchEvent(new Event('waiting'));assert.ok(a.paused&&b.paused);
 a.readyState=4;a.dispatchEvent(new Event('canplay'));await settle();assert.ok(!a.paused&&!b.paused);
 a.muted=false;a.dispatchEvent(new Event('volumechange'));assert.equal(a.muted,true);
});

for(const firstName of ['earlier','latest'])test(`both finish naturally when ${firstName} ends first; timers and canplay cannot restart it`,async()=>{
 const a=new Video(),b=new Video(),messages=[],p=createSyncPair(a,b,s=>messages.push(s));
 a.duration=b.duration=58.366667;await p.play();
 const first=firstName==='earlier'?a:b,last=first===a?b:a;
 last.currentTime=58.350783;first.finishNaturally();
 const firstPlays=first.playCalls,firstSeeks=first.seekWrites,lastSeeks=last.seekWrites;
 assert.equal(last.currentTime,58.350783);assert.equal(last.ended,false);
 assert.equal(last.paused,false);assert.equal(p.playing,true);
 assert.ok(!messages.some(s=>s.startsWith('Finished')));
 p.tick();first.dispatchEvent(new Event('canplay'));await settle();
 assert.equal(first.playCalls,firstPlays);assert.equal(first.seekWrites,firstSeeks);
 assert.equal(last.seekWrites,lastSeeks);assert.equal(first.ended,true);
 // A buffering event near the end must resume only the unfinished clip.
 last.readyState=2;last.dispatchEvent(new Event('waiting'));assert.equal(last.paused,true);
 last.readyState=4;last.dispatchEvent(new Event('canplay'));await settle();
 assert.equal(first.playCalls,firstPlays);assert.equal(first.ended,true);assert.equal(last.paused,false);
 last.finishNaturally();
 assert.equal(a.ended,true);assert.equal(b.ended,true);assert.equal(p.playing,false);
 assert.equal(messages.filter(s=>s.startsWith('Finished')).length,1);
 p.tick();a.dispatchEvent(new Event('canplay'));b.dispatchEvent(new Event('canplay'));await settle();
 assert.equal(a.ended,true);assert.equal(b.ended,true);assert.ok(a.paused&&b.paused);
 assert.equal(first.seekWrites,firstSeeks);assert.equal(last.seekWrites,lastSeeks);
 await p.play();assert.equal(a.currentTime,0);assert.equal(b.currentTime,0);
 assert.equal(a.ended,false);assert.equal(b.ended,false);assert.ok(!a.paused&&!b.paused);
 assert.equal(a.muted,true);assert.equal(b.muted,false);
});

test('manual pause near completion preserves native-ended state; explicit seek can reopen it',async()=>{
 const a=new Video(),b=new Video(),messages=[],p=createSyncPair(a,b,s=>messages.push(s));await p.play();
 b.currentTime=75.98;a.finishNaturally();p.pause();
 assert.equal(a.ended,true);assert.equal(a.currentTime,76);assert.equal(b.currentTime,75.98);
 await p.play();assert.equal(a.ended,true);assert.equal(b.paused,false);
 p.seek(20);p.tick();await settle();
 assert.equal(a.ended,false);assert.equal(b.ended,false);assert.equal(a.currentTime,20);assert.equal(b.currentTime,20);
 assert.ok(!a.paused&&!b.paused);
 a.finishNaturally();b.finishNaturally();assert.ok(messages.at(-1).startsWith('Finished'));
 p.seek(0);assert.equal(a.currentTime,0);assert.equal(b.currentTime,0);
 assert.ok(!messages.at(-1).startsWith('Finished'));assert.equal(p.playing,false);
});

test('a buffering pause during pending play retains intent even when canplay races its rejection',async()=>{
 const a=new PendingFirstPlay(),b=new PendingFirstPlay(),messages=[],p=createSyncPair(a,b,s=>messages.push(s));
 const initial=p.play();assert.equal(a.playCalls,1);assert.equal(b.playCalls,1);
 a.readyState=2;a.dispatchEvent(new Event('waiting'));assert.ok(a.paused&&b.paused);
 // Both canplay events arrive while Promise.all is still unwinding. The next
 // normal tick must recover without another user click or a second soundtrack.
 a.readyState=4;a.dispatchEvent(new Event('canplay'));b.dispatchEvent(new Event('canplay'));
 await initial;assert.equal(p.playing,true);assert.ok(messages.at(-1).startsWith('Buffering'));
 assert.ok(!messages.includes('Press Play to start both videos.'));
 p.tick();await settle();assert.equal(a.playCalls,2);assert.equal(b.playCalls,2);
 assert.ok(!a.paused&&!b.paused);assert.equal(a.muted,true);assert.equal(b.muted,false);
 assert.equal(messages.at(-1),'Playing together · one soundtrack');
});

test('manual pause during pending play remains paused after AbortError and later ready events',async()=>{
 const a=new PendingFirstPlay(),b=new PendingFirstPlay(),messages=[],p=createSyncPair(a,b,s=>messages.push(s));
 const initial=p.play();p.pause();await initial;
 a.dispatchEvent(new Event('canplay'));b.dispatchEvent(new Event('canplay'));p.tick();await settle();
 assert.equal(p.playing,false);assert.ok(a.paused&&b.paused);
 assert.equal(a.playCalls,1);assert.equal(b.playCalls,1);assert.equal(messages.at(-1),'Paused');
});

test('a genuine browser play permission rejection still requests an explicit Play click',async()=>{
 class RestrictedVideo extends Video {async play(){this.playCalls++;throw new DOMException('User interaction required','NotAllowedError');}}
 const a=new RestrictedVideo(),b=new Video(),messages=[],p=createSyncPair(a,b,s=>messages.push(s));
 await p.play();assert.equal(p.playing,false);assert.ok(a.paused&&b.paused);
 assert.equal(messages.at(-1),'Press Play to start both videos.');
 const calls=a.playCalls;a.dispatchEvent(new Event('canplay'));p.tick();await settle();assert.equal(a.playCalls,calls);
});
