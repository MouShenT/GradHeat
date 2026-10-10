import hashlib

from gradheat.material_store import encode
from gradheat_workbench.admissions_decision import evaluate_public, publication_version, render_report
from gradheat_workbench.congestion import ScenarioInput, simulate
from gradheat_workbench.dashboard import DiscoveryInput, discover, programme_overview
from gradheat_workbench.models import AdmissionsComparisonInput


class VersionConflict(ValueError):
    pass


class CandidateMissing(KeyError):
    pass


class AnalysisService:
    def __init__(self, publications, heat, root):
        self.publications = publications
        self.heat = heat
        self.root = root

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
        if unit not in {row['name'] for row in self.payload()['units']}:
            raise CandidateMissing('招生单位不属于当前资料')
        return self.heat.read(unit)
