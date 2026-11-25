"""Smoothed grid maximum likelihood and population-weighted pair comparisons."""
import numpy as np

from .likelihood import STATS, _counts


GRID = np.linspace(.0025, .9975, 400)
SIGMA = 3.0
ITERATIONS = 300
RADIUS = int(4 * SIGMA)
KERNEL = np.exp(-.5 * (np.arange(-RADIUS, RADIUS + 1) / SIGMA) ** 2)
KERNEL /= KERNEL.sum()


def _scaled_log_likelihood(x, n):
    values = x[:, None] * np.log(GRID) + (n - x)[:, None] * np.log1p(-GRID)
    return values - values.max(axis=1, keepdims=True)


def _fit_weights(x, n):
    # Group repeated observations; zero-trial rows have responsibility g.
    counts, freq = np.unique(np.stack((x, n), axis=1), axis=0, return_counts=True)
    weights = np.full(len(GRID), 1 / len(GRID))
    if not np.any(n):
        return weights
    likelihood = np.exp(_scaled_log_likelihood(counts[:, 0], counts[:, 1]))
    for _ in range(ITERATIONS):
        marginal = np.einsum("ij,j->i", likelihood, weights)
        update = weights * np.einsum("i,ij->j", freq / marginal, likelihood)
        # Retain the convolution on the specified support and renormalize.
        smooth = np.convolve(update, KERNEL, mode="same")
        weights = np.maximum(smooth, 1e-250)
        weights /= weights.sum()
    return weights


def fit_grid_priors(profiles):
    profiles = list(profiles)
    return {
        "theta": GRID.tolist(), "iterations": ITERATIONS, "sigma_steps": SIGMA,
        "weights": {key: _fit_weights(*_counts(profiles, x, n)).tolist() for key, x, n in STATS},
    }


class GridScores:
    def __init__(self, profiles, prior):
        self.terms = {}
        for key, success, trials in STATS:
            x, n = _counts(profiles, success, trials)
            weights = np.asarray(prior["weights"][key])
            log_l = _scaled_log_likelihood(x, n)
            log_g = np.log(np.maximum(weights, np.finfo(float).tiny))
            marginal = np.logaddexp.reduce(log_l + log_g, axis=1)
            # Dot products of these vectors are joint / (marginal_i * marginal_j).
            vectors = np.exp(log_l + .5 * log_g - marginal[:, None])
            self.terms[key] = vectors, n

    def components(self, i, others):
        result = {}
        for key, (vectors, n) in self.terms.items():
            odds = np.einsum("...k,k->...", vectors[others], vectors[i])
            value = np.log10(np.maximum(odds, np.finfo(float).tiny))
            result[key] = np.where((n[i] == 0) | (n[others] == 0), 0.0, value)
        return result

    def row(self, i, others):
        return sum(self.components(i, others).values())
