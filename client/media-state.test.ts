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
