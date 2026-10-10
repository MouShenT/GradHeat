"""Adapters are bounded. Collection never promotes an unreviewed fact."""
from . import bootstrap
from collections import Counter
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, model_validator
from gradheat.material_store import archive, encode, readback
from gradheat_workbench.corroboration import Corroborator
from gradheat_workbench.models import InputModel
from .api import VersionedScenario
from .messages import PROCESSOR_VERSION
from .publication import FrozenPublication
from .service import AnalysisService


class PausedHuman(RuntimeError):
    def __init__(self, code, payload=None):
        self.code = code
        self.payload = payload or {'reason': code}
        super().__init__(code)


class Cancelled(RuntimeError):
    pass


class OfficialItem(InputModel):
    unit: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=10, max_length=1800)
    title: str = Field(min_length=1, max_length=240)
    year: Literal[2025, 2026, 2027]


class OfficialScope(InputModel):
    items: list[OfficialItem] = Field(default_factory=list, max_length=12)
    resume_batch: str | None = Field(default=None, max_length=240)

    @model_validator(mode='after')
    def one_mode(self):
        if bool(self.items) == bool(self.resume_batch):
            raise ValueError('Choose bounded items or an existing frozen batch')
        return self


class SocialScope(InputModel):
    units: list[str] = Field(default_factory=list, max_length=2)
    platforms: list[Literal['xhs', 'zhihu', 'dy', 'bili']] = Field(default_factory=lambda: ['xhs', 'bili'], max_length=4)
    limit: int = Field(default=2, ge=1, le=3)
    resume_batch: str | None = Field(default=None, max_length=240)
    worker: Literal['win-primary'] = 'win-primary'

    @model_validator(mode='after')
    def bounded(self):
        if self.resume_batch:
            if self.units:
                raise ValueError('Storage resume cannot contain new queries')
        elif not self.units or not self.platforms:
            raise ValueError('Social collection needs units and platforms')
        if len(set(self.units)) != len(self.units) or len(set(self.platforms)) != len(self.platforms):
            raise ValueError('Repeated collection scope')
        return self


class ExtractScope(InputModel):
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    format: Literal['pdf', 'html', 'text']
    max_pages: int = Field(default=80, ge=1, le=200)


class VerifyScope(InputModel):
    observation_ids: list[str] = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def ids(self):
        if any(not re.fullmatch('[a-f0-9]{64}', x) for x in self.observation_ids):
            raise ValueError('Only stored immutable observation ids are allowed')
        return self


class AnalysisScope(InputModel):
    operation: Literal['recommendations', 'game-scenario', 'compare', 'dashboard', 'heat']
    input: dict = Field(default_factory=dict)


class AutonomousScope(InputModel):
    batch_id:str=Field(pattern=r'^batch-[0-9]{8}-[a-f0-9]{12}$')
    plan_sha:str=Field(pattern=r'^[a-f0-9]{64}$')
    retry_platforms:list[Literal['xhs','zhihu','dy','bili']]=Field(default_factory=list,max_length=4)


def frozen_path(root, relative, prefix):
    path = (root / relative).resolve()
    if not path.is_relative_to((root / prefix).resolve()) or not path.is_dir():
        raise ValueError('Resume batch must be an existing project-owned frozen folder')
    return path


def validate_public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError('Only public HTTP official source URLs are accepted')
    if not parsed.hostname:
        raise ValueError('Missing public host')
    forbidden = {'cookie', 'token', 'signature', 'authorization', 'password', 'sign'}
    if forbidden & {x.lower() for x in parse_qs(parsed.query)}:
        raise ValueError('Session parameters are forbidden in official sources')
    # Block numeric/private targets before a fetch; URL must additionally match the unit's approved domains.
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Source host must resolve only to public addresses')


