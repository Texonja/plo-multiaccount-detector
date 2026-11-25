"""Directional top-K ranks with deterministic ties and bounded storage."""
import heapq

import numpy as np


class NeighborRanks:
    def __init__(self, model, count, size):
        if size < 1:
            raise ValueError("neighbor_list_size must be positive")
        self.missing = size + 1
        self.ranks = []
        k = min(size, max(0, count - 1))
        for i in range(count):
            ranks = {}
            if k:
                scores = np.array(model.row(i, slice(None)), dtype=float, copy=True)
                scores[i] = -np.inf
                cutoff_index = np.argpartition(scores, count - k)[count - k]
                cutoff = scores[cutoff_index]
                above = np.flatnonzero(scores > cutoff)
                tied = np.flatnonzero(scores == cutoff)[:k - len(above)]
                members = np.concatenate((above, tied))
                order = np.lexsort((members, -scores[members]))
                ranks = {int(j): rank for rank, j in enumerate(members[order], 1)}
            self.ranks.append(ranks)

    def pair(self, i, j):
        forward = self.ranks[i].get(j, self.missing)
        reverse = self.ranks[j].get(i, self.missing)
        return forward, reverse, max(forward, reverse)

    def upper_row(self, i):
        row = np.full(len(self.ranks) - i - 1, self.missing, dtype=int)
        for j, rank in self.ranks[i].items():
            if j > i:
                row[j - i - 1] = max(rank, self.ranks[j].get(i, self.missing))
        return row


class ReportShortlist:
    """Apply the report threshold and keep the best pairs within the row cap."""

    def __init__(self, threshold, cap):
        if cap < 0:
            raise ValueError("max_candidates must be nonnegative")
        self.threshold = threshold
        self.cap = cap
        self.best = []

    def add_row(self, i, scores, mutual_ranks):
        eligible = np.flatnonzero(scores >= self.threshold)
        for offset in eligible:
            j = i + 1 + int(offset)
            # Player indices follow ascending account names and break score ties.
            entry = -int(mutual_ranks[offset]), float(scores[offset]), -i, -j
            if len(self.best) < self.cap:
                heapq.heappush(self.best, entry)
            elif self.best and entry > self.best[0]:
                heapq.heapreplace(self.best, entry)
        return eligible

    def ordered_pairs(self):
        return [(-i, -j, score) for _, score, i, j in sorted(self.best, reverse=True)]
