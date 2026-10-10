import hashlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .decision import evaluate
from . import ANALYSIS_VERSION
from .models import ComparisonInput, AdmissionsComparisonInput
from .repository import ResearchRepository
from .sessions import SessionStore, canonical
from .data_store import AdmissionsStore
from .admissions_decision import evaluate_public, publication_version
from .comparison_archive import MySQLComparisonArchive
from .dashboard import programme_overview,discover,DiscoveryInput
from .congestion import simulate,ScenarioInput
from .heat import HeatStore

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parents[1] / "static"


def create_app(root: Path = ROOT, snapshot: Path | None = None, session_db: Path | None = None, comparison_archive=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.repo = ResearchRepository(root, snapshot)
        app.state.store = SessionStore(session_db or root / ".research/decision-workbench/sessions.sqlite")
        app.state.admissions = AdmissionsStore(root.resolve(), app.state.repo, remote=root.resolve() == ROOT.resolve())
        app.state.admissions.start()
        app.state.comparison_archive = comparison_archive or MySQLComparisonArchive(root)
        app.state.heat = HeatStore(root)
        h = hashlib.sha256()
        for path in sorted(Path(__file__).parent.glob("*.py")):
            h.update(path.name.encode())
            h.update(path.read_bytes())
        app.state.implementation_sha256 = h.hexdigest()
        yield
        app.state.admissions.close()

    app = FastAPI(title="GradHeat 本地择校工作台", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (request.headers.get("sec-fetch-site") == "cross-site"
                    or (origin and urlsplit(origin).netloc != request.headers.get("host"))):
                return JSONResponse({"detail": "比较记录只允许同源写入"}, status_code=403)
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 200_000:
                return JSONResponse({"detail": "比较输入过大"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def result_for(request: ComparisonInput):
        if any(c.programme_id not in app.state.repo.programmes for c in request.candidates):
            raise HTTPException(404, "专业来源ID不属于当前快照")
        result = evaluate(app.state.repo, request)
        result["implementation_sha256"] = app.state.implementation_sha256
        return result

    def saved(session_id: str):
        if not re.fullmatch(r"[a-f0-9]{64}", session_id):
            raise HTTPException(404, "比较记录不存在")
        try:
            return app.state.store.get(session_id)
        except KeyError:
            raise HTTPException(404, "比较记录不存在")
        except ValueError as error:
            raise HTTPException(409, str(error))

    @app.get("/")
    def index():
        return FileResponse(STATIC / "admissions.html")

    @app.get("/api/meta")
    def meta():
        return {**app.state.repo.meta(), "analysis_version": ANALYSIS_VERSION}

    @app.get("/api/admissions")
    def admissions_data():
        payload = app.state.admissions.get()
        return JSONResponse(payload, headers={'X-Data-Version': publication_version(payload), 'X-Comparison-Archive':'exact-bytes-v1'})

    @app.get('/api/dashboard')
    def dashboard_data():
        return programme_overview(app.state.admissions.get(),root)

    @app.get('/api/heat')
    def heat_data(unit: str=Query(min_length=1,max_length=160)):
        if unit not in {u['name'] for u in app.state.admissions.get()['units']}:
            raise HTTPException(404,'招生单位不属于当前资料')
        return app.state.heat.read(unit)

    @app.post('/api/recommendations')
    def recommendations(request: DiscoveryInput):
        payload=app.state.admissions.get()
        if publication_version(payload)!=request.data_version:raise HTTPException(409,'资料已更新，请刷新后重试')
        try:return discover(payload,programme_overview(payload,root),request)
        except ValueError as error:raise HTTPException(422,str(error))

    @app.post('/api/game-scenario')
    def game_scenario(request: ScenarioInput):
        programmes=app.state.admissions.get()['programmes']
        ids={p['id'] for p in programmes}
        if any(o.programme_id not in ids for o in request.options):raise HTTPException(404,'专业不属于当前资料')
        eligible={p['id'] for p in programmes if p.get('year')==2027 and p.get('eligible_11408') is True}
        if any(o.programme_id not in eligible for o in request.options):raise HTTPException(422,'博弈候选需为明确2027年11408的专业')
        return simulate(request)

    def public_result(request):
        payload = app.state.admissions.get()
        if publication_version(payload) != request.data_version:
            raise HTTPException(409, '招生数据已更新，请刷新资料后重新比较。填写内容会保留。')
        try:
            result = evaluate_public(payload, request)
        except KeyError:
            raise HTTPException(404, '所选专业已不在当前资料中，请重新选择。')
        result['implementation_sha256'] = app.state.implementation_sha256
        return result

    def archive_call(method, *args):
        try:
            return getattr(app.state.comparison_archive, method)(*args)
        except KeyError:
            raise HTTPException(404, '比较记录不存在')
        except ValueError as error:
            raise HTTPException(409, str(error))
        except Exception:
            raise HTTPException(503, '比较记录库暂时无法连接；填写内容保留，请稍后重试。')

    def valid_comparison_id(cid):
        if not re.fullmatch(r'[a-f0-9]{64}', cid):
            raise HTTPException(404, '比较记录不存在')

    @app.post('/api/admissions/compare')
    def admissions_compare(request: AdmissionsComparisonInput):
        return public_result(request)

    @app.post('/api/admissions/comparisons')
    def admissions_save(request: AdmissionsComparisonInput):
        return archive_call('save', public_result(request))

    @app.get('/api/admissions/comparisons')
    def admissions_comparisons():
        return {'items': archive_call('list')}

    @app.get('/api/admissions/comparisons/{cid}')
    def admissions_saved(cid: str):
        valid_comparison_id(cid)
        return archive_call('get', cid)

    @app.get('/api/admissions/comparisons/{cid}/export')
    def admissions_export(cid: str, format: Literal['md', 'json'] = 'md'):
        valid_comparison_id(cid)
        value = archive_call('get', cid)
        headers = {'Content-Disposition': f'attachment; filename="gradheat-comparison-{cid[:12]}.{format}"'}
        if format == 'md':
            return PlainTextResponse(value['report_md'], headers=headers)
        return Response(canonical(value), media_type='application/json', headers=headers)

    @app.get("/api/programmes")
    def programmes(q: str = Query(default="", max_length=120), group: str = "", mode: str = "", degree: str = "",
                   eligibility: Literal["matched", "all"] = "matched"):
        return app.state.repo.find(q, group, mode, degree, eligibility)

    @app.get("/api/programmes/{programme_id}")
    def detail(programme_id: str):
        try:
            return app.state.repo.detail(programme_id)
        except KeyError:
            raise HTTPException(404, "专业来源不存在")

    @app.get("/api/evidence/{sha256}")
    def evidence(sha256: str):
        try:
            path = app.state.repo.evidence(sha256)
        except (KeyError, FileNotFoundError):
            raise HTTPException(404, "原件不存在")
        except ValueError as error:
            raise HTTPException(409, str(error))
        # HTML/JSON originals are attachments, never executable pages under this origin.
        return FileResponse(path, filename=path.name, content_disposition_type="attachment")

    @app.post("/api/compare")
    def compare(request: ComparisonInput):
        return result_for(request)

    @app.post("/api/sessions")
    def save(request: ComparisonInput):
        return app.state.store.save(result_for(request))

    @app.get("/api/sessions")
    def sessions():
        return {"items": app.state.store.list()}

    @app.get("/api/sessions/{session_id}")
    def session(session_id: str):
        return saved(session_id)

    @app.get("/api/sessions/{session_id}/export")
    def export(session_id: str, format: Literal["md", "json"] = "md"):
        value = saved(session_id)
        headers = {"Content-Disposition": f'attachment; filename="gradheat-{session_id[:12]}.{format}"'}
        if format == "md":
            return PlainTextResponse(value["report_md"], headers=headers)
        return Response(canonical(value), media_type="application/json", headers=headers)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
