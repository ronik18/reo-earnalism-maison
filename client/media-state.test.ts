import assert from "node:assert/strict";
import test from "node:test";
import {approvedStreamURL} from "./media-state";
const now = Date.parse("2026-11-18T12:00:00Z");
const grant = {asset_id:"asset", edition_revision_id:"revision",transport:"stream_signed",content_type:"video/mp4",url:"https://iframe.videodelivery.net/approved-token",expires_at:"2026-11-18T12:01:30Z"};
test("Video accepts only current exact-revision short-lived approved Stream grants", () => {
  assert.equal(approvedStreamURL(grant,"asset","revision",now),grant.url);
  for (const change of [{content_type:"audio/mpeg"},{asset_id:"other"},{edition_revision_id:"other"},{transport:"local_signed"},{expires_at:"invalid"},{expires_at:"2026-11-18T11:59:59Z"},{expires_at:"2026-11-18T12:03:00Z"},{url:"https://iframe.videodelivery.net.attacker.example/token"},{url:"http://iframe.videodelivery.net/token"},{url:"https://user:secret@iframe.videodelivery.net/token"}]) assert.equal(approvedStreamURL({...grant,...change},"asset","revision",now),undefined);
});

import {approvedAudioURL} from "./media-state";
const chapter={asset_id:"audio",sha256:"exact-hash",duration_ms:180000,quality_kbps:48};
const audioGrant={...chapter,edition_revision_id:"revision",transport:"r2_s3_presigned",content_type:"audio/mpeg",url:"https://private-bucket.example/audio.mp3?signature=opaque",expires_at:"2026-11-18T12:01:30Z"};
test("Audio rejects wrong-format, wrong-revision, stale or inconsistent grants", () => {
  assert.equal(approvedAudioURL(audioGrant,chapter,"revision","https://maison.example",now),audioGrant.url);
  for(const change of [{content_type:"video/mp4"},{transport:"stream_signed"},{edition_revision_id:"other"},{asset_id:"other"},{duration_ms:1},{quality_kbps:96},{sha256:"other"},{expires_at:"invalid"},{expires_at:"2026-11-18T11:59:59Z"},{url:"http://private-bucket.example/audio"}]) assert.equal(approvedAudioURL({...audioGrant,...change},chapter,"revision","https://maison.example",now),undefined);
  const local={...audioGrant,transport:"local_signed",url:"http://127.0.0.1:8000/local-object"};
  assert.equal(approvedAudioURL(local,chapter,"revision","http://127.0.0.1:8000",now),local.url);
  assert.equal(approvedAudioURL(local,chapter,"revision","https://maison.example",now),undefined);
});

import {approvedAudioPreviewURL} from "./media-state";
test("Audio samples accept only a physically bounded clip gateway for the exact revision", () => {
  const preview={asset_id:"clip",edition_revision_id:"revision",unit_id:"unit",url:"/api/v1/content/audio-previews/clip?locale=en&territory=IN",sha256:"a".repeat(64),bytes:8000,content_type:"audio/mpeg",duration_ms:6000,quality_kbps:48};
  assert.equal(approvedAudioPreviewURL(preview,"revision","https://maison.example"),"https://maison.example"+preview.url);
  for(const change of [{url:"/api/v1/content/local-assets/full-chapter"},{url:"https://private.r2.cloudflarestorage.com/full-chapter?token=opaque"},{url:"https://other.example/api/v1/content/audio-previews/clip"},{url:"/api/v1/content/audio-previews/another"},{edition_revision_id:"other"},{unit_id:""},{sha256:"invalid"},{bytes:2097153},{bytes:0},{duration_ms:120001},{duration_ms:0},{content_type:"video/mp4"},{quality_kbps:192}]) assert.equal(approvedAudioPreviewURL({...preview,...change},"revision","https://maison.example"),undefined);
});

test("Production video grants stay on the configured Stream customer host", () => {
  const configured="customer-approved.cloudflarestream.com";
  const valid={...grant,url:`https://${configured}/signed-token/iframe`};
  assert.equal(approvedStreamURL(valid,"asset","revision",now,configured),valid.url);
  assert.equal(approvedStreamURL(valid,"asset","revision",now,"customer-other.cloudflarestream.com"),undefined);
  assert.equal(approvedStreamURL(grant,"asset","revision",now,configured),undefined);
  assert.equal(approvedStreamURL(valid,"asset","revision",now,"*.cloudflarestream.com"),undefined);
});

