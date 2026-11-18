# Maison CDN activation and verification

18 November 2026. This is a minimal qualification of the approved Maison app/assets hostnames, not a book publication or legacy cutover. Provider changes are performed only by the Integration Lane. The Selfish Giant stays draft. Existing apex/www/api records remain DNS-only and unchanged.

## Request transform: exact Maison app host

Match expression:

```text
http.host eq "maison.theearnalism.com"
```

In HTTP Request Header Modification, **Set static** `x-maison-origin` to the existing `ORIGIN_SHARED_SECRET` privately; **Set dynamic** `x-maison-country` to `ip.src.country`. Set overwrites attacker-supplied values; do not Add or log the secret. Preserve Cloudflare's real `CF-Connecting-IP`. Do not apply the origin secret to the assets host or legacy hosts. Use HTTPS to Render with Full (strict) TLS and its verified CNAME destination `reo-earnalism-maison-qa.onrender.com`. Keep the actual Render origin-protection behavior and health exception unchanged.

## Smallest initial app Cache Rules

Use the expressions below in the Free zone editor's validation before deployment. Dynamic field comparisons/concat must be accepted by the actual zone; source review is not provider acceptance. No regex, custom cache key or Worker is needed if these supported expressions validate. Keep the default full URL key, including query string. Do not normalize away parameters. Use **Eligible for cache**, respecting origin cache-control. Do not set an Edge TTL that overrides origin/private headers; do not strip Set-Cookie or Vary.

Rule 1, bypass all app requests by default:

```text
http.host eq "maison.theearnalism.com"
```

The actual Free-zone editor rejected two `concat()` calls in a single expression (maximum one). Use two otherwise identical public admission rules, one per locale, after the default bypass; three Cache Rules total. This preserves the same predicate and architecture.

Rule 2, later in order, admit only canonical EN home requests:

```text
(http.host eq "maison.theearnalism.com"
 and http.request.uri.path eq "/api/v1/home"
 and (http.request.method eq "PURGE" or (http.request.method in {"GET" "HEAD"}
 and http.cookie eq ""
 and not has_key(http.request.headers, "cookie")
 and not has_key(http.request.headers, "authorization")
 and ip.src.country in {"AM" "AZ" "BD" "BH" "BN" "BR" "BT" "CA" "CY" "DE" "DK" "FR" "GB" "GE" "HK" "ID" "IL" "IN" "IQ" "JO" "JP" "KH" "KR" "KZ" "LA" "LB" "LK" "MM" "MO" "MV" "MY" "NL" "NP" "NZ" "OM" "PH" "PK" "QA" "RU" "SA" "SG" "TH" "TR" "TW" "US" "UZ" "YE"}
 and http.request.uri.query eq concat("locale=en&territory=", ip.src.country))))
```

Rule 3, later in order, admit only canonical BN home requests:

```text
(http.host eq "maison.theearnalism.com"
 and http.request.uri.path eq "/api/v1/home"
 and (http.request.method eq "PURGE" or (http.request.method in {"GET" "HEAD"}
 and http.cookie eq ""
 and not has_key(http.request.headers, "cookie")
 and not has_key(http.request.headers, "authorization")
 and ip.src.country in {"AM" "AZ" "BD" "BH" "BN" "BR" "BT" "CA" "CY" "DE" "DK" "FR" "GB" "GE" "HK" "ID" "IL" "IN" "IQ" "JO" "JP" "KH" "KR" "KZ" "LA" "LB" "LK" "MM" "MO" "MV" "MY" "NL" "NP" "NZ" "OM" "PH" "PK" "QA" "RU" "SA" "SG" "TH" "TR" "TW" "US" "UZ" "YE"}
 and http.request.uri.query eq concat("locale=bn&territory=", ip.src.country))))
```

Rule order is material: rule 1 bypasses everything, then rules 2/3 override eligibility only for their exact public admission conditions. No subsequent broad eligible rule may override them. Export/read back the effective order.

The actual provider accepted `has_key(http.request.headers, "cookie")` and the authorization equivalent. Header-name array comparisons previously let Cookie requests hit a warmed public entry; that failed approach is replaced. Map presence catches mixed-case and empty headers; `http.cookie eq ""` is retained as an additional condition. The PURGE method branch is required for provider exact-file cache eviction matching; external HTTP PURGE was separately tested and rejected400 without cached catalog retrieval. Country/query binding happens **before cache lookup**: an origin-only check cannot protect an already warmed different-country URL. Duplicate, reordered and unknown query parameters fail this exact comparison. Excluded countries receive no admission. The live application remains responsible for status200, rights deadlines, no-store/private, response cookies and representation checks. Its current admission code captures GET only; HEAD may remain uncacheable safely.

This narrow route is sufficient to qualify CDN behavior without broadening the architecture. Other catalog/SSR routes remain uncached until separately admitted consistently with `operations/providers.py:PUBLIC_PATH`; do not claim the full route set qualified.

## Public assets

Attach `assets-maison.theearnalism.com` using the official existing public R2 bucket custom-domain workflow. Never expose the private bucket or use its S3 endpoint/r2.dev as a public CDN target. Existing immutable release is `19e40009002433e09db905c865b34d85da4c8d457b5630431e135dfc71b40142`. Public GET/HEAD font/JS requests need suitable MIME and CORS (the configured exact allowed app origins, no credentials); metadata already specifies one-year immutable caching. Do not apply app-origin secret to R2. First test provider defaults; add only a host/path-limited static eligibility rule if needed, respecting object headers. Do not introduce paid cache features.

## Read-only, secret-free HTTP probe

