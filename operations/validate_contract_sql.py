"""Execute the full handoff SQL in a new, local-only PostgreSQL audit database.
This is separate from the app ORM schema; it never targets legacy/production DBs.
"""
import io
import json
import re
import sys
import uuid
from pathlib import Path
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]

def main():
    cfg = json.loads((ROOT / '.local/database.json').read_text())
    if cfg['HOST'] not in {'127.0.0.1', 'localhost'} or int(cfg['PORT']) != 55432:
        raise SystemExit('Only the isolated local PostgreSQL container is allowed')
    name = 'maison_contract_' + uuid.uuid4().hex[:12]
    connargs = {k.lower(): v for k, v in cfg.items() if k in {'NAME','USER','PASSWORD','HOST','PORT'}}
    connargs['dbname'] = connargs.pop('name')
    with psycopg.connect(**connargs, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    from django.conf import settings
    settings.configure(INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions'],
                       DATABASES={'default': {'ENGINE':'django.db.backends.postgresql', **cfg, 'NAME':name}},
                       SECRET_KEY='local-contract-audit-only', USE_TZ=True)
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, stdout=io.StringIO(), verbosity=0)
    connargs['dbname'] = name
    checks = []
    with psycopg.connect(**connargs, autocommit=True) as conn:
        conn.execute((ROOT/'contracts/database.sql').read_text())
        tables = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'maison_%'").fetchone()[0]
        checks.append({'check':'full_handoff_sql_executes_after_real_auth_session_migrations','pass':tables==54,'tables':tables})
        def reject(label, statement, params):
            try:
                with conn.transaction():
                    conn.execute(statement,params)
            except psycopg.errors.CheckViolation:
                checks.append({'check':label,'pass':True});return
            raise AssertionError(label+' unexpectedly accepted')
        uid=conn.execute("INSERT INTO auth_user(password,last_login,is_superuser,username,first_name,last_name,email,is_staff,is_active,date_joined) VALUES ('!',NULL,false,'sql-pilot','','','sql@example.test',false,true,now()) RETURNING id").fetchone()[0]
        member,work,edition,revision,offer,order,payment,refund = [uuid.uuid4() for _ in range(8)]
        conn.execute('INSERT INTO maison_member_profile(id,user_id) VALUES(%s,%s)',(member,uid))
        conn.execute("INSERT INTO maison_work(id,slug,kind,house,creator_display) VALUES(%s,'local-sql-fixture','book','golpo','Original local test')",(work,))
        conn.execute("INSERT INTO maison_edition(id,work_id,locale,edition_number) VALUES(%s,%s,'en',1)",(edition,work))
        conn.execute("INSERT INTO maison_edition_revision(id,edition_id,revision_number,revision_sha256) VALUES(%s,%s,1,%s)",(revision,edition,'a'*64))
        policy=conn.execute('SELECT access_policy FROM maison_edition_revision WHERE id=%s',(revision,)).fetchone()[0]
        checks.append({'check':'new_revision_access_defaults_deny','pass':set(policy.values())=={'deny'}})
        reject('access_policy_rejects_json_null',"UPDATE maison_edition_revision SET access_policy='{"+'"reader":null,"audio":"deny","video":"deny"'+"}' WHERE id=%s",(revision,))
        reject('access_policy_rejects_missing_format',"UPDATE maison_edition_revision SET access_policy='{}' WHERE id=%s",(revision,))
        for table,key in [('maison_edition',edition),('maison_edition_revision',revision)]:
            reject(table+'_version_positive',sql.SQL('UPDATE {} SET version=0 WHERE id=%s').format(sql.Identifier(table)),(key,))
        conn.execute("INSERT INTO maison_offer(id,code,version,kind,label_en,label_bn,currency,price_minor,tax_inclusive,scope,formats,duration_seconds,available_from,terms_sha256) VALUES(%s,'local-test',1,'fixed_pass','Local test','স্থানীয় পরীক্ষা','INR',1000,true,'all',ARRAY['reader'],86400,now(),%s)",(offer,'b'*64))
        conn.execute("INSERT INTO maison_order(id,member_id,offer_id,idempotency_key,request_sha256,status,currency,price_minor,tax_minor,total_minor,offer_snapshot,billing_country,expires_at) VALUES(%s,%s,%s,%s,%s,'pending','INR',1000,0,1000,'{}','IN',now()+interval '1 hour')",(order,member,offer,uuid.uuid4(),'c'*64))
        conn.execute("INSERT INTO maison_payment(id,order_id,provider_payment_id,status,currency,amount_minor,captured_at) VALUES(%s,%s,'local-only-capture','captured','INR',1000,now())",(payment,order))
        conn.execute("INSERT INTO maison_refund(id,payment_id,idempotency_key,amount_minor,currency,status,reason_code) VALUES(%s,%s,%s,800,'INR','requested','local_test')",(refund,payment,uuid.uuid4()))
        conn.execute("UPDATE maison_refund SET amount_minor=400,status='approved' WHERE id=%s",(refund,))
        checks.append({'check':'partial_refund_approval_can_reduce_once','pass':conn.execute('SELECT amount_minor FROM maison_refund WHERE id=%s',(refund,)).fetchone()[0]==400})
        reject('approved_refund_amount_frozen','UPDATE maison_refund SET amount_minor=300 WHERE id=%s',(refund,))
        reject('refund_reservations_cannot_exceed_capture',"INSERT INTO maison_refund(id,payment_id,idempotency_key,amount_minor,currency,status,reason_code) VALUES(%s,%s,%s,700,'INR','approved','local_test')",(uuid.uuid4(),payment,uuid.uuid4()))
        small=uuid.uuid4()
        conn.execute("INSERT INTO maison_refund(id,payment_id,idempotency_key,amount_minor,currency,status,reason_code) VALUES(%s,%s,%s,100,'INR','requested','local_test')",(small,payment,uuid.uuid4()))
        reject('approval_cannot_increase_proposal',"UPDATE maison_refund SET status='approved',amount_minor=200 WHERE id=%s",(small,))
        checks.append({'check':'device_asset_order_refund_versions_persisted','pass':all(conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_name=%s AND column_name='version'",(t,)).fetchone()[0]==1 for t in ['maison_device','maison_asset','maison_order','maison_refund'])})
    report={'scope':'isolated local raw contract database, distinct from app ORM migrations','database':name,'postgres_major':17,'paid_infrastructure':False,'checks':checks,'pass':all(c['pass'] for c in checks)}
    (ROOT/'docs/evidence/contract-postgresql.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['pass'] else 1

if __name__ == '__main__': sys.exit(main())
