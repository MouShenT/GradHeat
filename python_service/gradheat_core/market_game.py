"""Entropy-regularized capacity congestion; no assumed real applicant count."""
import math

MODEL='capacity-entropy-congestion-v2'


def equilibrium(options, demand_factor=1.0, crowding=1.2, temperature=.8):
    if not options:
        return dict(model=MODEL, shares={}, pressure={}, converged=True, residual=0, iterations=0)
    if len(options)>1000 or len({x['id'] for x in options})!=len(options):
        raise ValueError('Bounded unique market options required')
    if any(not math.isfinite(x['capacity']) or not .1<=x['capacity']<=50000 or not math.isfinite(x['attraction']) or abs(x['attraction'])>50 for x in options):
        raise ValueError('Observed positive capacities and finite attractions required')
    if not .1<=demand_factor<=5 or not .1<=crowding<=10 or not .1<=temperature<=5:
        raise ValueError('Invalid game parameters')
    total=sum(x['capacity'] for x in options)
    capacities=[x['capacity']/total for x in options]
    slopes=[crowding*demand_factor/c for c in capacities]
    attractions=[x['attraction'] for x in options]
    def response(multiplier):
        result=[]
        for slope,attraction in zip(slopes,attractions):
            low,high=-200.,0.
            for _ in range(44):
                value=(low+high)/2
                if slope*math.exp(value)+temperature*value-attraction+multiplier>0: high=value
                else: low=value
            result.append(math.exp((low+high)/2))
        return result
    low=min(attractions)-crowding*demand_factor-temperature*math.log(len(options))-5
    high=max(attractions)+5
    for iteration in range(64):
        multiplier=(low+high)/2
        shares=response(multiplier)
        if sum(shares)>1: low=multiplier
        else: high=multiplier
        if high-low<1e-10: break
    shares=response((low+high)/2)
    mass=sum(shares)
    shares=[x/mass for x in shares]
    derivatives=[slope*x+temperature*math.log(x)-a for slope,x,a in zip(slopes,shares,attractions)]
    residual=max(derivatives)-min(derivatives)
    return dict(model=MODEL, shares={o['id']:x for o,x in zip(options,shares)},
                pressure={o['id']:demand_factor*x/c for o,x,c in zip(options,shares,capacities)},
                converged=residual<1e-7 and abs(sum(shares)-1)<1e-10, residual=residual,iterations=iteration+1,
                demand_factor=demand_factor, real_applicants=None)