Use an ordinary browser User-Agent: the actual public asset qualification returned Cloudflare error1010 to the default Python urllib agent; browser-style requests passed without disabling security. Run with the probe's actual country, established through the trusted edge/origin behavior, not a caller-supplied country header. The script sends no origin secret and performs no SMTP, account or publication mutation. Cookie and Authorization probes use inert qualification values. Set `ASSET_URL` to one real uploaded manifest path, never a guessed filename. Save evidence outside ignored credential files. Unknown/no-store responses should not be relabeled HIT failures for an unsupported country.

```sh
export QUALIFICATION_COUNTRY=IN
export ASSET_URL='https://assets-maison.theearnalism.com/static/19e40009002433e09db905c865b34d85da4c8d457b5630431e135dfc71b40142/REPLACE_WITH_REAL_MANIFEST_PATH'
python3 - <<'PY'
import hashlib,json,os,time,urllib.request,urllib.error,ssl
from pathlib import Path
country=os.environ['QUALIFICATION_COUNTRY']
assert len(country)==2 and country.isalpha() and country.isupper()
base='https://maison.theearnalism.com'
canonical=f'{base}/api/v1/home?locale=en&territory={country}'
ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
checks=[]
def probe(name,url,headers=None):
    req=urllib.request.Request(url,headers={'User-Agent':ua,**(headers or {})})
    try:r=urllib.request.urlopen(req,timeout=30,context=ssl.create_default_context())
    except urllib.error.HTTPError as e:r=e
    body=r.read();h=r.headers
    keep=['CF-Cache-Status','CF-Ray','Age','Cache-Control','CDN-Cache-Control',
          'Cloudflare-CDN-Cache-Control','Content-Type','Access-Control-Allow-Origin',
          'ETag','Vary','Strict-Transport-Security','X-Content-Type-Options']
    row={'name':name,'url':url,'status':r.status,'headers':{k:h.get(k) for k in keep},
         'set_cookie_present':bool(h.get('Set-Cookie')),'body_sha256':hashlib.sha256(body).hexdigest(),
         'bytes':len(body)}
    checks.append(row);print(name,r.status,h.get('CF-Cache-Status'))
probe('catalog_en_first',canonical);time.sleep(1);probe('catalog_en_repeat',canonical)
probe('catalog_bn',f'{base}/api/v1/home?locale=bn&territory={country}')
time.sleep(1);probe('catalog_bn_repeat',f'{base}/api/v1/home?locale=bn&territory={country}')
probe('cookie_bypass',canonical,{'Cookie':'qualification=1'})
probe('authorization_bypass',canonical,{'Authorization':'Bearer invalid-qualification'})
probe('unknown_query',canonical+'&unexpected=1')
probe('duplicate_query',canonical+'&territory='+country)
other='US' if country!='US' else 'IN'
probe('mismatched_country',f'{base}/api/v1/home?locale=en&territory={other}')
probe('private_session',base+'/api/v1/session')
probe('draft_reader',base+'/en/read/55a3f5e3-f713-40b2-a873-942cd97bb1b7/')
asset=os.environ.get('ASSET_URL','')
if asset and 'REPLACE_' not in asset:
    probe('asset_first',asset,{'Origin':base});time.sleep(1)
    probe('asset_repeat',asset,{'Origin':base})
Path('docs/evidence/cdn-activation-http.json').write_text(json.dumps({
    'country_context':country,'country_not_established_by_this_script':True,
    'checks':checks,'book_publication_changed':False,'dns_changed_by_script':False},indent=2)+'\n')
PY
```

Review rather than blindly assert: same probe/POP should show initial MISS (or existing HIT) then HIT before the 30-second catalog TTL; a cold MISS can be established by exact purge. Capture country/POP separately, use real regional probes for country isolation, and never spoof country headers as proof. Cookie/Authorization/private/errors/malformed queries must not be shared HITs. Expect private draft404 and no manuscript. Different locale representations must have their own URL/cache entry; body hashes may match if all localized content happens to be identical, so assess content as well as hash.

## Exact-URL purge acceptance

Use the existing application exact-URL adapter with its separately approved zone Cache Purge token, fixed zone and canonical emitted URL. Do not put a bearer token on a command line or in this document. If a credential still needs creation, obtain its required separate approval. Capture only sanitized acknowledgement, timestamp and URL; never token/header values. Purge the synthetic/anonymous home URL, then immediately GET the same URL from the same probe and record MISS and fresh body, followed by repeat HIT. No purge-everything and no publication mutation is required.

Cloudflare documents that request method conditions can affect single-file purge matching; country-dependent eligibility also requires actual readback qualification. An API success is not eviction proof. If purge does not evict the observed entry, record failure, preserve the source design, and keep catalog shared caching disabled until its exact-key rule/purge pairing is corrected. Do not silently switch to paid tags/custom keys or claim global recall. The app adapter accepts only the app host; separate asset-host exact purge remains an independent qualification item.

References: [Transform Rules availability](https://developers.cloudflare.com/rules/transform/), [dynamic comparison operators](https://developers.cloudflare.com/ruleset-engine/rules-language/operators/), [cache-rule settings and purge limitation](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/), [origin cache-control behavior](https://developers.cloudflare.com/cache/concepts/cache-control/).

## Observed corrected-rule acceptance

On deployed `b588d4c6176acd9e74477cae9ed2ba5928060e12`, EN/BN revalidated then HIT; Cookie/Authorization title-case, mixed-case and empty values all DYNAMIC; draft404; malformed queries/private endpoints DYNAMIC; mismatched territory403; HEAD public200/HIT; PUT403 and external PURGE400. See `docs/evidence/cdn-activation-http.json`, which preserves earlier failed attempts as resolved history. Purge API acknowledgement/readback is owned and recorded separately by the Integration Lane.
