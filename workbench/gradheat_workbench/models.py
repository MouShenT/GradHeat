from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIMENSIONS = {
    "research": "研究兴趣",
    "location": "城市与生活",
    "cost": "费用可承受度",
    "career": "就业与发展",
    "training": "培养方式适配",
}


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Rating(InputModel):
    low: float = Field(ge=0, le=10)
    high: float = Field(ge=0, le=10)
    basis: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def ordered(self):
        if self.low > self.high:
            raise ValueError("评分下限不能高于上限")
        return self


class Profile(InputModel):
    target_year: Literal[2027] = 2027
    modes: list[Literal["全日制", "非全日制"]] = Field(
        default_factory=lambda: ["全日制"], min_length=1, max_length=2
    )
    degrees: list[Literal["学术学位", "专业学位"]] = Field(
        default_factory=lambda: ["学术学位", "专业学位"], min_length=1, max_length=2
    )
    notes: str = Field(default="", max_length=2000)


class CandidateInput(InputModel):
    programme_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    personal_eligibility: Literal["unknown", "self_reported_pass", "self_reported_fail"] = "unknown"
    ratings: dict[str, Rating] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_dimensions(self):
        if set(self.ratings) - set(DIMENSIONS):
            raise ValueError("未知偏好维度")
        return self


class ComparisonInput(InputModel):
    title: str = Field(default="我的专业比较", min_length=1, max_length=120)
    profile: Profile = Field(default_factory=Profile)
    weights: dict[str, float] = Field(default_factory=lambda: dict.fromkeys(DIMENSIONS, 1.0))
    candidates: list[CandidateInput] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_comparison(self):
        if set(self.weights) != set(DIMENSIONS):
            raise ValueError("必须给出全部五个维度的权重")
        if any(not 0 <= value <= 10 for value in self.weights.values()):
            raise ValueError("权重需在0到10之间")
        if sum(self.weights.values()) <= 0:
            raise ValueError("至少一个维度权重大于0")
        ids = [c.programme_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("比较项目不能重复")
        return self


class AdmissionsComparisonInput(ComparisonInput):
    data_version: str = Field(pattern=r'^[a-f0-9]{64}$')
