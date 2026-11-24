import random, statistics as st
random.seed(7); N=20000
T=random.triangular
def pct(xs):
    xs=sorted(xs); return [round(xs[int(len(xs)*p)]) for p in (0.1,0.5,0.9)]
def months_ramp(m, final):  # linear ramp over 12 months
    return final*m/12
# ---------- S1: content flywheel (YouTube long + Shorts/Reels + store distribution + sponsorship), 12 months, INR
s1=[];s1_parts={'yt_long':[],'shorts':[],'stores':[],'sponsor':[]}
for _ in range(N):
    titles=T(12,36,24)              # films/yr at 2-3 per month with eav pipeline
    views_per_film_m12=T(2e3,150e3,15e3)  # monthly views per long film once matured (heavy tail)
    rpm_long=T(20,100,45)           # INR per 1000 monetised views (bn/en story, low-mid of education band)
    monetised=T(0.4,0.8,0.6)        # share of views monetised; YPP needs 1k subs + 4k hrs first
    ypp_month=int(T(3,10,6))        # month YPP eligibility reached
    long=0;short=0
    for m in range(1,13):
        live=titles*m/12
        if m>=ypp_month:
            long+=live*views_per_film_m12*(m/12)*monetised*rpm_long/1000
    shorts_views_m=T(0.2e6,8e6,1.5e6)   # monthly Shorts views at maturity, across 2 reels/title
    rpm_s=T(3,12,6)
    for m in range(ypp_month,13): short+=shorts_views_m*(m/12)*rpm_s/1000
    stores=titles*T(5,120,25)*T(80,200,130)*0.52*0.5   # Google Play auto/own-narrated: units*price*52%*half-year avg
    sponsor=T(0,6,2)*T(15e3,60e3,25e3)  # sponsored learning tracks/integrations in year 1
    tot=long+short+stores+sponsor
    s1.append(tot)
    for k,v in zip(s1_parts,(long,short,stores,sponsor)): s1_parts[k].append(v)
# ---------- S2: freemium Pass (B2C) after free-audience build
s2=[];mau_end=[];payers_end=[]
for _ in range(N):
    mau12=T(5e3,120e3,30e3)     # MAU at month 12, mostly fed by S1 traffic
    conv=T(0.01,0.06,0.025)     # free->paid among MAU
    arpu_m=T(70,99,83)          # blend of 99/mo and 999/yr (=83.25/mo)
    churn=T(0.05,0.15,0.09)
    start=int(T(4,8,6))         # paid Pass reactivated (owner approval + merchant qualification)
    payers=0;rev=0
    for m in range(1,13):
        mau=mau12*m/12
        if m>=start:
            target=mau*conv
            payers=payers*(1-churn)+max(0,target-payers*(1-churn))*0.5
            rev+=payers*arpu_m*(1-0.03)   # ~3% gateway; GST excluded (price shown inclusive assumption)
    s2.append(rev);mau_end.append(mau12);payers_end.append(payers)
# ---------- S3: schools / tuition centres / CSR (B2B2C)
s3=[];seats=[]
for _ in range(N):
    pilots=int(T(2,15,6))       # institutions signed in yr1 (founder-led sales, WB + English-medium private)
    students=T(80,600,250)
    price=T(100,400,200)        # INR/student/yr -- NO market data found; assumption
    paid_share=T(0.3,0.9,0.6)   # share of pilots that convert from free pilot to paid
    csr=T(0,3,1)*T(50e3,300e3,100e3)   # CSR/NGO funded licences
    r=pilots*paid_share*students*price*0.5+csr  # half-year average
    s3.append(r);seats.append(pilots*paid_share*students)
fmt=lambda l:'  '.join(f'₹{x:,}' for x in pct(l))
print('P10 / P50 / P90 first-12-month revenue (INR)')
print('S1 content flywheel :',fmt(s1))
for k,v in s1_parts.items(): print('   ',k.ljust(8),fmt(v))
print('S2 freemium Pass    :',fmt(s2),'| payers@m12 P50',pct(payers_end)[1],'MAU P50',pct(mau_end)[1])
print('S3 schools/CSR      :',fmt(s3),'| paid seats P50',pct(seats)[1])
comb=[a+b+c for a,b,c in zip(s1,s2,s3)]
print('Combined            :',fmt(comb))
# month-24 run-rate for S2 using steady state
rr=[]
for _ in range(N):
    mau24=T(20e3,400e3,90e3);conv=T(0.01,0.06,0.025);arpu=T(70,99,83)
    rr.append(mau24*conv*arpu*12*0.97)
print('S2 year-2 annualised run-rate:',fmt(rr))
# sensitivity: correlation of inputs to S1 handled crudely by re-running with views fixed
