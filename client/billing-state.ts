export interface FinancialPDFGrant {url:string;expires_at:string;sha256:string;bytes:number;content_type:string;revision?:number;}
/** A retained financial PDF uses a fresh private grant, never an account/auth URL. */
export function approvedFinancialPDFURL(grant:FinancialPDFGrant,localPath:string,origin:string,now=Date.now()):string|undefined {
  try {
    const url=new URL(grant.url,origin),page=new URL(origin),expiry=Date.parse(grant.expires_at);
    if(grant.content_type!=="application/pdf"||!Number.isSafeInteger(grant.bytes)||grant.bytes<5||!/^[a-f0-9]{64}$/.test(grant.sha256)||!Number.isFinite(expiry)||expiry<=now||expiry>now+125000||url.username||url.password||url.hash)return;
    if(url.origin===page.origin)return url.pathname===localPath?url.href:undefined;
    return url.protocol==="https:"?url.href:undefined;
  } catch {return undefined;}
}
