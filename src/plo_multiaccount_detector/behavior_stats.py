"""Behavioral stat definitions and per-hand sizing observations."""
from bisect import bisect_left
from collections import defaultdict


STREETS = ("FLOP", "TURN", "RIVER")
SIZING_STATS = tuple(
    stat
    for street in STREETS
    for name in (street.lower(),)
    for stat in (
        (f"{name}_small_bet", f"{name}_small_bet", f"{name}_first_bets", f"{street.title()} small bet"),
        (f"{name}_large_bet", f"{name}_large_bet", f"{name}_non_small_bets", f"{street.title()} large | non-small"),
    )
) + (("pot_open", "pot_open", "opens", "Pot-sized open"),)

RFI_STATS = tuple((f"rfi_{pos}", f"rfi_{pos}", f"rfi_{pos}_opps", f"{pos.upper()} RFI")
                  for pos in ("ep", "co", "btn", "sb"))
FREQUENCY_STATS = (
    ("flop_cbet", "flop_cbet", "flop_cbet_opps", "Flop c-bet"),
    ("fold_to_flop_cbet", "fold_to_flop_cbet", "fold_to_flop_cbet_opps", "Fold to flop c-bet"),
    ("fold_to_3bet", "fold_to_3bet", "fold_to_3bet_opps", "Fold to 3Bet"),
    ("flop_check_raise", "flop_check_raise", "flop_check_raise_opps", "Flop check-raise"),
)
GROUPS = {"bet_sizing": SIZING_STATS, "positional_rfi": RFI_STATS, "postflop_frequency": FREQUENCY_STATS}
EXTRA_STATS = tuple(stat for group in GROUPS.values() for stat in group)
EXTRA_FIELDS = tuple(dict.fromkeys(field for _, success, trials, _ in EXTRA_STATS for field in (success, trials)))
SIZING_EDGES = (.10, .20, .30, .40, .50, .60, .70, .75, .80, .90, 1.0, 1.25, 1.5, 2.0)
WAGERS = {"post_small_blind", "post_big_blind", "call", "bet", "raise", "return_uncalled"}
FORCED_POT_ONLY = {"post_dead_blind", "post_ante"}


def stat_specs(groups=None):
    from .likelihood import STATS

    return [*STATS, *(stat[:3] for group, stats in GROUPS.items()
                      if groups is None or groups.get(group, False) for stat in stats)]


def pot_before_actions(hand):
    """Yield each action with the prior pot, amount to call and incremental chips."""
    pot = 0.0
    street = None
    committed = {}
    for action in hand.actions:
        if action.street != street:
            street = action.street
            committed.clear()
        previous = committed.get(action.player, 0.0)
        to_call = max(0.0, max(committed.values(), default=0.0) - previous)
        amount = action.amount if action.action in WAGERS or action.action in FORCED_POT_ONLY else 0.0
        if hand.source_format == "text" and action.action == "raise" and action.to_amount is not None:
            amount = max(0.0, action.to_amount - previous)
        yield action, pot, to_call, amount
        pot += amount
        if action.action in WAGERS:
            committed[action.player] = previous + amount


def sizing_events(hand, players, events, histogram):
    first_bets = set()
    raised = False
    for action, pot, to_call, amount in pot_before_actions(hand):
        street, player, kind = action.street, action.player, action.action
        if player not in players:
            continue
        if street == "PREFLOP" and kind in {"raise", "bet"} and not raised:
            raised = True
            maximum = pot + 2 * to_call
            if not action.all_in and maximum > 0 and amount > 0:
                events[player].add("opens")
                if amount + 1e-9 >= .95 * maximum:
                    events[player].add("pot_open")
        elif street in STREETS and kind == "bet" and street not in first_bets:
            first_bets.add(street)
            if action.all_in or pot <= 0 or amount <= 0:
                continue
            prefix = street.lower()
            fraction = round(amount / pot, 12)
            histogram[street][bisect_left(SIZING_EDGES, fraction)] += 1
            events[player].add(f"{prefix}_first_bets")
            if fraction <= .40:
                events[player].add(f"{prefix}_small_bet")
            else:
                events[player].add(f"{prefix}_non_small_bets")
                if fraction > .75:
                    events[player].add(f"{prefix}_large_bet")


DECISIONS = {"fold", "check", "call", "bet", "raise"}
AGGRESSIVE = {"bet", "raise"}


def rfi_positions(hand, players):
    if hand.button_seat not in hand.seats or len(players) < 2:
        return {}
    button = hand.seats[hand.button_seat].player
    if button not in players:
        return {}
    if len(players) == 2:
        return {button: "sb"}
    seats = sorted(hand.seats.values(), key=lambda seat: (seat.seat_no <= hand.button_seat, seat.seat_no))
    order = [seat.player for seat in seats if seat.player in players]
    positions = {order[0]: "sb", order[-1]: "btn"}
    if len(order) >= 4:
        positions[order[-2]] = "co"
        positions.update((player, "ep") for player in order[2:-2])
    return positions


def preflop_frequencies(hand, players, events):
    positions = rfi_positions(hand, players)
    voluntary = False
    raises = 0
    opener = last_raiser = None
    for action in hand.actions:
        if action.street != "PREFLOP":
            break
        player, kind = action.player, action.action
        if player not in players or kind not in DECISIONS:
            continue
        position = positions.get(player)
        if not voluntary and position and kind != "check":
            events[player].add(f"rfi_{position}_opps")
            if kind in AGGRESSIVE:
                events[player].add(f"rfi_{position}")
        if raises == 2 and player == opener and kind != "check":
            events[player].add("fold_to_3bet_opps")
            if kind == "fold":
                events[player].add("fold_to_3bet")
        if kind in AGGRESSIVE:
            if raises == 0:
                opener = player
            last_raiser = player
            raises += 1
        voluntary |= kind in {"call", "bet", "raise"}
    return last_raiser


def flop_frequencies(hand, players, last_raiser, events):
    checked = set()
    bettor = None
    raised = False
    for action in hand.actions:
        if action.street != "FLOP":
            continue
        player, kind = action.player, action.action
        if player not in players or kind not in DECISIONS:
            continue
        if bettor is None:
            if player == last_raiser and kind in {"check", "bet"}:
                events[player].add("flop_cbet_opps")
                if kind == "bet":
                    events[player].add("flop_cbet")
            if kind == "check":
                checked.add(player)
            elif kind == "bet":
                bettor = player
        elif not raised and player != bettor and kind in {"fold", "call", "raise"}:
            if bettor == last_raiser:
                events[player].add("fold_to_flop_cbet_opps")
                if kind == "fold":
                    events[player].add("fold_to_flop_cbet")
            if player in checked:
                events[player].add("flop_check_raise_opps")
                if kind == "raise":
                    events[player].add("flop_check_raise")
            raised = kind == "raise"


def behavior_events(hand, players, histogram):
    events = defaultdict(set)
    sizing_events(hand, players, events, histogram)
    last_raiser = preflop_frequencies(hand, players, events)
    flop_frequencies(hand, players, last_raiser, events)
    return events


def sizing_distribution(histogram):
    return {
        "upper_edges_inclusive": [*SIZING_EDGES, None],
        "counts_by_street": {street.lower(): [histogram[street].get(i, 0)
                                            for i in range(len(SIZING_EDGES) + 1)] for street in STREETS},
    }
