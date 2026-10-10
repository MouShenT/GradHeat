"""Immutable original bytes, chunked to stay below MySQL's packet limit."""
import hashlib
import json
import mimetypes
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
ORIGINAL_SUFFIXES = {'.pdf','.html','.htm','.doc','.docx','.xls','.xlsx','.png','.jpg','.jpeg','.gif','.zip','.rar','.ole','.bin','.response'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def migrate(con, root):
    path = root / 'crawler/sql/003_material_storage.sql'
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with con.cursor() as cur:
        cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s', (path.name,))
        prior = cur.fetchone()
        if prior:
            if prior[0] != checksum: raise ValueError('Material migration checksum changed')
            return
        for statement in path.read_text(encoding='utf-8').split(';'):
            if statement.strip(): cur.execute(statement)
        cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)', (path.name,checksum))
    con.commit()


def inventory(root):
    """Admissions originals only; never browser sessions, HAR, logs or credentials."""
    research = root / '.research'
    for path in sorted(research.rglob('*')):
        if not path.is_file(): continue
        rel = path.relative_to(research)
        parts = [p.lower() for p in rel.parts[:-1]]
        if any('browser' in p or 'acceptance' in p or 'database-ingest' in p or p == 'decision-workbench' for p in parts): continue
        raw_dir = any('raw' in p or p in {'pages','attachments','chsi-programs','search','mcp-search'} for p in parts)
        manual = bool(parts and parts[0] == 'manual-downloads' and len(parts) > 1)
        suffix = path.suffix.lower()
        if suffix in ORIGINAL_SUFFIXES and (raw_dir or manual):
            yield path, 'original'
        elif suffix == '.json' and raw_dir:
            yield path, 'public-response'
        elif manual and suffix in {'.md','.txt'} and not any(s in path.name for s in ('清单','资料','说明','汇总')):
            if not path.with_suffix('.pdf').exists() and not path.with_suffix('.html').exists():
                yield path, 'saved-text'


def readback(cur, sha, consumer=None):
    h = hashlib.sha256(); size = 0; expected = 0
    cur.execute('SELECT ordinal,content FROM material_chunk WHERE sha256=%s ORDER BY ordinal', (sha,))
    for ordinal, content in cur:
        if ordinal != expected: raise ValueError('Original chunk sequence is incomplete')
        expected += 1; h.update(content); size += len(content)
        if consumer: consumer(content)
    return h.hexdigest(), size, expected


def existing_state(con, paths, root):
    """Small incremental batches need only their hashes, not the entire archive."""
    paths=list(paths)
    wanted_hashes=set();wanted_locations=set()
    small=len(paths)<=512
    if small:
        for filename,_ in paths:
            path=Path(filename).resolve()
            if not path.is_relative_to(root.resolve()):raise ValueError('Original outside project')
            with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
            wanted_hashes.add(sha)
            wanted_locations.add(hashlib.sha256((path.relative_to(root).as_posix()+'\n'+sha).encode()).hexdigest())
    with con.cursor() as cur:
        if small:
            if not wanted_hashes:return paths,{},set()
            cur.execute("SELECT sha256,byte_size FROM material_blob WHERE state='complete' AND sha256 IN ("+','.join(['%s']*len(wanted_hashes))+')',tuple(wanted_hashes))
            existing=dict(cur.fetchall())
            cur.execute('SELECT location_id FROM material_location WHERE location_id IN ('+','.join(['%s']*len(wanted_locations))+')',tuple(wanted_locations))
        else:
            cur.execute("SELECT sha256,byte_size FROM material_blob WHERE state='complete'")
            existing=dict(cur.fetchall())
            cur.execute('SELECT location_id FROM material_location')
        locations={r[0] for r in cur.fetchall()}
    return paths,existing,locations


