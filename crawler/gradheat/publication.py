"""MySQL is authoritative. Redis and local JSON are replaceable mirrors."""
import hashlib,json,uuid
from pathlib import Path
from .material_store import encode
from .redis_vm import connect_redis
from .publication_bytes import store_publication_bytes

CACHE_TTL=26*60*60

def mirror(root,version,payload):
    folder=root/'.research/admissions-data';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(version+'.json')
    text=encode(payload)
    if hashlib.sha256(text.encode()).hexdigest()!=version:raise ValueError('Publication hash mismatch')
    if not path.exists():path.write_text(text,encoding='utf-8')
    pointer=folder/'latest.json';temp=folder/('latest-'+uuid.uuid4().hex+'.tmp')
    temp.write_text(encode({'version_id':version,'path':str(path)}),encoding='utf-8');temp.replace(pointer)


def publish(con,root,payload,internal):
    internal=dict(internal)
    github=root/'.research/github-sources'
    if (github/'latest.json').exists():
        snapshots=json.loads((github/'latest.json').read_text(encoding='utf-8'))['repositories']
        internal['repository_snapshots']=[{k:s[k] for k in ('repo','commit','sha256')} for s in snapshots]
    if (github/'candidates.json').exists():
        raw=(github/'candidates.json').read_bytes()
        internal['external_candidate_file_sha256']=hashlib.sha256(raw).hexdigest()
        internal['external_candidate_ids']=[x['id'] for x in json.loads(raw)]
    builder=root/'workbench/gradheat_workbench/admissions.py'
    if builder.exists():internal['public_builder_sha256']=hashlib.sha256(builder.read_bytes()).hexdigest()
    text=encode(payload);version=hashlib.sha256(text.encode()).hexdigest()
    try:
        with con.cursor() as cur:
            cur.execute('INSERT IGNORE INTO admissions_publication(version_id,data_as_of,payload_json,internal_manifest) VALUES(%s,%s,%s,%s)',(version,payload['data_as_of'],text,encode(internal)))
            store_publication_bytes(cur,version,payload)
            cur.execute('INSERT INTO admissions_head(name,version_id) VALUES(%s,%s) ON DUPLICATE KEY UPDATE version_id=VALUES(version_id)',('current',version))
        con.commit()
        with con.cursor() as cur:
            cur.execute('SELECT payload_json FROM admissions_publication WHERE version_id=%s',(version,));stored=json.loads(cur.fetchone()[0])
        if encode(stored)!=text:raise ValueError('MySQL publication readback mismatch')
        con.commit()
    except Exception:con.rollback();raise
    mirror(root,version,stored)
    cache='unavailable'
    try:
        with connect_redis(root/'.research/admissions-data') as client:
            client.set('gradheat:admissions:'+version,text,ex=CACHE_TTL)
            cache='verified' if client.get('gradheat:admissions:'+version)==text and client.ttl('gradheat:admissions:'+version)>0 else 'readback-failed'
    except Exception as error:cache=type(error).__name__
    return dict(version_id=version,cache_state=cache,cache_ttl=CACHE_TTL)


def load(con,root):
    with con.cursor() as cur:
        cur.execute("SELECT version_id FROM admissions_head WHERE name='current'")
        head=cur.fetchone()
        if not head:raise LookupError('No admissions publication')
        version=head[0]
    con.commit()
    cached=None
    try:
        with connect_redis(root/'.research/admissions-data') as client:cached=client.get('gradheat:admissions:'+version)
    except Exception:pass
    if cached and hashlib.sha256(cached.encode()).hexdigest()==version:payload=json.loads(cached)
    else:
        with con.cursor() as cur:
            cur.execute('SELECT payload_json FROM admissions_publication WHERE version_id=%s',(version,));payload=json.loads(cur.fetchone()[0])
        con.commit()
        if hashlib.sha256(encode(payload).encode()).hexdigest()!=version:raise ValueError('MySQL publication integrity failure')
        try:
            with connect_redis(root/'.research/admissions-data') as client:client.set('gradheat:admissions:'+version,encode(payload),ex=CACHE_TTL)
        except Exception:pass
    mirror(root,version,payload)
    return payload
