"""Offline coverage, counterfactual invariants and historical cutoff diagnostics."""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'))
from gradheat_core.intelligence import PersonalProfile,VictoryInput,victory_indices
from gradheat_core.decision_inputs import resolve_inputs
from gradheat_core.history_alignment import align_history


def evaluate(payload,dossiers):
    alignment=payload.get('historical_alignment') or align_history(payload['programmes'],payload.get('history',[]))
    histories={h['id']:h for h in payload.get('history',[])}
    programmes=[p for p in payload['programmes'] if p.get('eligible_11408') is True and p['year']==payload.get('target_year',2027)]
    inputs={p['id']:resolve_inputs(p,dossiers.get(p['unit'],{}),[histories[k] for k in alignment.get(p['id'],{}).get('matched',[]) if k in histories]) for p in programmes}
    def run(score,**fields):
        return victory_indices(payload,dossiers,VictoryInput(data_version='a'*64,profile=PersonalProfile(score=score,**fields),limit=200))
    base=run(350);higher=run(380);safe=run(350,risk_aversion=1)
    scores={r['unit']:r for r in base['ranking']}
    checks=dict(score_monotonic=all(r['victory_index'] is None or r['victory_index']>=scores[r['unit']]['victory_index'] for r in higher['ranking']),
                conservative_bounded=all(r['victory_index'] is None or r['victory_index']<=scores[r['unit']]['victory_index'] for r in safe['ranking']),
                game_converged=base['game_converged'],maximum_stationarity_residual=base['game']['maximum_residual'])
    # Hold out each latest cutoff, training ONLY on older cutoff values. This is
    # a retrospective stability diagnostic: original publication dates and
    # individual admission outcomes are insufficient for causal/probability validation.
    folds={}
    for p in programmes:
        item=inputs[p['id']];values=item['threshold_history']
        if item['subject_change'] or len(values)<2:continue
        target=values[0];training=values[1:]
        last=training[0]['value'];trend=last
        if len(training)>1:
            delta=(training[0]['value']-training[1]['value'])/(training[0]['year']-training[1]['year'])
            trend+=max(-10,min(10,.5*delta*(target['year']-training[0]['year'])))
        folds[item['competition_pool']]=dict(unit=p['unit'],year=target['year'],latest_error=abs(last-target['value']),bounded_trend_error=abs(trend-target['value']))
    folds=list(folds.values())
    return dict(eligible_programmes=len(programmes),eligible_units=len({p['unit'] for p in programmes}),
                score_ready_units=sum(r['victory_index'] is not None for r in base['ranking']),
                score_missing_units=[r['unit'] for r in base['ranking'] if r['victory_index'] is None],
                current_net_quota_programmes=sum(i['ordinary_quota'] is not None for i in inputs.values()),
                capacity_reference_programmes=sum(i['capacity_proxy'] is not None for i in inputs.values()),
                game_options=base['game_options'],checks=checks,
                historical_diagnostic=dict(pools=len(folds),units=len({f['unit'] for f in folds}),
                    latest_cutoff_mae=round(statistics.mean(f['latest_error'] for f in folds),2) if folds else None,
                    bounded_trend_mae=round(statistics.mean(f['bounded_trend_error'] for f in folds),2) if folds else None,
                    kind='retrospective-cutoff-stability',probability_calibrated=False,
                    limitation='No individual admission outcomes or complete pre-decision timestamped data. No automatic weight fitting.'),
                dossiers=len(dossiers),decision_facts=sum(len(d.get('decision_facts',[])) for d in dossiers.values()),
                observed_search_signals=sum(len(d.get('search_signals',[])) for d in dossiers.values()))


def main():
    p=argparse.ArgumentParser();p.add_argument('--payload',type=Path,required=True);p.add_argument('--dossiers',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'.research/index-evaluation/report.json');args=p.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to((ROOT/'.research').resolve()):raise ValueError('Evaluation reports contain local data and must stay in .research')
    result=evaluate(json.loads(args.payload.read_text(encoding='utf-8')),json.loads(args.dossiers.read_text(encoding='utf-8')))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
