"""Packed per-account stat increments for post-parse validation splits."""
from array import array

import numpy as np


CORE_FIELDS = (
    "vpip", "pfr", "threebet", "threebet_opportunities",
    "saw_flop", "went_to_showdown", "won_at_showdown",
)
CORE_FLAGS = {field: 1 << index for index, field in enumerate(CORE_FIELDS)}


class HandSample:
    def __init__(self):
        # Triples of signed 64-bit integers: timestamp, hand ID, increment flags.
        self.records = {}
        self.undated = 0

    def add(self, player, timestamp, hand_id, flags):
        self.records.setdefault(player, array("q")).extend((timestamp, hand_id, flags))
        self.undated += timestamp == 0

    def halves(self, player):
        records = np.frombuffer(self.records[player], dtype=np.int64).reshape(-1, 3)
        timestamps, hand_ids, flags = records.T
        odd = hand_ids % 2 == 1
        dated = np.flatnonzero(timestamps)
        order = dated[np.lexsort((hand_ids[dated], timestamps[dated]))]
        midpoint = len(order) // 2
        return {
            "chronological": (flags[order[:midpoint]], flags[order[midpoint:]]),
            "parity": (flags[~odd], flags[odd]),
        }


def timestamp_key(timestamp):
    if timestamp is None:
        return 0
    return (((timestamp.toordinal() * 24 + timestamp.hour) * 60 + timestamp.minute)
            * 60 + timestamp.second) * 1_000_000 + timestamp.microsecond