import {approvedFilmURL, shouldRenewFilm, renewExpiredFilm, type FilmGrant} from "./media-state";
const film={asset_id:"film",sha256:"b".repeat(64),duration_ms:5400000};
const filmGrant:FilmGrant={...film,edition_revision_id:"revision",transport:"r2_s3_presigned",content_type:"video/mp4",url:"https://account.r2.cloudflarestorage.com/private/film.mp4?X-Amz-Signature=opaque",expires_at:"2026-11-18T12:01:30Z"};
test("Film accepts only a fresh exact R2 or same-origin local grant", () => {
  assert.equal(approvedFilmURL(filmGrant,film,"revision","https://maison.example",now),filmGrant.url);
  for(const change of [{content_type:"audio/mpeg"},{content_type:"application/vnd.apple.mpegurl"},{transport:"stream_signed"},{edition_revision_id:"other"},{asset_id:"other"},{sha256:"c".repeat(64)},{duration_ms:5399999},{expires_at:"invalid"},{expires_at:"2026-11-18T11:59:59Z"},{expires_at:"2026-11-18T12:02:00.001Z"},{url:"http://account.r2.cloudflarestorage.com/private/film.mp4"},{url:"https://user:secret@account.r2.cloudflarestorage.com/film.mp4"}]) assert.equal(approvedFilmURL({...filmGrant,...change},film,"revision","https://maison.example",now),undefined,JSON.stringify(change));
  assert.equal(approvedFilmURL({...filmGrant,expires_at:"2026-11-18T12:02:00Z"},film,"revision","https://maison.example",now),filmGrant.url);
  const local={...filmGrant,transport:"local_signed",url:"/api/v1/content/local-assets/film?token=opaque"};
  assert.equal(approvedFilmURL(local,film,"revision","http://localhost:8000",now),"http://localhost:8000/api/v1/content/local-assets/film?token=opaque");
  assert.equal(approvedFilmURL(local,film,"revision","https://maison.example",now),undefined);
  assert.equal(approvedFilmURL({...local,url:"http://127.0.0.1:9000/film"},film,"revision","http://localhost:8000",now),undefined);
});
test("Film renewal starts only for an expired grant with no renewal in flight", () => {
  assert.equal(shouldRenewFilm("2026-11-18T11:59:59Z",now,false),true);
  assert.equal(shouldRenewFilm("2026-11-18T12:00:00Z",now,false),true);
  assert.equal(shouldRenewFilm("2026-11-18T11:59:59Z",now,true),false);
  assert.equal(shouldRenewFilm("2026-11-18T12:01:00Z",now,false),false);
  assert.equal(shouldRenewFilm("invalid",now,false),false);
});
test("renews_expired_film_grant_and_resumes", async () => {
  const expired={...filmGrant,expires_at:"2026-11-18T11:59:50Z",url:"https://account.r2.cloudflarestorage.com/private/film.mp4?X-Amz-Signature=first"};
  const fresh={...filmGrant,url:"https://account.r2.cloudflarestorage.com/private/film.mp4?X-Amz-Signature=second"};
  const element={src:expired.url,currentTime:1234.5,paused:false};
  let current:FilmGrant=expired, requests=0, plays=0;
  const renewing={current:false};
  const io={
    grant:()=>current, renewing, now:()=>now,
    request:async()=>{requests++;return fresh;},
    approve:(g:FilmGrant)=>approvedFilmURL(g,film,"revision","https://maison.example",now),
    currentTime:()=>element.currentTime, playing:()=>!element.paused,
    apply:async(url:string,g:FilmGrant,at:number,resume:boolean)=>{current=g;element.src=url;element.currentTime=0;element.currentTime=at;if(resume)plays++;},
  };
  const first=renewExpiredFilm(io);
  assert.equal(await renewExpiredFilm(io),false,"a second error during renewal must not request again");
  assert.equal(await first,true);
  assert.equal(requests,1);
  assert.equal(element.src,fresh.url);
  assert.equal(element.currentTime,1234.5);
  assert.equal(plays,1);
  assert.equal(renewing.current,false);
  assert.equal(await renewExpiredFilm(io),false,"a fresh grant's error is a retry, not a renewal");
  assert.equal(requests,1);
});
test("Film renewal rejects an invalid replacement grant without changing the source", async () => {
  const element={src:"first",currentTime:12};
  const renewing={current:false};
  await assert.rejects(renewExpiredFilm({grant:()=>({...filmGrant,expires_at:"2026-11-18T11:59:00Z"}),renewing,now:()=>now,request:async()=>({...filmGrant,sha256:"c".repeat(64)}),approve:(g:FilmGrant)=>approvedFilmURL(g,film,"revision","https://maison.example",now),currentTime:()=>element.currentTime,playing:()=>true,apply:(url:string)=>{element.src=url;}}),/media_changed/);
  assert.equal(element.src,"first");
  assert.equal(renewing.current,false);
});
