"""Empirical beta-binomial priors and row-wise pair likelihood ratios."""
import math

import numpy as np


STATS = [
    ("vpip", "vpip", "hands"),
    ("pfr_given_vpip", "pfr", "vpip"),
    ("threebet", "threebet", "threebet_opportunities"),
    ("wtsd", "went_to_showdown", "saw_flop"),
    ("wonsd", "won_at_showdown", "went_to_showdown"),
]


def _counts(profiles, success, trials):
    x = np.array([getattr(p, success) for p in profiles], dtype=np.int64)
    n = np.array([getattr(p, trials) for p in profiles], dtype=np.int64)
    if np.any((x < 0) | (x > n)):
        raise ValueError(f"Invalid binomial counts for {success}/{trials}")
    return x, n


def _fit(x, n):
    """Maximize the marginal log likelihood in log coordinates (Nelder-Mead)."""
    if not np.any(n):
        return {"alpha": 1.0, "beta": 1.0}
    # log Gamma(t+k) - log Gamma(t) is the sum of log(t+i) for i < k.
    # Each weight counts profiles that use the corresponding term.
    terms = []
    for counts in (x, n - x, n):
        weights = np.bincount(counts)[1:][::-1].cumsum()[::-1]
        terms.append((np.arange(len(weights)), weights))

    def objective(point):
        # A boundary estimate is needed for homogeneous or all-success data.
        if np.any(np.abs(point) > 12):
            return math.inf
        a, b = np.exp(point)
        values = [np.sum(weights * np.log(t + offset))
                  for (t, weights), offset in zip(terms, (a, b, a + b))]
        return values[2] - values[1] - values[0]

    mean = (x.sum() + .5) / (n.sum() + 1)
    start = np.log(np.clip([10 * mean, 10 * (1 - mean)], .001, 10))
    simplex = np.array([start, start + [.5, 0], start + [0, .5]])
    values = np.array([objective(p) for p in simplex])
    for _ in range(200):
        order = np.argsort(values)
        simplex, values = simplex[order], values[order]
        if np.max(np.abs(simplex[1:] - simplex[0])) < 1e-6:
            break
        center = simplex[:2].mean(axis=0)
        reflected = 2 * center - simplex[2]
        score = objective(reflected)
        if score < values[0]:
            expanded = 2 * reflected - center
            expanded_score = objective(expanded)
            if expanded_score < score:
                reflected, score = expanded, expanded_score
        elif score >= values[1]:
            outside = score < values[2]
            target = reflected if outside else simplex[2]
            contraction = (center + target) / 2
            contracted_score = objective(contraction)
            if contracted_score <= min(score, values[2]):
                reflected, score = contraction, contracted_score
            else:
                simplex[1:] = (simplex[1:] + simplex[0]) / 2
                values[1:] = [objective(p) for p in simplex[1:]]
                continue
        simplex[2], values[2] = reflected, score
    a, b = np.exp(simplex[np.argmin(values)])
    return {"alpha": float(a), "beta": float(b)}


def fit_priors(profiles):
    profiles = list(profiles)
    return {key: _fit(*_counts(profiles, success, trials)) for key, success, trials in STATS}


def _lgammas(offset, counts):
    size = 2 * int(counts.max(initial=0)) + 1
    return np.fromiter((math.lgamma(offset + k) for k in range(size)), float, count=size)


class LikelihoodScores:
    def __init__(self, profiles, priors):
        self.terms = {}
        for key, success, trials in STATS:
            x, n = _counts(profiles, success, trials)
            y = n - x
            a, b = priors[key]["alpha"], priors[key]["beta"]
            lx, ly, ln = _lgammas(a, x), _lgammas(b, y), _lgammas(a + b, n)
            base = lx[0] + ly[0] - ln[0]
            marginal = lx[x] + ly[y] - ln[n]
            self.terms[key] = x, y, n, lx, ly, ln, base, marginal

    def components(self, i, others):
        result = {}
        for key, (x, y, n, lx, ly, ln, base, marginal) in self.terms.items():
            joint = lx[x[i] + x[others]] + ly[y[i] + y[others]] - ln[n[i] + n[others]]
            lr = (joint + base - (marginal[i] + marginal[others])) / math.log(10)
            result[key] = np.where((n[i] == 0) | (n[others] == 0), 0.0, lr)
        return result

    def row(self, i, others):
        return sum(self.components(i, others).values())