class Handlers:
    def __init__(self, service, database, settings):
        self.service, self.database, self.settings = service, database, settings
        self.root = settings.root

    def process(self, command, context):
        if command.processor_version != PROCESSOR_VERSION:
            raise ValueError('Unknown processor version')
        if datetime.now(timezone.utc) >= command.deadline_at:
            raise TimeoutError('Task deadline expired before work')
        if context.cancelled.is_set():
            raise Cancelled('Task was cancelled before work')
        if hasattr(self.service.publications, 'get_version'):
            payload = self.service.publications.get_version(command.input_version)
        else:
            payload = self.service.payload(command.input_version)
        context.service = AnalysisService(FrozenPublication(payload), self.service.heat, self.root)
        method = {
            'analyse.long': self.analysis, 'extract.documents': self.extract,
            'verify.information': self.verify, 'collect.official': self.official,
            'collect.social.win-primary': self.social,
            'collect.autonomous.win-primary':self.autonomous,
        }[command.type]
        return method(command, context)

    def autonomous(self,command,context):
        if os.name!='nt' or self.settings.worker_id!='win-primary':raise ValueError('Collection belongs to Windows win-primary')
        scope=AutonomousScope.model_validate(command.scope)
        from .collection_web import CollectionWeb
        from .collection_plan import read_plan
        from .collection_cli import run,export
        folder=CollectionWeb(self.root).batch(scope.batch_id);plan=read_plan(folder)
        if plan['plan_sha']!=scope.plan_sha:raise ValueError('Collection plan changed')
        hours=min(plan['policy']['execution']['default_hours'],(command.deadline_at-datetime.now(timezone.utc)).total_seconds()/3600)
        result=run(folder,hours=hours,retry_platforms=scope.retry_platforms,stop_event=context.cancelled)
        # All raw details stay in the frozen batch; task result carries safe summary only.
        from collect_social_sources import collector_lock
        with collector_lock(self.root,'full-run'):export(folder)
        return {'batch_id':folder.name,'planned_jobs':result['planned_jobs'],'states':result['states'],
            'queue_finished':result['finished'],'materials_complete':result['material_scope_complete'],
            'needs_analysis':True}

    def analysis(self, command, context):
        service = context.service
        scope = AnalysisScope.model_validate(command.scope)
        request = dict(scope.input)
        if scope.operation in ('recommendations', 'compare', 'game-scenario'):
            if request.get('data_version', command.input_version) != command.input_version:
                raise ValueError('Analysis parameters use a different publication')
            request['data_version'] = command.input_version
        if scope.operation == 'recommendations':
            return service.recommendations(request)
        if scope.operation == 'compare':
            return service.comparison(request)
        if scope.operation == 'game-scenario':
            model = VersionedScenario.model_validate(request)
            from gradheat_workbench.congestion import ScenarioInput
            return service.scenario(ScenarioInput.model_validate(model.model_dump(exclude={'data_version'})), model.data_version)
        if scope.operation == 'dashboard':
            if request:
                raise ValueError('Dashboard task has no additional parameters')
            return service.dashboard()
        if set(request) != {'unit'}:
            raise ValueError('Heat task requires only unit')
        return service.heat_for(request['unit'])

    def extract(self, command, context):
        scope = ExtractScope.model_validate(command.scope)
        chunks = []
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute("SELECT byte_size,chunk_count,media_type FROM material_blob WHERE sha256=%s AND state='complete'", (scope.sha256,))
                meta = cur.fetchone()
                if meta is None or meta[0] > 20_000_000:
                    raise ValueError('Stored original unavailable or over document budget')
                sha, size, count = readback(cur, scope.sha256, chunks.append)
                if sha != scope.sha256 or size != meta[0] or count != meta[1]:
                    raise ValueError('Original byte integrity failure')
            con.rollback()
        raw = b''.join(chunks)
        truncated = False
        if scope.format == 'pdf':
            if not raw.startswith(b'%PDF'):
                raise ValueError('Declared PDF does not match original bytes')
            import pymupdf
            with pymupdf.open(stream=raw, filetype='pdf') as doc:
                pages = [dict(page=n + 1, text=doc[n].get_text()) for n in range(min(len(doc), scope.max_pages))]
                truncated = len(doc) > scope.max_pages
        elif scope.format == 'html':
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, 'html.parser')
            for hidden in soup(['script', 'style']):
                hidden.decompose()
            pages = [dict(page=1, text=soup.get_text('\n', strip=True))]
        else:
            pages = [dict(page=1, text=raw.decode('utf-8', errors='strict'))]
        # Word/character budget supplements page count for malformed PDFs or large HTML.
        remaining = 800_000
        for page in pages:
            if len(page['text']) > remaining:
                truncated = True
            page['text'] = page['text'][:remaining]
            remaining -= len(page['text'])
        return dict(original_sha256=scope.sha256, transcription_sha256=hashlib.sha256(encode(pages).encode()).hexdigest(),
            pages=pages, truncated=truncated, state='text-candidate', images_verified=False,
            note='原件已从MySQL逐字节复验；转录为候选，图片及表格列对齐仍需审核。')

    def verify(self, command, context):
        scope = VerifyScope.model_validate(command.scope)
        selected = set(scope.observation_ids)
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute('SELECT internal_manifest FROM admissions_publication WHERE version_id=%s', (command.input_version,))
                publication = cur.fetchone()
                consensus_id = json.loads(publication[0]).get('consensus_run_id') if publication else None
                if not consensus_id:
                    raise ValueError('Publication has no reviewed consensus snapshot')
                cur.execute('SELECT payload_json FROM corroboration_run WHERE run_id=%s', (consensus_id,))
                consensus = cur.fetchone()
                if not consensus:
                    raise ValueError('Reviewed consensus snapshot is unavailable')
                consensus = json.loads(consensus[0])
                if hashlib.sha256(encode(consensus).encode()).hexdigest() != consensus_id:
                    raise ValueError('Consensus snapshot integrity failure')
                active_ids = set(consensus['observation_ids'])
                if selected - active_ids:
                    raise ValueError('Only observations in this publication consensus may be verified')
                cur.execute('SELECT observation_id,payload_json FROM corroboration_observation WHERE observation_id IN (' + ','.join(['%s'] * len(selected)) + ')', tuple(sorted(selected)))
                rows = cur.fetchall()
                if {r[0] for r in rows} != selected:
                    raise ValueError('One or more stored observations are missing')
                scopes = set()
                for oid, raw in rows:
                    row = json.loads(raw)
                    if row.get('id') != oid:
                        raise ValueError('Observation identity mismatch')
                    scopes.add(row['scope']['unit'])
                # Include all observations of the same units, not only two hand-picked matching values.
                cur.execute("SELECT o.observation_id,o.payload_json FROM corroboration_observation o JOIN corroboration_run r ON r.run_id=%s WHERE JSON_CONTAINS(JSON_EXTRACT(r.payload_json,'$.observation_ids'),JSON_QUOTE(o.observation_id)) AND JSON_UNQUOTE(JSON_EXTRACT(o.payload_json,'$.scope.unit')) IN (" + ','.join(['%s'] * len(scopes)) + ') ORDER BY o.observation_id LIMIT 10001', (consensus_id, *sorted(scopes)))
                all_rows = cur.fetchall()
                if len(all_rows) > 10000:
                    raise ValueError('Verification scope exceeds bounded unit budget')
                observations = []
                for oid, raw in all_rows:
                    row = json.loads(raw)
                    if row.get('id') != oid or hashlib.sha256(encode({k: v for k, v in row.items() if k != 'id'}).encode()).hexdigest() != oid:
                        raise ValueError('Stored observation hash mismatch')
                    observations.append(row)
            con.rollback()
        checker = Corroborator(observations)
        decisions = checker.decisions()
        # Reuse semantic rules and independent-origin chains; raw candidates are not extra votes.
        return dict(policy=checker.policy, observation_count=len(observations), selected_observations=len(selected),
            decisions=decisions, information_agreements=checker.information_agreements(decisions),
            note='只复核已审核入库的观察；不同年度、专业、方向、人群及来源链不混用。未自动切换公开发布头。')

    def official(self, command, context):
        scope = OfficialScope.model_validate(command.scope)
        helper = str(self.root / 'tools/research')
        if helper not in sys.path:
            sys.path.insert(0, helper)
        import build_unit_dossiers as dossiers
        import refresh_dossier_sources as refresh
        from run_daily_update import local_lock, store_collection_ledger
        with local_lock():
            incomplete_checkpoint = False
            if scope.resume_batch:
                folder = frozen_path(self.root, scope.resume_batch, '.research/daily-update')
                if not (folder / 'sources.json').is_file() or not (folder / 'summary.json').is_file():
                    raise ValueError('Frozen official batch is missing its complete manifest or summary')
                sources = json.loads((folder / 'sources.json').read_text(encoding='utf-8'))
                report = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
            else:
                corpus = {u['name']: u for u in json.loads((self.root / '.research/manual-downloads/全量采集资料.json').read_text(encoding='utf-8'))['units']}
                for item in scope.items:
                    if item.unit not in corpus or not refresh.allowed(item.url, corpus[item.unit]):
                        raise ValueError('Official source does not belong to the approved unit scope')
                folder = self.root / '.research/daily-update' / ('app-' + command.execution_key[:32])
                if folder.exists():
                    if (folder / 'sources.json').is_file() and (folder / 'summary.json').is_file():
                        # Completed fetches are never requested again after a delivery/database failure.
                        sources = json.loads((folder / 'sources.json').read_text(encoding='utf-8'))
                        report = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
                    else:
                        # Recover already frozen per-URL metadata, then pause. Do not retry a
                        # request whose crash point cannot establish whether its original was saved.
                        permitted_items = {(i.unit, i.url) for i in scope.items}
                        sources = [json.loads(p.read_text(encoding='utf-8')) for p in (folder / 'live-meta').glob('*.json')]
                        if any((x.get('unit'), x.get('url')) not in permitted_items for x in sources):
                            raise ValueError('Partial official checkpoint does not match the immutable task')
                        report = dict(source_checks=len(sources), requested=len(scope.items), states=dict(Counter(x['status'] for x in sources)),
                            as_of=datetime.now(timezone.utc).date().isoformat(), changed_documents='not-reviewed', recovery='partial-metadata-no-refetch')
                        incomplete_checkpoint = True
                else:
                    for item in scope.items:
                        validate_public_url(item.url)
                    folder.mkdir(parents=True)
                    prior_work = dossiers.WORK
                    dossiers.WORK = folder
                    sources = []
                    try:
                        for item in scope.items:
                            if context.cancelled.is_set() or datetime.now(timezone.utc) >= command.deadline_at:
                                break
                            sources.append(refresh.fetch(dict(unit=item.unit, unit_info=corpus[item.unit], url=item.url, title=item.title, year=item.year)))
                    finally:
                        dossiers.WORK = prior_work
                    report = dict(source_checks=len(sources), requested=len(scope.items), states=dict(Counter(x['status'] for x in sources)),
                        as_of=datetime.now(timezone.utc).date().isoformat(), changed_documents='not-reviewed')
                    (folder / 'sources.json').write_text(encode(sources), encoding='utf-8')
                    (folder / 'summary.json').write_text(encode(report), encoding='utf-8')
            paths = []
            for source in sources:
                for key in ('raw_path', 'text_path'):
                    if source.get(key):
                        path = Path(source[key]).resolve()
                        if not path.is_relative_to(folder) or not path.is_file():
                            raise ValueError('Frozen official original missing or outside its batch')
                        if key == 'raw_path' and source.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest():
                            raise ValueError('Frozen official original hash changed')
                        paths.append((path, 'original' if key == 'raw_path' else 'transcription'))
            with self.database.connect() as con:
                with con.cursor() as cur:
                    cur.execute("SELECT GET_LOCK('gradheat_material_archive',30)")
                    if cur.fetchone()[0] != 1:
                        raise RuntimeError('Original archive busy; resume the same batch')
                try:
                    materials = archive(con, list(dict.fromkeys(paths)), self.root, progress=lambda *args, **kwargs: None)
                    store_collection_ledger(con, folder.name, datetime.now(timezone.utc).isoformat(), report, sources)
                finally:
                    with con.cursor() as cur:
                        cur.execute("SELECT RELEASE_LOCK('gradheat_material_archive')")
            result = dict(collection=report, materials=materials, batch=folder.relative_to(self.root).as_posix(),
                needs_content_review=True, originals_committed=True,
                scope_complete=bool(scope.resume_batch) or len(sources) == len(scope.items))
            if incomplete_checkpoint:
                raise PausedHuman('official-checkpoint-incomplete-manual-recovery', result)
            if any(x['status'] == 'verification-page' for x in sources):
                raise PausedHuman('official-verification-required', result)
            if context.cancelled.is_set():
                result['cancelled_after_archiving'] = True
                return result
            if not result['scope_complete']:
                raise TimeoutError('Official scope stopped at deadline; archived partial originals')
            return result

    def social(self, command, context):
        scope = SocialScope.model_validate(command.scope)
        if os.name != 'nt' or self.settings.worker_id != 'win-primary':
            raise ValueError('Browser collection belongs only to Windows win-primary')
        helper = str(self.root / 'tools/research')
        if helper not in sys.path:
            sys.path.insert(0, helper)
        import collect_social_sources as social
        if scope.resume_batch:
            folder = frozen_path(self.root, scope.resume_batch, '.research/social/runs')
            # Existing resume persists frozen originals without a browser request, including during pauses.
            result = social.resume(folder)
        else:
            if (self.root / '.research/social/human-browser-handoff.json').exists():
                raise PausedHuman('browser-human-handoff-active')
            health = social.platform_health()
            permitted = {u['name'] for u in context.service.payload(command.input_version)['units']}
            if set(scope.units) - permitted:
                raise ValueError('Social units do not belong to the frozen publication')
            results = []
            blocked = []
            last_request = None
            # Holding the original full-run OS lock also prevents a frozen supervisor
            # from starting during this bounded task. bulk skips only its self-lock check.
            with social.collector_lock(self.root, 'full-run'):
                for unit in scope.units:
                    for platform in scope.platforms:
                        if context.cancelled.is_set() or datetime.now(timezone.utc) >= command.deadline_at:
                            break
                        checkpoint = 'app-' + command.execution_key[:32] + '-' + hashlib.sha256((unit + '\n' + platform).encode()).hexdigest()[:8]
                        frozen = self.root / '.research/social/runs' / checkpoint
                        # Storage-only resume remains allowed while a platform is paused.
                        if not frozen.exists():
                            health = social.platform_health()
                            if health.get(platform, {}).get('state') == 'needs-human':
                                blocked.append(platform)
                                continue
                            if (self.root / '.research/social/human-browser-handoff.json').exists():
                                blocked.append('human-browser-handoff')
                                break
                            if last_request is not None:
                                context.cancelled.wait(max(0, 30 - (time.monotonic() - last_request)))
                                if context.cancelled.is_set():
                                    break
                            last_request = time.monotonic()
                        item = social.run(units_override=[unit], platforms_override=[platform], sort_override='general' if platform == 'dy' else 'latest',
                            detail_limit=scope.limit, skip_discovery=True, image_limit=2, vm=True, bulk=True, run_id_override=checkpoint)
                        if item.get('database_state') != 'committed':
                            raise RuntimeError('Frozen social original storage incomplete; resume without recollecting')
                        if item.get('state') == 'needs-human':
                            blocked.append(platform)
                        results.append({k: v for k, v in item.items() if k != 'folder'})
            result = dict(database_state='committed', state='needs-human' if blocked else 'collected',
                batches=results, paused_platforms=sorted(set(blocked)), requested_pairs=len(scope.units) * len(scope.platforms),
                processed_pairs=len(results), sampling='bounded-keyword-sample')
        if result.get('database_state') != 'committed':
            raise RuntimeError('Original storage incomplete; resume frozen batch, do not recollect')
        public = {k: v for k, v in result.items() if k != 'folder'}
        if result.get('state') == 'needs-human':
            raise PausedHuman('social-verification-required', public)
        return public
