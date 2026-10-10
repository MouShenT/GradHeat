"""User preference intervals; no forecast or cross-year admissions inference."""

from .models import DIMENSIONS


def interval_scores(cards: list[dict], weights: dict[str, float]):
    total = sum(weights.values())
    normalized = {d: weights[d] / total for d in DIMENSIONS}
    intervals = {}
    for card in cards:
        if card["hard_constraint_status"] == "blocked":
            continue
        low = high = known = 0.0
        missing = []
        for dimension, weight in normalized.items():
            rating = card["ratings"].get(dimension)
            if rating is None:
                high += weight * 10
                if weight > 0:
                    missing.append(dimension)
            else:
                low += weight * rating["low"]
                high += weight * rating["high"]
                known += weight
        intervals[card["id"]] = {
            "low": low, "high": high, "specified_weight": known, "unknown_dimensions": missing
        }
    # Compare unrounded values. All results are conditional on user inputs.
    potential = [i for i, s in intervals.items()
                 if s["high"] + 1e-10 >= max((o["low"] for j, o in intervals.items() if j != i), default=0)]
    certain = [i for i, s in intervals.items()
               if s["low"] + 1e-10 >= max((o["high"] for j, o in intervals.items() if j != i), default=0)]
    for s in intervals.values():
        for key in ["low", "high", "specified_weight"]:
            s[key] = round(s[key], 4)
    return {"normalized_weights": normalized, "intervals": intervals,
            "potential_best": potential, "certain_best": certain}
