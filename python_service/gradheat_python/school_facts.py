"""Validated, immutable school basics backed by retained public original bytes."""
from . import bootstrap
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from gradheat_core.models import InputModel
from gradheat_core.intelligence import canonical, digest, date_value
from gradheat.material_store import archive_serial


class AdmissionValues(InputModel):
    cutoff: float | None = Field(default=None, ge=200, le=500)
    ordinary_quota: int | None = Field(default=None, ge=0, le=5000)
    interview_count: int | None = Field(default=None, ge=0, le=20000)
    admitted_count: int | None = Field(default=None, ge=0, le=20000)
    admitted_minimum: float | None = Field(default=None, ge=100, le=500)
    admitted_mean: float | None = Field(default=None, ge=100, le=500)
    admitted_maximum: float | None = Field(default=None, ge=100, le=500)
    score_limits: dict[str, float] = Field(default_factory=dict)
    initial_weight: float | None = Field(default=None, ge=0, le=1)
    interview_weight: float | None = Field(default=None, ge=0, le=1)
    machine_test_weight: float | None = Field(default=None, ge=0, le=1)
    cross_major_allowed: bool | None = None
    equivalent_education_allowed: bool | None = None
    previous_graduate_allowed: bool | None = None

    @model_validator(mode='after')
    def consistent(self):
        for key,value in self.score_limits.items():
            if key not in {'politics','english','mathematics','computer'} or not 0 <= value <= (100 if key in {'politics','english'} else 150):
                raise ValueError('Invalid single-subject threshold')
        low,mean,high = self.admitted_minimum,self.admitted_mean,self.admitted_maximum
        if low is not None and high is not None and low>high or mean is not None and (low is not None and mean<low or high is not None and mean>high):
            raise ValueError('Inconsistent admitted score summary')
        if self.initial_weight is not None and self.interview_weight is not None and abs(self.initial_weight+self.interview_weight-1)>.001:
            raise ValueError('Initial and interview weights must sum to one')
        if not any(v is not None and v != {} for v in self.model_dump().values()):
            raise ValueError('An empty observation is not a school fact')
        return self


class SchoolFact(InputModel):
    unit: str = Field(min_length=1,max_length=160)
    year: int = Field(ge=2024,le=2035)
    department: str = Field(default='',max_length=160)
    department_scope: str = Field(default='exact',pattern=r'^(exact|all)$')
    major_code: str = Field(pattern=r'^[0-9A-Z]{6}$')
    major_name: str = Field(min_length=1,max_length=160)
    mode: str = Field(default='全日制',pattern=r'^(全日制|非全日制)$')
    route: str = Field(default='first-choice',pattern=r'^(first-choice|transfer|recommended-exemption)$')
    population: str = Field(default='ordinary',pattern=r'^(ordinary|enrolled|retest_pool|observed-sample)$')
    special: bool = False
    campus: str | None = Field(default=None,max_length=80)
    cutoff_kind: str = Field(default='department',pattern=r'^(department|school-minimum)$')
    observed_at: str
    source_url: str = Field(max_length=2048)
    source_artifact: str = Field(max_length=2048)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    locator: str = Field(min_length=1,max_length=300)
    excerpt: str = Field(default='',max_length=4000)
    values: AdmissionValues

    @model_validator(mode='after')
    def public_original(self):
        parts=urlsplit(self.source_url)
        if parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password or date_value(self.observed_at) is None:
            raise ValueError('A public original and observation timestamp are required')
        if self.population!='ordinary' and self.values.ordinary_quota is not None:
            raise ValueError('An observed sample or roster is not an ordinary quota')
        if self.population not in {'ordinary','retest_pool'} and self.values.cutoff is not None:
            raise ValueError('A roster score is not a published interview cutoff')
        if self.department_scope=='all' and self.department:
            raise ValueError('An all-department rule must not invent an issuing department')
        return self


def import_facts(con, root, rows, units):
    validated=[]
    for row in rows:
        model=SchoolFact.model_validate(row)
        if model.unit not in units: raise ValueError('School is outside the existing registry')
        path=Path(model.source_artifact).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Retained original must be within this workspace')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=model.source_sha256:
            raise ValueError('School fact original checksum mismatch')
        item=model.model_dump(exclude_none=True)
        if not item['values'].get('score_limits'): item['values'].pop('score_limits',None)
        validated.append(item)
    # Validation of the whole batch precedes every write.
    originals=list({r['source_artifact'] for r in validated})
    stored=archive_serial(con,[(p,'school-admission-basics') for p in originals],root,progress=lambda *a,**kw:None)
    inserted=0
    with con.cursor() as cur:
        for row in validated:
            body=canonical(row).encode();sha=digest(row)
            cur.execute('INSERT IGNORE INTO school_decision_fact(fact_sha,unit,cohort,observed_at,payload_json,canonical_bytes) VALUES(%s,%s,%s,%s,%s,%s)',
                        (sha,row['unit'],row['year'],row['observed_at'],body.decode(),body))
            inserted+=cur.rowcount
            cur.execute('SELECT canonical_bytes FROM school_decision_fact WHERE fact_sha=%s',(sha,))
            if bytes(cur.fetchone()[0])!=body: raise ValueError('School fact exact-byte readback mismatch')
    con.commit()
    return dict(records=len(validated),inserted=inserted,originals=stored['files'],units=len({r['unit'] for r in validated}))
