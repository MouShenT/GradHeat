from . import bootstrap
from contextlib import asynccontextmanager
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse,FileResponse
from pydantic import Field

from gradheat_core.admissions_decision import publication_version
from gradheat_core.congestion import ScenarioInput
from gradheat_core.dashboard import DiscoveryInput
from gradheat_core.models import AdmissionsComparisonInput
from gradheat_core.intelligence import VictoryInput

from .config import Settings
from .database import Database
from .heat import HeatReader
from .publication import PublicationReader, PublicationUnavailable
from .service import AnalysisService, CandidateMissing, VersionConflict


class VersionedScenario(ScenarioInput):
    data_version: str = Field(pattern=r'^[a-f0-9]{64}$')


def create_app(settings=None, *, database=None, publications=None, heat=None):
    settings = settings or Settings.from_env()
    if len(settings.internal_token) < 32:
        raise ValueError('Internal service authentication must be configured')
    database = database or Database(settings)
    publications = publications or PublicationReader(database, settings)
    custom_heat = heat is not None
    heat = heat or HeatReader(database)
    from .intelligence import DossierReader
    service = AnalysisService(publications, heat, settings.root, None if custom_heat else DossierReader(database))

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service
        yield

    app = FastAPI(title='GradHeat Python Internal Service', version='1.0.0', lifespan=lifespan,
        docs_url=None, redoc_url=None)
    app.state.service = service
    from .collection_web import CollectionWeb
    collection=CollectionWeb(settings.root)
    app.state.collection=collection

    def authenticate(token: str | None = Header(default=None, alias='X-GradHeat-Internal-Token')):
        if not token or not hmac.compare_digest(token, settings.internal_token):
            raise HTTPException(401, 'Internal authentication required')

    @app.middleware('http')
    async def bounded_request(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            # Body is bounded even for chunked requests lacking content-length.
            total = 0
            chunks = []
            async for chunk in request.stream():
                total += len(chunk)
                if total > (5_000_000 if request.url.path=='/internal/v1/collection/prepare' else 200_000):
                    return JSONResponse({'detail': 'Input exceeds service budget'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(VersionConflict)
    async def version_error(request, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.exception_handler(CandidateMissing)
    async def candidate_error(request, error):
        return JSONResponse({'detail': str(error.args[0])}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid_input(request, error):
        return JSONResponse({'detail': 'Invalid input or publication integrity failure'}, status_code=422)

    @app.exception_handler(PublicationUnavailable)
    async def unavailable(request, error):
        return JSONResponse({'detail': 'Committed publication temporarily unavailable'}, status_code=503)

    @app.get('/health')
    def health():
        return {'status': 'up', 'service': 'gradheat-python', 'version': '1.0.0'}

    @app.get('/internal/v1/ready', dependencies=[Depends(authenticate)])
    def ready():
        return {'status': 'ready', 'data_version': publication_version(service.payload())}

    @app.get('/internal/v1/admissions', dependencies=[Depends(authenticate)])
    def admissions():
        payload = service.payload()
        return JSONResponse(payload, headers={'X-Data-Version': publication_version(payload)})

    @app.get('/internal/v1/dashboard', dependencies=[Depends(authenticate)])
    def dashboard():
        return service.dashboard()

    @app.get('/internal/v1/heat', dependencies=[Depends(authenticate)])
    def heat_data(unit: str = Query(min_length=1, max_length=160)):
        return service.heat_for(unit)

    @app.post('/internal/v1/recommendations', dependencies=[Depends(authenticate)])
    def recommendations(request: DiscoveryInput):
        return service.recommendations(request)

    @app.post('/internal/v1/victory-index', dependencies=[Depends(authenticate)])
    def victory(request: VictoryInput):
        return service.victory(request)

    @app.get('/internal/v1/school-dossier', dependencies=[Depends(authenticate)])
    def school(unit: str = Query(min_length=1, max_length=160)):
        return service.school(unit)

    @app.get('/internal/v1/school-indices', dependencies=[Depends(authenticate)])
    def school_indices():
        return service.school_indices()

    @app.post('/internal/v1/game-scenario', dependencies=[Depends(authenticate)])
    def scenario(request: VersionedScenario):
        return service.scenario(ScenarioInput.model_validate(request.model_dump(exclude={'data_version'})), request.data_version)

    @app.post('/internal/v1/compare', dependencies=[Depends(authenticate)])
    @app.post('/internal/v1/comparisons/evaluate', dependencies=[Depends(authenticate)])
    def compare(request: AdmissionsComparisonInput):
        return service.comparison(request)

    @app.post('/internal/v1/collection/browser',dependencies=[Depends(authenticate)])
    def collection_browser():return collection.open_browser()

    @app.get('/internal/v1/collection/browser',dependencies=[Depends(authenticate)])
    def collection_browser_status():return collection.browser_status()

    @app.post('/internal/v1/collection/prepare',dependencies=[Depends(authenticate)])
    def collection_prepare(source:dict):return collection.prepare(source)

    @app.get('/internal/v1/collection/{batch_id}',dependencies=[Depends(authenticate)])
    def collection_progress(batch_id:str):return collection.progress(batch_id)

    @app.get('/internal/v1/collection/{batch_id}/download/{kind}',dependencies=[Depends(authenticate)])
    def collection_download(batch_id:str,kind:str):
        path=collection.download(batch_id,kind)
        return FileResponse(path,filename=path.name,media_type='application/json' if kind=='incomplete' else 'application/zip')

    return app


def main():
    import uvicorn
    import os
    uvicorn.run(create_app(), host=os.getenv('GRADHEAT_BIND_HOST', '127.0.0.1'),
        port=int(os.getenv('GRADHEAT_PYTHON_PORT', '18730')), access_log=False)


if __name__ == '__main__':
    main()
