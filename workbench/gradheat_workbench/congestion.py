"""A finite singleton congestion scenario with explicit hypothetical capacity."""
from collections import Counter
import random
from pydantic import Field, model_validator
from .models import InputModel


class ScenarioOption(InputModel):
    programme_id: str = Field(min_length=1, max_length=100)
    capacity: int = Field(ge=1, le=10000)
    preference: float = Field(ge=0, le=10)


class ScenarioInput(InputModel):
    options: list[ScenarioOption] = Field(min_length=2, max_length=8)
    participants: int = Field(default=120, ge=2, le=500)
    crowding_weight: float = Field(default=2, gt=0, le=20)
    seed: int = Field(default=0, ge=0, le=1000000)

    @model_validator(mode='after')
    def unique_options(self):
        if len({x.programme_id for x in self.options}) != len(self.options):
            raise ValueError('同一专业情景不能重复')
        return self


def solve(options, participants, weight, seed=0, move_budget=20000):
    rng=random.Random(seed)
    choices=[rng.randrange(len(options)) for _ in range(participants)]
    counts=Counter(choices)
    def potential():
        return sum(weight*counts[j]*(counts[j]+1)/(2*o.capacity)-counts[j]*o.preference for j,o in enumerate(options))
    initial=potential();moves=0;converged=False
    for _ in range(2000):
        changed=False
        for i,current in enumerate(choices):
            current_utility=options[current].preference-weight*counts[current]/options[current].capacity
            alternatives=[(o.preference-weight*(counts[j]+1)/o.capacity,j) for j,o in enumerate(options) if j!=current]
            best_utility,best=max(alternatives,key=lambda item:(item[0],-item[1]))
            if best_utility>current_utility+1e-9:
                counts[current]-=1;counts[best]+=1;choices[i]=best;moves+=1;changed=True
            if moves>=move_budget:break
        if not changed:converged=True;break
        if moves>=move_budget:break
    exploitability=max((max(o.preference-weight*(counts[j]+1)/o.capacity for j,o in enumerate(options) if j!=current)
        -(options[current].preference-weight*counts[current]/options[current].capacity) for current in choices),default=0)
    return dict(participants=participants,converged=converged,moves=moves,improvement_tolerance=1e-9,
        maximum_improvement=max(0,round(exploitability,9)),potential_initial=round(initial,9),potential_final=round(potential(),9),
        allocations=[dict(programme_id=o.programme_id,hypothetical_capacity=o.capacity,
            hypothetical_choices=counts[j],crowding_ratio=round(counts[j]/o.capacity,4),
            model_utility=round(o.preference-weight*counts[j]/o.capacity,4)) for j,o in enumerate(options)])


def simulate(request):
    base=solve(request.options,request.participants,request.crowding_weight,request.seed)
    sensitivity=[dict(demand_factor=factor,**solve(request.options,max(2,round(request.participants*factor)),request.crowding_weight,request.seed)) for factor in (0.75,1,1.25)]
    return dict(model='finite-singleton-linear-congestion-v1',kind='hypothetical-scenario',base=base,sensitivity=sensitivity,
        assumptions=['模拟参与者均具有你填写的共同偏好，每人选择一个候选；不是实际报考者画像。',
            '效用=个人偏好分−拥挤权重×该选项模拟选择人数/假设容量。',
            '容量和参与人数均由你输入，不读取含推免计划，不推断真实报名需求。',
            '每次只允许严格改善效用的单人迁移；达到计算预算时报告未收敛。'],
        validation='只验证这个假设游戏的最优反应和势函数；未进行考研制度拟合或历史预测验证。',
        admission_probability=None,real_applicants=None,approved_pool=False)