def archive_serial(con, paths, root, progress=print):
    paths,existing,locations=existing_state(con,paths,root)
    con.commit()
    counts = dict(files=0, inserted=0, reused=0, bytes_inserted=0)
    for path, kind in paths:
        path = Path(path).resolve()
        if not path.is_relative_to(root.resolve()): raise ValueError('Original outside project')
        with path.open('rb') as stream: sha = hashlib.file_digest(stream,'sha256').hexdigest()
        size = path.stat().st_size
        relative = path.relative_to(root).as_posix()
        location = hashlib.sha256((relative+'\n'+sha).encode()).hexdigest()
        if sha in existing and existing[sha] != size: raise ValueError('Original size conflict')
        try:
            with con.cursor() as cur:
                if sha not in existing:
                    cur.execute('INSERT INTO material_blob(sha256,byte_size,chunk_count,media_type,state) VALUES(%s,%s,%s,%s,%s)',
                                (sha,size,(size+CHUNK_SIZE-1)//CHUNK_SIZE,mimetypes.guess_type(path.name)[0] or 'application/octet-stream','writing'))
                    ordinal = 0
                    with path.open('rb') as stream:
                        while data := stream.read(CHUNK_SIZE):
                            cur.execute('INSERT INTO material_chunk(sha256,ordinal,content) VALUES(%s,%s,%s)',(sha,ordinal,data))
                            ordinal += 1
                    import pymysql.cursors
                    with con.cursor(pymysql.cursors.SSCursor) as stream_cur:
                        actual, stored_size, chunk_count = readback(stream_cur,sha)
                    if (actual,stored_size,chunk_count) != (sha,size,ordinal): raise ValueError('MySQL original readback mismatch')
                    cur.execute("UPDATE material_blob SET state='complete',verified_at=UTC_TIMESTAMP(6) WHERE sha256=%s",(sha,))
                    counts['inserted'] += 1; counts['bytes_inserted'] += size
                else: counts['reused'] += 1
                if location not in locations:
                    cur.execute('INSERT INTO material_location(location_id,sha256,local_path,kind) VALUES(%s,%s,%s,%s)',(location,sha,relative,kind))
            con.commit(); existing[sha]=size; locations.add(location); counts['files'] += 1
        except Exception:
            con.rollback(); raise
        if counts['files'] % 100 == 0: progress(encode(counts), flush=True)
    with con.cursor() as cur:
        cur.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM material_blob WHERE state='complete'")
        n, size = cur.fetchone()
    con.commit()
    return {**counts,'stored_unique':n,'stored_bytes':int(size)}


def archive(con, paths, root, progress=print):
    """Bounded batches; verify every stored chunk inside the same transaction."""
    root=root.resolve()
    paths,existing,locations=existing_state(con,paths,root)
    con.commit()
    counts=dict(files=0,inserted=0,reused=0,bytes_inserted=0)
    pending={};aliases={};batch_files=0;memory=0
    def flush():
        nonlocal batch_files,memory
        if not batch_files:return
        try:
            with con.cursor() as cur:
                if pending:
                    cur.executemany('INSERT INTO material_blob(sha256,byte_size,chunk_count,media_type,state) VALUES(%s,%s,%s,%s,%s)',
                        [(sha,item['size'],len(item['chunks']),item['media'],'writing') for sha,item in pending.items()])
                    chunks=[(sha,n,chunk) for sha,item in pending.items() for n,chunk in enumerate(item['chunks'])]
                    if chunks:cur.executemany('INSERT INTO material_chunk(sha256,ordinal,content) VALUES(%s,%s,%s)',chunks)
                    cur.execute('SELECT sha256,ordinal,OCTET_LENGTH(content),SHA2(content,256) FROM material_chunk WHERE sha256 IN ('+','.join(['%s']*len(pending))+') ORDER BY sha256,ordinal',tuple(pending))
                    actual={sha:[] for sha in pending}
                    for sha,n,size,digest in cur.fetchall():actual[sha].append((n,size,digest))
                    for sha,item in pending.items():
                        expected=[(n,len(chunk),hashlib.sha256(chunk).hexdigest()) for n,chunk in enumerate(item['chunks'])]
                        if actual[sha]!=expected:raise ValueError('Stored original chunk integrity mismatch')
                    cur.execute("UPDATE material_blob SET state='complete',verified_at=UTC_TIMESTAMP(6) WHERE sha256 IN ("+','.join(['%s']*len(pending))+')',tuple(pending))
                if aliases:cur.executemany('INSERT INTO material_location(location_id,sha256,local_path,kind) VALUES(%s,%s,%s,%s)',list(aliases.values()))
            con.commit()
        except Exception:con.rollback();raise
        for sha,item in pending.items():existing[sha]=item['size']
        locations.update(aliases)
        counts['inserted']+=len(pending);counts['bytes_inserted']+=sum(x['size'] for x in pending.values());counts['files']+=batch_files
        pending.clear();aliases.clear();batch_files=0;memory=0
        progress(encode(counts),flush=True)
    for path,kind in paths:
        path=Path(path).resolve()
        if not path.is_relative_to(root):raise ValueError('Original outside project')
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        size=path.stat().st_size;relative=path.relative_to(root).as_posix()
        location=hashlib.sha256((relative+'\n'+sha).encode()).hexdigest()
        known=existing.get(sha,pending.get(sha,{}).get('size'))
        if known is not None and known!=size:raise ValueError('Original size conflict')
        if known is None:
            if size>8*1024*1024:
                flush()
                report=archive_serial(con,[(path,kind)],root,progress)
                counts['files']+=report['files'];counts['inserted']+=report['inserted'];counts['reused']+=report['reused'];counts['bytes_inserted']+=report['bytes_inserted']
                existing[sha]=size;locations.add(location)
                continue
            chunks=[]
            with path.open('rb') as stream:
                while chunk:=stream.read(CHUNK_SIZE):chunks.append(chunk)
            if hashlib.sha256(b''.join(chunks)).hexdigest()!=sha:raise ValueError('Original changed during archive')
            pending[sha]={'size':size,'chunks':chunks,'media':mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}
            memory+=size
        else:counts['reused']+=1
        if location not in locations and location not in aliases:aliases[location]=(location,sha,relative,kind)
        batch_files+=1
        if batch_files>=250 or memory>=8*1024*1024:flush()
    flush()
    with con.cursor() as cur:
        cur.execute("SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM material_blob WHERE state='complete'")
        n,size=cur.fetchone()
    con.commit()
    return {**counts,'stored_unique':n,'stored_bytes':int(size)}


def missing_references(con):
    """Find absent originals with indexed lookups across legacy hash charsets."""
    with con.cursor() as cur:
        cur.execute('SELECT artifact_path,sha256 FROM research_artifact')
        rows=cur.fetchall()
        wanted=sorted({sha for _,sha in rows});complete=set()
        # A join between older differently encoded hash columns can defeat the
        # primary-key index. Query the blob's own column with bounded constants.
        for start in range(0,len(wanted),512):
            chunk=wanted[start:start+512]
            cur.execute("SELECT sha256 FROM material_blob WHERE state='complete' AND sha256 IN ("+
                        ','.join(['%s']*len(chunk))+')',tuple(chunk))
            complete.update(row[0] for row in cur.fetchall())
    return [(filename,sha) for filename,sha in rows if sha not in complete]


def archive_references(con,root):
    """Close any byte-storage gap introduced by a new research import."""
    rows=missing_references(con)
    paths=[]
    for filename,expected in rows:
        path=Path(filename).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('Referenced original unavailable')
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=expected:raise ValueError('Referenced original hash mismatch')
        paths.append((path,'referenced-original'))
    return archive(con,paths,root)
