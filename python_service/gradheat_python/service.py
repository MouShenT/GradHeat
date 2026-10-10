import hashlib

from gradheat.material_store import encode
from gradheat_core.admissions_decision import evaluate_public, publication_version, render_report
from gradheat_core.congestion import ScenarioInput, simulate
from gradheat_core.dashboard import DiscoveryInput, discover, programme_overview
from gradheat_core.models import AdmissionsComparisonInput
from gradheat_core.intelligence import VictoryInput, victory_indices
from gradheat_core.history_alignment import align_history


class VersionConflict(ValueError):
    pass


class CandidateMissing(KeyError):
    pass


class AnalysisService:
    def __init__(self, publications, heat, root, dossiers=None):
        self.publications = publications
        self.heat = heat
        self.root = root
        self.dossiers = dossiers

    def victory(self, request):
        request = request if isinstance(request, VictoryInput) else VictoryInput.model_validate(request)
        payload = self.payload(request.data_version)
        if set(request.programme_ids) - {p['id'] for p in payload['programmes']}:
            raise CandidateMissing('专业不属于当前资料')
        if set(request.profile.preferred_units) - {u['name'] for u in payload['units']}:
            raise CandidateMissing('院校不属于当前资料')
        schools = self.dossiers.all(request.data_version) if self.dossiers else {}
        if not payload.get('historical_alignment'):
            payload = dict(payload, historical_alignment=align_history(payload['programmes'],payload.get('history',[])))
        result = victory_indices(payload, schools, request)
        result['dossier_versions'] = {u: d['dossier_version'] for u,d in schools.items()}
        return result

    def school(self, unit):
        payload = self.payload()
        if self.dossiers:
            result = self.dossiers.public(unit,publication_version(payload))
            if result.get('available'): return result
        if unit not in {u['name'] for u in payload['units']}:
            raise CandidateMissing('招生单位不属于当前资料')
        return dict(unit=unit,available=False)

    def school_indices(self):
        return self.dossiers.summaries(publication_version(self.payload())) if self.dossiers else []

    def payload(self, version=None):
        payload = self.publications.get()
        if version is not None and publication_version(payload) != version:
            raise VersionConflict('招生资料已更新，请刷新后重试')
        return payload

    def dashboard(self):
        return programme_overview(self.payload(), self.root)

    def recommendations(self, request):
        if not isinstance(request, DiscoveryInput):
            request = DiscoveryInput.model_validate(request)
        payload = self.payload(request.data_version)
        return discover(payload, programme_overview(payload, self.root), request)

    def scenario(self, request, data_version=None):
        if not isinstance(request, ScenarioInput):
            request = ScenarioInput.model_validate(request)
        payload = self.payload(data_version)
        programmes = {p['id']: p for p in payload['programmes']}
        if any(o.programme_id not in programmes for o in request.options):
            raise CandidateMissing('专业不属于当前资料')
        if any(programmes[o.programme_id].get('year') != 2027
                or programmes[o.programme_id].get('eligible_11408') is not True for o in request.options):
            raise ValueError('博弈候选需为明确2027年11408的专业')
        result = simulate(request)
        return dict(result, data_version=publication_version(payload))

    def comparison(self, request):
        if not isinstance(request, AdmissionsComparisonInput):
            request = AdmissionsComparisonInput.model_validate(request)
        payload = self.payload(request.data_version)
        try:
            result = evaluate_public(payload, request)
        except KeyError as error:
            raise CandidateMissing('所选专业不属于当前资料') from error
        canonical = encode(result)
        sha = hashlib.sha256(canonical.encode()).hexdigest()
        report = render_report(result)
        archive = encode({'result': result, 'report_md': report})
        return dict(result=result, report_md=report, canonical_result=canonical,
            result_sha256=sha, canonical_archive=archive, canonical_record=archive,
            comparison_id=hashlib.sha256(archive.encode()).hexdigest())

    def heat_for(self, unit):
        if self.dossiers:
            item = self.dossiers.all(publication_version(self.payload())).get(unit)
            if item:
                return dict(item['heat'], unit=unit, checked_at=item['observed_at'], platforms=[],
                    dossier_version=item['dossier_version'], read_state='school-database',
                    note='热度值综合讨论与真实搜索信号；搜索数据缺失时使用讨论估算。')
        if unit not in {row['name'] for row in self.payload()['units']}:
            raise CandidateMissing('招生单位不属于当前资料')
        return self.heat.read(unit)
