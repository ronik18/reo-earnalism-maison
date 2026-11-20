// Shared, read-only Earnalism brand and destination reservations.
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {dirname,join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=join(dirname(fileURLToPath(import.meta.url)),'..','src');
const pins={'branding.mjs':'fda2f90d555e60c6111a1c1de782ca91c0cc347f3903750e0dd7189707178314',
 'social-safe-area.mjs':'e02f86e16898a1907718f127459cc90f0e0b2f3bea88a5eb4bfc40d7b78e590c'};
for(const [name,expected] of Object.entries(pins))
 if(createHash('sha256').update(readFileSync(join(root,name))).digest('hex')!==expected)
  throw Error('Review changed shared module before rendering: '+name);
const {watermarkLayout}=await import(pathToFileURL(join(root,'branding.mjs')));
const {reviewProfileForFrame,safeContentRect,portraitReviewProfile,landscapeReviewProfile,assertUiClear}=await import(pathToFileURL(join(root,'social-safe-area.mjs')));
let raw='';for await(const part of process.stdin)raw+=part;
const frames=JSON.parse(raw),out={};
for(const [name,{width,height,occupiedRects=[]}] of Object.entries(frames)){
 const portrait=name==='portrait';
 const profile=reviewProfileForFrame(width,height,portrait?portraitReviewProfile:landscapeReviewProfile);
 for(const [i,rect] of occupiedRects.entries()) assertUiClear('rebuilt tides '+i,rect,profile);
 const brand=watermarkLayout(width,height,{occupiedRects});
 out[name]={safe:safeContentRect(profile),profile,brand,sharedPins:pins};
}
process.stdout.write(JSON.stringify(out));
