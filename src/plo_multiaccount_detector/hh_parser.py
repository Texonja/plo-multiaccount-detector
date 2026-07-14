"""Parsers for HM2-stored PLO hand histories.

v1 supports two formats found in HM2 backups:
- text hand histories such as WPN/ACR style;
- iPoker XML hand histories.

The detector uses a common ParsedHand model after parsing, so site-specific
format quirks stay inside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import html
import xml.etree.ElementTree as ET
from typing import Iterable


MONEY_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
HEADER_RE = re.compile(
    r"^Hand #(?P<hand_no>\d+) - (?P<game>.+?) - \$(?P<sb>[0-9]+(?:\.[0-9]+)?)/\$(?P<bb>[0-9]+(?:\.[0-9]+)?) - (?P<dt>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) UTC"
)
TABLE_RE = re.compile(r"^(?P<table>.+?)\s+(?P<max_players>\d+)-max Seat #(?P<button_seat>\d+) is the button$")
SEAT_RE = re.compile(r"^Seat (?P<seat>\d+): (?P<player>.+?) \(\$(?P<stack>[0-9]+(?:\.[0-9]+)?)\)(?P<tail>.*)$")
DEALT_RE = re.compile(r"^Dealt to (?P<player>.+?) \[(?P<cards>[^\]]+)\]")
SHOWS_RE = re.compile(r"^(?P<player>.+?) shows \[(?P<cards>[^\]]+)\]")
SUMMARY_SEAT_RE = re.compile(r"^Seat (?P<seat>\d+): (?P<player>.+?) (?P<desc>.+)$")
UNCALLED_RE = re.compile(r"^Uncalled bet \(\$(?P<amount>[0-9]+(?:\.[0-9]+)?)\) returned to (?P<player>.+)$")


@dataclass
class Seat:
    seat_no: int
    player: str
    stack: float
    sitting_out: bool = False
    waiting: bool = False


@dataclass
class Action:
    player: str
    street: str
    action: str
    amount: float = 0.0
    to_amount: float | None = None
    raw: str = ""


@dataclass
class ParsedHand:
    hand_id: int
    table_name: str
    timestamp: datetime | None
    small_blind: float
    big_blind: float
    max_players: int | None = None
    button_seat: int | None = None
    seats: dict[int, Seat] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    dealt_cards: dict[str, str] = field(default_factory=dict)
    shown_cards: dict[str, str] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    winnings: dict[str, float] = field(default_factory=dict)
    total_pot: float | None = None
    rake: float | None = None
    is_bomb_pot: bool = False
    is_run_it_twice: bool = False
    raw_text: str = ""
    source_format: str = "unknown"

    @property
    def active_players(self) -> set[str]:
        return {s.player for s in self.seats.values() if not s.sitting_out and not s.waiting}

    def net_by_player(self) -> dict[str, float]:
        players = set(self.active_players) | set(self.contributions) | set(self.winnings)
        return {p: self.winnings.get(p, 0.0) - self.contributions.get(p, 0.0) for p in players}


class HandParseError(ValueError):
    pass


def _money_first(line: str) -> float | None:
    m = MONEY_RE.search(line)
    return float(m.group(1)) if m else None


def parse_money(value: str | None) -> float:
    """Parse HM2/iPoker money strings: €1.260,13, €0,50, $0.25, 20,00."""
    if value is None:
        return 0.0
    s = value.strip()
    if not s:
        return 0.0
    s = re.sub(r"[^0-9,\.\-]", "", s)
    if not s or s in {"-", ",", "."}:
        return 0.0
    if "," in s and "." in s:
        # European format with thousands dot and decimal comma.
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_datetime(value: str) -> datetime | None:
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _add_amount(dct: dict[str, float], player: str, amount: float) -> None:
    dct[player] = dct.get(player, 0.0) + amount


def _extract_won_amount(desc: str) -> float:
    total = 0.0
    for m in re.finditer(r"won \$([0-9]+(?:\.[0-9]+)?)", desc):
        total += float(m.group(1))
    return total


def _extract_summary_player(desc_player: str) -> str:
    markers = [" folded", " showed", " did not show", " mucked", " collected", " won", " lost"]
    best_idx = None
    for marker in markers:
        idx = desc_player.find(marker)
        if idx != -1 and (best_idx is None or idx < best_idx):
            best_idx = idx
    if best_idx is None:
        return desc_player.strip()
    name = desc_player[:best_idx].strip()
    name = re.sub(r"\s+\((button|small blind|big blind)\)$", "", name).strip()
    return name


def _action_player(line: str, verbs: Iterable[str]) -> tuple[str, str] | None:
    for verb in verbs:
        token = f" {verb}"
        idx = line.find(token)
        if idx > 0:
            return line[:idx], verb
    return None


def parse_text_hand_history(raw_text: str, *, fallback_hand_id: int | None = None) -> ParsedHand:
    lines = [ln.strip() for ln in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    if not lines:
        raise HandParseError("Empty hand history")

    header = HEADER_RE.match(lines[0])
    if not header:
        raise HandParseError(f"Unsupported or unrecognized text header: {lines[0][:120]}")

    hand_id = int(header.group("hand_no")) if header.group("hand_no") else int(fallback_hand_id or 0)
    hand = ParsedHand(
        hand_id=hand_id,
        table_name="",
        timestamp=_parse_datetime(header.group("dt")),
        small_blind=float(header.group("sb")),
        big_blind=float(header.group("bb")),
        raw_text=raw_text,
        source_format="text",
    )

    current_street = "PREFLOP"
    in_summary = False

    for line in lines[1:]:
        if line == "*** HOLE CARDS ***":
            current_street = "PREFLOP"
            continue
        if line.startswith("*** FLOP"):
            current_street = "FLOP"
            cards = re.findall(r"\[([^\]]+)\]", line)
            if cards:
                hand.board = cards[-1].split()
            continue
        if line.startswith("*** TURN"):
            current_street = "TURN"
            cards = re.findall(r"\[([^\]]+)\]", line)
            if cards:
                hand.board = cards[-1].split()
            continue
        if line.startswith("*** RIVER"):
            current_street = "RIVER"
            cards = re.findall(r"\[([^\]]+)\]", line)
            if cards:
                hand.board = cards[-1].split()
            continue
        if line.startswith("*** SHOW DOWN"):
            current_street = "SHOWDOWN"
            continue
        if line == "*** RUN IT TWICE ***":
            hand.is_run_it_twice = True
            continue
        if line == "*** SUMMARY ***":
            in_summary = True
            current_street = "SUMMARY"
            continue

        table_match = TABLE_RE.match(line)
        if table_match:
            hand.table_name = table_match.group("table")
            hand.max_players = int(table_match.group("max_players"))
            hand.button_seat = int(table_match.group("button_seat"))
            continue

        seat_match = SEAT_RE.match(line)
        if seat_match and not in_summary:
            tail = seat_match.group("tail") or ""
            hand.seats[int(seat_match.group("seat"))] = Seat(
                seat_no=int(seat_match.group("seat")),
                player=seat_match.group("player"),
                stack=float(seat_match.group("stack")),
                sitting_out="sitting out" in tail,
            )
            continue

        if line.endswith(" waits for big blind"):
            player = line[: -len(" waits for big blind")]
            for seat in hand.seats.values():
                if seat.player == player:
                    seat.waiting = True
                    break
            continue

        if line == "BombPot":
            hand.is_bomb_pot = True
            continue

        if line.startswith("Total pot"):
            m = re.search(r"Total pot \$([0-9]+(?:\.[0-9]+)?)", line)
            if m:
                hand.total_pot = float(m.group(1))
            r = re.search(r"Rake \$([0-9]+(?:\.[0-9]+)?)", line)
            if r:
                hand.rake = float(r.group(1))
            continue

        dealt = DEALT_RE.match(line)
        if dealt:
            hand.dealt_cards[dealt.group("player")] = dealt.group("cards")
            continue

        shows = SHOWS_RE.match(line)
        if shows:
            hand.shown_cards[shows.group("player")] = shows.group("cards")
            hand.actions.append(Action(shows.group("player"), current_street, "show", raw=line))
            continue

        uncalled = UNCALLED_RE.match(line)
        if uncalled:
            player = uncalled.group("player")
            amount = float(uncalled.group("amount"))
            _add_amount(hand.contributions, player, -amount)
            hand.actions.append(Action(player, current_street, "return_uncalled", amount=-amount, raw=line))
            continue

        if in_summary:
            sm = SUMMARY_SEAT_RE.match(line)
            if sm:
                player_part = sm.group("player") + " " + sm.group("desc")
                player = _extract_summary_player(player_part)
                amount = _extract_won_amount(player_part)
                if amount:
                    _add_amount(hand.winnings, player, amount)
            continue

        for suffix, action_name in (
            (" posts the small blind", "post_small_blind"),
            (" posts the big blind", "post_big_blind"),
            (" posts ante", "post_ante"),
            (" posts dead blind", "post_dead_blind"),
        ):
            idx = line.find(suffix)
            if idx > 0:
                player = line[:idx]
                amount = _money_first(line)
                if amount is not None:
                    _add_amount(hand.contributions, player, amount)
                    hand.actions.append(Action(player, "PREFLOP", action_name, amount=amount, raw=line))
                break
        else:
            parsed = _action_player(line, ["folds", "checks", "calls", "bets", "raises"])
            if parsed:
                player, verb = parsed
                if verb == "folds":
                    hand.actions.append(Action(player, current_street, "fold", raw=line))
                elif verb == "checks":
                    hand.actions.append(Action(player, current_street, "check", raw=line))
                elif verb == "calls":
                    amount = _money_first(line) or 0.0
                    _add_amount(hand.contributions, player, amount)
                    hand.actions.append(Action(player, current_street, "call", amount=amount, raw=line))
                elif verb == "bets":
                    amount = _money_first(line) or 0.0
                    _add_amount(hand.contributions, player, amount)
                    hand.actions.append(Action(player, current_street, "bet", amount=amount, raw=line))
                elif verb == "raises":
                    amounts = MONEY_RE.findall(line)
                    amount = float(amounts[0]) if amounts else 0.0
                    to_amount = float(amounts[1]) if len(amounts) > 1 else None
                    _add_amount(hand.contributions, player, amount)
                    hand.actions.append(Action(player, current_street, "raise", amount=amount, to_amount=to_amount, raw=line))

    if not hand.table_name:
        hand.table_name = "UNKNOWN"
    return hand


def _child_text(parent: ET.Element, path: str, default: str = "") -> str:
    el = parent.find(path)
    return el.text.strip() if el is not None and el.text else default


def _card_text_to_space(cards: str) -> str:
    return " ".join(cards.split())



_ATTR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')
_ROUND_RE = re.compile(r'<round\s+no="([^"]+)">(.*?)</round>', re.S)
_NODE_RE = re.compile(r'<action\s+([^>]*)/>|<cards\s+([^>]*)>(.*?)</cards>', re.S)


def _attrs(attr_text: str | None) -> dict[str, str]:
    if not attr_text:
        return {}
    return {m.group(1): html.unescape(m.group(2)) for m in _ATTR_RE.finditer(attr_text)}


def _tag_text(raw_text: str, tag: str, default: str = "") -> str:
    m = re.search(rf'<{tag}>(.*?)</{tag}>', raw_text, re.S)
    return html.unescape(m.group(1).strip()) if m else default


def parse_ipoker_xml_hand_history_fast(raw_text: str, *, fallback_hand_id: int | None = None) -> ParsedHand:
    """Fast regex parser for HM2 iPoker XML fragments.

    HM2 stores many iPoker rows as XML fragments without a closing </session>.
    ElementTree is unnecessarily slow for hundreds of thousands of rows, and
    would need fragment repair anyway. This parser extracts only the fields the
    detector needs.
    """
    m_game = re.search(r'<game\s+gamecode="(\d+)"', raw_text)
    if not m_game:
        raise HandParseError("iPoker XML has no gamecode")
    hand_id = int(m_game.group(1) or fallback_hand_id or 0)
    table_name = _tag_text(raw_text, "tablename", "UNKNOWN")
    sb = parse_money(_tag_text(raw_text, "smallblind", "0"))
    bb = parse_money(_tag_text(raw_text, "bigblind", "1")) or 1.0
    max_text = _tag_text(raw_text, "tablesize", "")
    max_players = int(max_text) if max_text.isdigit() else None

    # Startdate inside the <game><general> block is the hand timestamp. The
    # session startdate appears earlier, so look after <game gamecode=...>.
    ts = None
    after_game = raw_text[m_game.end():]
    m_ts = re.search(r'<startdate>(.*?)</startdate>', after_game, re.S)
    if m_ts:
        ts = _parse_datetime(html.unescape(m_ts.group(1).strip()))

    hand = ParsedHand(
        hand_id=hand_id,
        table_name=table_name,
        timestamp=ts,
        small_blind=sb,
        big_blind=bb,
        max_players=max_players,
        raw_text=raw_text,
        source_format="ipoker_xml",
    )

    # Players in the game block only. In these rows player tags appear only
    # inside <players>, so a global regex is sufficient and much faster.
    for m in re.finditer(r'<player\s+([^>]*)/>', raw_text):
        a = _attrs(m.group(1))
        name = a.get("name", "").strip()
        if not name:
            continue
        seat_no = int(a.get("seat") or 0)
        stack = parse_money(a.get("chips"))
        hand.seats[seat_no] = Seat(seat_no=seat_no, player=name, stack=stack)
        if a.get("dealer") == "1":
            hand.button_seat = seat_no
        bet = parse_money(a.get("bet"))
        win = parse_money(a.get("win"))
        if bet:
            hand.contributions[name] = bet
        if win:
            # Net proxy convention: winners get +win, losers keep -bet.
            hand.winnings[name] = bet + win

    street_by_round = {"0": "PREFLOP", "1": "PREFLOP", "2": "FLOP", "3": "TURN", "4": "RIVER"}
    street_contrib: dict[str, float] = {}
    for rnd_no, body in _ROUND_RE.findall(raw_text):
        street = street_by_round.get(rnd_no, f"ROUND_{rnd_no}")
        if rnd_no not in {"0", "1"}:
            street_contrib = {}
        for n in _NODE_RE.finditer(body):
            if n.group(1) is not None:  # action
                a = _attrs(n.group(1))
                player = a.get("player", "").strip()
                if not player:
                    continue
                typ = a.get("type", "")
                amount_raw = parse_money(a.get("sum"))
                raw = n.group(0).strip()
                if typ == "0":
                    hand.actions.append(Action(player, street, "fold", amount=0.0, raw=raw))
                elif typ == "1":
                    hand.actions.append(Action(player, "PREFLOP", "post_small_blind", amount=amount_raw, raw=raw))
                    street_contrib[player] = street_contrib.get(player, 0.0) + amount_raw
                elif typ == "2":
                    hand.actions.append(Action(player, "PREFLOP", "post_big_blind", amount=amount_raw, raw=raw))
                    street_contrib[player] = street_contrib.get(player, 0.0) + amount_raw
                elif typ == "3":
                    hand.actions.append(Action(player, street, "call", amount=amount_raw, raw=raw))
                    street_contrib[player] = street_contrib.get(player, 0.0) + amount_raw
                elif typ == "4":
                    hand.actions.append(Action(player, street, "check", amount=0.0, raw=raw))
                elif typ == "5":
                    hand.actions.append(Action(player, street, "bet", amount=amount_raw, raw=raw))
                    street_contrib[player] = street_contrib.get(player, 0.0) + amount_raw
                elif typ in {"7", "23"}:
                    prev = street_contrib.get(player, 0.0)
                    delta = max(0.0, amount_raw - prev)
                    hand.actions.append(Action(player, street, "raise", amount=delta, to_amount=amount_raw, raw=raw))
                    street_contrib[player] = max(prev, amount_raw)
                else:
                    hand.actions.append(Action(player, street, f"unknown_{typ}", amount=amount_raw, raw=raw))
            else:  # cards
                a = _attrs(n.group(2))
                ctype = a.get("type", "")
                player = a.get("player")
                cards = _card_text_to_space(html.unescape(n.group(3) or ""))
                if ctype == "Pocket" and player:
                    hand.dealt_cards[player] = cards
                elif ctype in {"Flop", "Turn", "River"}:
                    hand.board.extend(cards.split())

    if hand.contributions:
        hand.total_pot = sum(hand.contributions.values())
    return hand


def parse_ipoker_xml_hand_history(raw_text: str, *, fallback_hand_id: int | None = None) -> ParsedHand:
    xml_text = raw_text.strip()
    # HM2 sometimes stores iPoker rows as a session fragment ending after </game>
    # without the final </session>. Close it before ElementTree parsing.
    if xml_text.startswith("<?xml") and "<session" in xml_text and "</session>" not in xml_text:
        xml_text += "\n</session>"
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise HandParseError(f"Invalid iPoker XML: {exc}") from exc

    game = root.find("game")
    if game is None:
        raise HandParseError("iPoker XML has no <game> node")

    session_general = root.find("general")
    if session_general is None:
        raise HandParseError("iPoker XML has no session <general> node")

    game_general = game.find("general")
    if game_general is None:
        raise HandParseError("iPoker XML game has no <general> node")

    hand_id = int(game.attrib.get("gamecode") or fallback_hand_id or 0)
    table_name = _child_text(session_general, "tablename", "UNKNOWN")
    sb = parse_money(_child_text(session_general, "smallblind", "0"))
    bb = parse_money(_child_text(session_general, "bigblind", "1")) or 1.0
    timestamp = _parse_datetime(_child_text(game_general, "startdate", ""))
    max_players_text = _child_text(session_general, "tablesize", "")
    max_players = int(max_players_text) if max_players_text.isdigit() else None

    hand = ParsedHand(
        hand_id=hand_id,
        table_name=table_name,
        timestamp=timestamp,
        small_blind=sb,
        big_blind=bb,
        max_players=max_players,
        raw_text=raw_text,
        source_format="ipoker_xml",
    )

    players_el = game_general.find("players")
    if players_el is not None:
        for p in players_el.findall("player"):
            name = p.attrib.get("name", "").strip()
            if not name:
                continue
            seat_no = int(p.attrib.get("seat") or 0)
            stack = parse_money(p.attrib.get("chips"))
            hand.seats[seat_no] = Seat(seat_no=seat_no, player=name, stack=stack)
            if p.attrib.get("dealer") == "1":
                hand.button_seat = seat_no

            # HM2 iPoker XML stores per-hand player bet/win attributes. `bet`
            # works well as money at risk. `win` is a useful result proxy, but
            # not always a perfect gross-pot reconstruction when uncalled bets
            # are involved, so reports label this as net proxy.
            bet = parse_money(p.attrib.get("bet"))
            win = parse_money(p.attrib.get("win"))
            if bet:
                hand.contributions[name] = bet
            if win:
                hand.winnings[name] = bet + win

    street_by_round = {"0": "PREFLOP", "1": "PREFLOP", "2": "FLOP", "3": "TURN", "4": "RIVER"}
    current_street_contrib: dict[str, float] = {}
    for rnd in game.findall("round"):
        no = rnd.attrib.get("no", "")
        street = street_by_round.get(no, f"ROUND_{no}")
        current_street_contrib = {}
        for node in list(rnd):
            if node.tag == "cards":
                ctype = node.attrib.get("type", "")
                cards = _card_text_to_space(node.text or "")
                player = node.attrib.get("player")
                if ctype == "Pocket" and player:
                    if "X" not in cards.split():
                        hand.dealt_cards[player] = cards
                    elif player not in hand.dealt_cards:
                        hand.dealt_cards[player] = cards
                elif ctype in {"Flop", "Turn", "River"}:
                    hand.board.extend(cards.split())
                continue

            if node.tag != "action":
                continue
            player = node.attrib.get("player", "").strip()
            if not player:
                continue
            typ = node.attrib.get("type", "")
            amount_raw = parse_money(node.attrib.get("sum"))
            raw = ET.tostring(node, encoding="unicode").strip()

            if typ == "0":
                hand.actions.append(Action(player, street, "fold", amount=0.0, raw=raw))
            elif typ == "1":
                hand.actions.append(Action(player, "PREFLOP", "post_small_blind", amount=amount_raw, raw=raw))
            elif typ == "2":
                hand.actions.append(Action(player, "PREFLOP", "post_big_blind", amount=amount_raw, raw=raw))
            elif typ == "3":
                # Call amount is incremental in iPoker XML examples.
                hand.actions.append(Action(player, street, "call", amount=amount_raw, raw=raw))
                current_street_contrib[player] = current_street_contrib.get(player, 0.0) + amount_raw
            elif typ == "4":
                hand.actions.append(Action(player, street, "check", amount=0.0, raw=raw))
            elif typ == "5":
                hand.actions.append(Action(player, street, "bet", amount=amount_raw, raw=raw))
                current_street_contrib[player] = current_street_contrib.get(player, 0.0) + amount_raw
            elif typ in {"7", "23"}:
                # Raise `sum` is usually total amount for that street; use delta
                # as amount, keep total in to_amount.
                prev = current_street_contrib.get(player, 0.0)
                delta = max(0.0, amount_raw - prev)
                hand.actions.append(Action(player, street, "raise", amount=delta, to_amount=amount_raw, raw=raw))
                current_street_contrib[player] = max(current_street_contrib.get(player, 0.0), amount_raw)
            else:
                # Unknown iPoker type: keep it out of relationship stats, but
                # preserve raw action for debugging.
                hand.actions.append(Action(player, street, f"unknown_{typ}", amount=amount_raw, raw=raw))

    if hand.contributions:
        hand.total_pot = sum(hand.contributions.values())
    return hand


def parse_hand_history(raw_text: str, *, fallback_hand_id: int | None = None) -> ParsedHand:
    stripped = raw_text.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<session"):
        return parse_ipoker_xml_hand_history_fast(raw_text, fallback_hand_id=fallback_hand_id)
    return parse_text_hand_history(raw_text, fallback_hand_id=fallback_hand_id)
