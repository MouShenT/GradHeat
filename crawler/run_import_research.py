"""Prepare immutable evidence records and import them into the existing VM MySQL.

Default is prepare-only. --vm writes an additive, checksummed research migration
and an atomic batch. --verify-rollback exercises rollback before the actual import.
No credentials, raw browser sessions, candidate names, or original file bytes are
exported. Original documents stay at their recorded local paths.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/research'))
import build_unit_dossiers as d
from gradheat.vm_db import connect_vm

MIGRATION=ROOT/'crawler/sql/002_research_ingest.sql'
OUT=ROOT/'.research/database-ingest-20261003'

def encode(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(encode(x).encode('utf8')).hexdigest()
def file_hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf8'))
def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

def prepare():
 pointer=read(d.WORK/'comparison-draft-pointer.json');snapshot=Path(pointer['path'])
 snapshot_manifest=read(snapshot/'manifest.json')
 for item in snapshot_manifest['outputs']:
  if file_hash(snapshot/item['path'])!=item['sha256']:raise ValueError('Changed comparison output: '+item['path'])
 payload=read(snapshot/'comparison.json')
 dependencies=[dict(path=str(p),sha256=file_hash(p)) for p in [Path(__file__).resolve(),MIGRATION]];records={};artifacts={};links=set();checked_paths={}
 def load(path):
  dependencies.append(dict(path=str(path),sha256=file_hash(path)))
  return read(path)
 dependencies.append(dict(path=str(snapshot/'comparison.json'),sha256=file_hash(snapshot/'comparison.json')))
 def artifact(path,declared=None):
  path=Path(path).resolve()
  if not path.is_relative_to(ROOT):raise ValueError('Artifact outside project: '+str(path))
  if path not in checked_paths:
   checked_paths[path]=(file_hash(path),path.stat().st_size)
  actual,size=checked_paths[path]
  if declared and actual!=declared:raise ValueError('Artifact hash mismatch: '+str(path))
  artifacts.setdefault(actual,dict(sha256=actual,byte_size=size,artifact_path=str(path)))
  return actual
 def source_links(row):
  found=set()
  def visit(value):
   if isinstance(value,dict):
    for pk,hk in [('source_artifact','source_sha256'),('artifact','sha256'),('raw_path','sha256')]:
     if value.get(pk):found.add(artifact(value[pk],value.get(hk)))
    for v in value.values():visit(v)
   elif isinstance(value,list):
    for v in value:visit(v)
  visit(row);return found
 def add(kind,row,state,unit=None,cohort=None):
  row=dict(row);unit=unit or row.get('unit') or row.get('name')
  if unit not in names:raise ValueError('Unknown research unit: '+str(unit))
  eligible=row.get('eligible_11408') if kind=='programme' else None
  if eligible is not None and type(eligible) is not bool:raise ValueError('Eligibility must be bool or null')
  record=dict(kind=kind,unit_name=unit,cohort=cohort if cohort is not None else row.get('cohort',row.get('year')),department=row.get('department'),major_code=row.get('major_code'),study_mode=row.get('mode'),verification_state=state,eligible_11408=None if eligible is None else int(eligible),plan_raw=None,ordinary_quota=None,payload_json=row)
  if kind in ('programme','pool_candidate'):
   plan=row.get('planned_major_raw') if kind=='programme' else row.get('catalogue_plan_raw')
   record['plan_raw']=None if plan is None else str(plan)
   # No subtraction/inference from mixed total/push/special plans.
   record['ordinary_quota']=row.get('ordinary_quota')
  record_id=digest(record);record['record_id']=record_id
  records[record_id]=record
  for sha in source_links(row):links.add((record_id,sha))
 source_rows=load(d.WORK/'live-sources.json')
 priority_names={u['name'] for u in payload['units']}
 # A full discovery pass includes institutions beyond the 68 priority
 # dossiers. Store those source records and candidate unit metadata as well,
 # without adding unreviewed programmes to the comparison snapshot.
 extra_names={row['unit'] for row in source_rows if row.get('unit')}-priority_names
 names=priority_names|extra_names
 for row in payload['units']:add('unit',row,'metadata-only')
 for name in sorted(extra_names):
  add('unit',dict(name=name,group='其他招生单位',candidate_only=True,
      admissions_scope='来源采集对象；2027年11408资格与专业范围未审核'),'metadata-only')
 for row in payload['programmes']:add('programme',row,'extracted-candidate')
 for row in payload['checked_claims']:add('checked_claim',row,row.get('verification_level','passage-verified'))
 for row in load(d.WORK/'official-table-facts.json'):add('official_table_candidate',row,'extracted-candidate')
 for row in load(d.WORK/'admission-statistics-candidates.json'):
  conflict=row['unit']=='中国科学院软件研究所' and row['year']==2025
  if conflict:row=dict(row,conflict_reason='官方页面标题2025、正文2024；不进入2025比较',excluded_from_comparison=True)
  add('admission_statistics_candidate',row,'conflicted' if conflict else 'extracted-candidate')
 for dossier in load(d.WORK/'dossiers.json'):
  for year,rows in dossier['secondary'].items():
   for ordinal,row in enumerate(rows):
    row=dict(row,unit=dossier['unit'],source_row_ordinal=ordinal)
    add('secondary_table',row,'secondary-unverified' if row.get('aligned') else 'secondary-unaligned',cohort=int(year))
  for ordinal,row in enumerate(dossier.get('catalogue_page_candidates',[])):
   add('catalogue_page_candidate',dict(row,unit=dossier['unit'],source_row_ordinal=ordinal),'extracted-candidate')
 for row in source_rows:add('source_observation',row,'metadata-only')
 channels=ROOT/'.research/channel-supplement-20261003/sources.json'
 if channels.exists():
  for row in load(channels):add('source_observation',row,'metadata-only')
 for row in load(d.WORK/'material-availability.json'):add('material_availability',row,'availability-only')
 for row in load(d.WORK/'missing-fields.json'):add('gap',row,'unconfirmed')
 for row in load(d.WORK/'first-pool-candidates.json'):add('pool_candidate',row,'draft')
 rows=sorted(records.values(),key=lambda x:x['record_id']);files=sorted(artifacts.values(),key=lambda x:x['sha256']);pairs=sorted(links)
 counts=dict(Counter(x['kind'] for x in rows))
 identity=dict(source_snapshot=pointer['snapshot_id'],as_of=payload['as_of'],target_year=payload['target_year'],dependencies=dependencies,records=[x['record_id'] for x in rows],artifacts=files,links=pairs)
 batch_id=digest(identity)
 manifest=dict(batch_id=batch_id,state='draft',as_of=payload['as_of'],target_year=payload['target_year'],source_snapshot=pointer['snapshot_id'],dependencies=dependencies,counts=counts,records=len(rows),artifacts=len(files),artifact_paths_checked=len(checked_paths),artifact_links=len(pairs),approved_ranking_pools=0,raw_files_location='local-project',identity_sha256=batch_id)
 package=dict(manifest=manifest,records=rows,artifacts=files,links=pairs)
 path=OUT/batch_id;path.mkdir(parents=True,exist_ok=True)
 write(path/'package.json',package)
 manifest['package_sha256']=file_hash(path/'package.json')
 write(path/'manifest.json',manifest)
 return package,path

def migrate(con):
 from gradheat.db import _split_statements
 checksum=file_hash(MIGRATION)
 statements=list(_split_statements(MIGRATION.read_text(encoding='utf8')))
 with con.cursor() as cur:
  cur.execute(statements[0])
  cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s',(MIGRATION.name,));old=cur.fetchone()
  if old:
   if old[0]!=checksum:raise RuntimeError('Applied migration checksum changed; create a new migration')
   con.rollback();return
  # MySQL DDL commits implicitly. Only the subsequent data batch is atomic.
  for statement in statements[1:]:cur.execute(statement)
  cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)',(MIGRATION.name,checksum))
 con.commit()

def totals(con):
 tables=['research_import_batch','research_record','research_batch_record','research_artifact','research_record_artifact']
 with con.cursor() as cur:
  result={}
  for table in tables:
   cur.execute('SELECT COUNT(*) FROM '+table);result[table]=cur.fetchone()[0]
  return result

def verify(con,package):
 m=package['manifest'];batch=m['batch_id']
 with con.cursor() as cur:
  cur.execute('SELECT r.kind,COUNT(*) FROM research_record r JOIN research_batch_record b ON b.record_id=r.record_id WHERE b.batch_id=%s GROUP BY r.kind',(batch,))
  actual=dict(cur.fetchall())
  if actual!=m['counts']:raise RuntimeError('Batch count mismatch')
  columns=['record_id','kind','unit_name','cohort','department','major_code','study_mode','verification_state','eligible_11408','plan_raw','ordinary_quota','payload_json']
  cur.execute('SELECT '+','.join('r.'+c for c in columns)+' FROM research_record r JOIN research_batch_record b ON b.record_id=r.record_id WHERE b.batch_id=%s',(batch,))
  expected={x['record_id']:x for x in package['records']}
  null_eligible=null_quota=conflicts=0
  for values in cur.fetchall():
   actual_row=dict(zip(columns,values));rid=actual_row['record_id']
   actual_row['payload_json']=json.loads(actual_row['payload_json'])
   if digest({k:v for k,v in actual_row.items() if k!='record_id'})!=rid:raise RuntimeError('Read-back content hash mismatch')
   if actual_row!=expected[rid]:raise RuntimeError('Read-back typed values differ')
   null_eligible+=actual_row['eligible_11408'] is None;null_quota+=actual_row['ordinary_quota'] is None;conflicts+=actual_row['verification_state']=='conflicted'
  cur.execute('SELECT a.sha256,a.byte_size FROM research_artifact a JOIN research_record_artifact ra ON ra.sha256=a.sha256 JOIN research_batch_record b ON b.record_id=ra.record_id WHERE b.batch_id=%s GROUP BY a.sha256,a.byte_size',(batch,))
  if dict(cur.fetchall())!={x['sha256']:x['byte_size'] for x in package['artifacts']}:raise RuntimeError('Artifact read-back mismatch')
  cur.execute('SELECT ra.record_id,ra.sha256 FROM research_record_artifact ra JOIN research_batch_record b ON b.record_id=ra.record_id WHERE b.batch_id=%s',(batch,))
  if set(cur.fetchall())!=set(map(tuple,package['links'])):raise RuntimeError('Artifact relation mismatch')
 return dict(counts=actual,content_hashes='passed',typed_values='passed',artifact_references='passed',unknown_eligibility_null=null_eligible,unknown_quota_null=null_quota,conflicted_records=conflicts)

def insert_batch(con,package):
 m=package['manifest'];batch=m['batch_id']
 con.begin()
 try:
  with con.cursor() as cur:
   # Concurrent imports serialize on a named server lock in run().
   cur.execute('SELECT batch_id FROM research_import_batch WHERE batch_id=%s',(batch,))
   if cur.fetchone():return dict(reused=True,validation=verify(con,package))
   cur.execute('INSERT INTO research_import_batch(batch_id,as_of_date,target_year,source_snapshot,state,manifest_json) VALUES(%s,%s,%s,%s,%s,%s)',(batch,m['as_of'],m['target_year'],m['source_snapshot'],'draft',encode(m)))
   cur.execute('SELECT record_id FROM research_record');existing={x[0] for x in cur.fetchall()}
   rows=[x for x in package['records'] if x['record_id'] not in existing]
   columns=['record_id','kind','unit_name','cohort','department','major_code','study_mode','verification_state','eligible_11408','plan_raw','ordinary_quota','payload_json']
   for start in range(0,len(rows),100):
    cur.executemany('INSERT INTO research_record('+','.join(columns)+') VALUES('+','.join(['%s']*len(columns))+')',[tuple(encode(x[c]) if c=='payload_json' else x[c] for c in columns) for x in rows[start:start+100]])
   cur.execute('SELECT sha256,byte_size FROM research_artifact');existing_files=dict(cur.fetchall())
   for item in package['artifacts']:
    if item['sha256'] in existing_files and existing_files[item['sha256']]!=item['byte_size']:raise RuntimeError('Previously stored artifact size conflicts')
   files=[x for x in package['artifacts'] if x['sha256'] not in existing_files]
   if files:cur.executemany('INSERT INTO research_artifact(sha256,byte_size,artifact_path) VALUES(%s,%s,%s)',[(x['sha256'],x['byte_size'],x['artifact_path']) for x in files])
   cur.executemany('INSERT INTO research_batch_record(batch_id,record_id) VALUES(%s,%s)',[(batch,x['record_id']) for x in package['records']])
   cur.execute('SELECT record_id,sha256 FROM research_record_artifact');old_links=set(cur.fetchall())
   links=[tuple(x) for x in package['links'] if tuple(x) not in old_links]
   if links:cur.executemany('INSERT INTO research_record_artifact(record_id,sha256) VALUES(%s,%s)',links)
  return dict(reused=False,inserted_records=len(rows),inserted_artifacts=len(files),validation=verify(con,package))
 except Exception:
  con.rollback();raise

def run():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vm',action='store_true');parser.add_argument('--verify-rollback',action='store_true');args=parser.parse_args()
 if args.verify_rollback and not args.vm:parser.error('--verify-rollback requires --vm')
 package,path=prepare();result=dict(prepared=str(path),**package['manifest'])
 if args.vm:
  with connect_vm(OUT) as con:
   with con.cursor() as cur:
    cur.execute("SELECT GET_LOCK('gradheat-research-ingest',15)")
    if cur.fetchone()[0]!=1:raise RuntimeError('Another research import is in progress')
   try:
    migrate(con)
    before=totals(con);con.rollback()
    if args.verify_rollback:
     with con.cursor() as cur:
      cur.execute('SELECT batch_id FROM research_import_batch WHERE batch_id=%s',(package['manifest']['batch_id'],));exists=cur.fetchone()
     con.rollback()
     if exists:raise RuntimeError('Rollback verification needs a new prepared batch')
     try:
      insert_batch(con,package)
      raise RuntimeError('Controlled failure before commit')
     except RuntimeError as e:
      con.rollback()
      if str(e)!='Controlled failure before commit':raise
     if totals(con)!=before:raise RuntimeError('Rollback left partial data')
     con.rollback();result['rollback_test']='passed: controlled failure left zero partial rows'
    result['import']=insert_batch(con,package);con.commit()
    result['before']=before;result['after']=totals(con);con.rollback()
   finally:
    con.rollback()
    with con.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('gradheat-research-ingest')")
  # Verify from an independent connection after commit, not only own transaction.
  with connect_vm(OUT) as fresh:
   result['reconnected_validation']=verify(fresh,package);fresh.rollback()
  result['completed_at']=datetime.now(timezone.utc).isoformat()
  write(path/('verification-repeat.json' if result['import']['reused'] else 'verification.json'),result)
  write(OUT/'latest.json',dict(batch_id=package['manifest']['batch_id'],path=str(path),counts=package['manifest']['counts'],after=result['after']))
 else:write(path/'prepared-summary.json',result)
 print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
