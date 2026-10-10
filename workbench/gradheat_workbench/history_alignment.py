"""Link historical contexts to programmes without transplanting past rules."""
from .information_match import identity, compatible


def align_history(programmes, history):
    targets = [(p, identity(p, 'programme')) for p in programmes]
    result = {p['id']: {'matched': [], 'ambiguous': []} for p in programmes}
    for row in history:
        past = identity(row, 'history')
        if not past:
            continue
        candidates = [(p, scope) for p, scope in targets if scope and compatible(dict(scope, year=past['year']), past)]
        # Several catalogue directions can share one major-level history row.
        # Unknown department, code, mode, campus or degree cannot choose between distinct entities.
        facets = ('department', 'major_code', 'degree', 'mode', 'campus', 'route')
        ambiguous = any(not past.get(f) and len({s.get(f) for _, s in candidates if s.get(f)}) > 1 for f in facets)
        for p, _ in candidates:
            result[p['id']]['ambiguous' if ambiguous else 'matched'].append(row['id'])
    for value in result.values():
        value['matched'] = sorted(set(value['matched']))
        value['ambiguous'] = sorted(set(value['ambiguous']))
    return result
