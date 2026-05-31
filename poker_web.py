"""
Texas Hold'em — Flask browser UI  (single file)
Install:  pip install flask
Run:      python3 poker_web.py
Open:     http://localhost:5000
"""
from __future__ import annotations

import queue, threading
from collections import Counter
from dataclasses import dataclass, field
from enum import IntEnum
from itertools import combinations
from random import shuffle

from flask import Flask, jsonify, request, Response

# ── Suits & Ranks ─────────────────────────────────────────────────────────────

class Suit(IntEnum):
    CLUBS=0; DIAMONDS=1; HEARTS=2; SPADES=3

    @property
    def symbol(self): return {0:"♣",1:"♦",2:"♥",3:"♠"}[self]

    @property
    def is_red(self): return self in (Suit.DIAMONDS, Suit.HEARTS)


class Rank(IntEnum):
    TWO=2; THREE=3; FOUR=4; FIVE=5; SIX=6; SEVEN=7; EIGHT=8
    NINE=9; TEN=10; JACK=11; QUEEN=12; KING=13; ACE=14

    @property
    def label(self):
        return {2:"2",3:"3",4:"4",5:"5",6:"6",7:"7",8:"8",9:"9",
                10:"T",11:"J",12:"Q",13:"K",14:"A"}[self]


@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit
    def __str__(self): return self.rank.label + self.suit.symbol


class Deck:
    def __init__(self):
        self._cards = [Card(r,s) for s in Suit for r in Rank]
        shuffle(self._cards)

    def draw(self, count=1):
        if count < 1:           raise ValueError("count must be >= 1")
        if count > len(self._cards): raise ValueError("not enough cards")
        return [self._cards.pop() for _ in range(count)]


# ── Player ────────────────────────────────────────────────────────────────────

@dataclass
class Player:
    name: str
    chips: int
    is_human: bool = False
    hole_cards: list = field(default_factory=list)
    current_bet: int = 0
    folded: bool = False

    def reset_for_hand(self):
        self.hole_cards.clear(); self.current_bet = 0; self.folded = False

    def receive(self, cards): self.hole_cards.extend(cards)

    def bet(self, amount):
        if amount < 0: raise ValueError("negative bet")
        wager = min(amount, self.chips)
        self.chips -= wager; self.current_bet += wager
        return wager

    @property
    def active(self): return not self.folded and self.chips > 0


# ── Table ─────────────────────────────────────────────────────────────────────

@dataclass
class Table:
    community_cards: list = field(default_factory=list)
    pot: int = 0

    def reset(self): self.community_cards.clear(); self.pot = 0

    def add_to_pot(self, amount):
        if amount < 0: raise ValueError("negative amount")
        self.pot += amount


# ── Hand Evaluator ────────────────────────────────────────────────────────────

class HandCategory(IntEnum):
    HIGH_CARD=0; ONE_PAIR=1; TWO_PAIR=2; THREE_OF_A_KIND=3
    STRAIGHT=4; FLUSH=5; FULL_HOUSE=6; FOUR_OF_A_KIND=7; STRAIGHT_FLUSH=8


@dataclass(frozen=True, order=True)
class HandRank:
    category: HandCategory
    tiebreakers: tuple

    @property
    def label(self): return self.category.name.replace("_"," ").title()


class HandEvaluator:
    def best_rank(self, cards):
        if len(cards) < 5: raise ValueError("need at least 5 cards")
        return max(self._rank_five(list(c)) for c in combinations(cards, 5))

    def _rank_five(self, cards):
        ranks  = sorted([c.rank for c in cards], reverse=True)
        counts = Counter(ranks)
        groups = sorted(counts.items(), key=lambda x:(x[1],x[0]), reverse=True)
        is_flush = len({c.suit for c in cards}) == 1
        sh = self._straight_high(ranks)

        if is_flush and sh: return HandRank(HandCategory.STRAIGHT_FLUSH, (sh,))
        if groups[0][1]==4: return HandRank(HandCategory.FOUR_OF_A_KIND, (groups[0][0],groups[1][0]))
        if groups[0][1]==3 and groups[1][1]==2:
            return HandRank(HandCategory.FULL_HOUSE, (groups[0][0],groups[1][0]))
        if is_flush: return HandRank(HandCategory.FLUSH, tuple(ranks))
        if sh:       return HandRank(HandCategory.STRAIGHT, (sh,))
        if groups[0][1]==3:
            k = sorted([g[0] for g in groups[1:]], reverse=True)
            return HandRank(HandCategory.THREE_OF_A_KIND, (groups[0][0],)+tuple(k))
        if groups[0][1]==2 and groups[1][1]==2:
            p1,p2 = max(groups[0][0],groups[1][0]), min(groups[0][0],groups[1][0])
            return HandRank(HandCategory.TWO_PAIR, (p1,p2,groups[2][0]))
        if groups[0][1]==2:
            k = sorted([g[0] for g in groups[1:]], reverse=True)
            return HandRank(HandCategory.ONE_PAIR, (groups[0][0],)+tuple(k))
        return HandRank(HandCategory.HIGH_CARD, tuple(ranks))

    def _straight_high(self, ranks):
        u = sorted(set(ranks), reverse=True)
        for i in range(len(u)-4):
            w = u[i:i+5]
            if w[0]-w[4]==4: return w[0]
        if {14,2,3,4,5}.issubset(set(u)): return 5
        return None


# ── Game ──────────────────────────────────────────────────────────────────────

class TexasHoldemGame:
    def __init__(self, players, small_blind=5, big_blind=10, ui=None):
        if len(players) < 2: raise ValueError("need at least 2 players")
        self.players    = players
        self.small_blind = small_blind
        self.big_blind   = big_blind
        self.table      = Table()
        self.evaluator  = HandEvaluator()
        self.ui         = ui

    def play_hand(self):
        deck = Deck()
        self.table.reset()
        for p in self.players: p.reset_for_hand()
        for p in self.players: p.receive(deck.draw(2))
        self._post_blinds();  self.ui.refresh(self)
        self._betting_round()
        self._deal_community(deck, 3, "Flop");   self._betting_round()
        self._deal_community(deck, 1, "Turn");   self._betting_round()
        self._deal_community(deck, 1, "River");  self._betting_round()
        self._showdown();     self.ui.refresh(self)
        self.ui.hand_over()

    def _post_blinds(self):
        s = self.players[0].bet(self.small_blind)
        b = self.players[1].bet(self.big_blind)
        self.table.add_to_pot(s); self.table.add_to_pot(b)
        self.ui.log(f"{self.players[0].name} posts {s}  |  {self.players[1].name} posts {b}")

    def _deal_community(self, deck, count, street):
        if self._one_left(): return
        self.table.community_cards.extend(deck.draw(count))
        self.ui.log(f"── {street} ──"); self.ui.refresh(self)

    def _betting_round(self):
        if self._one_left(): return
        current_bet = max(p.current_bet for p in self.players)
        for player in self.players:
            if player.folded or not player.active: continue
            call_amt = current_bet - player.current_bet
            if player.is_human:
                action = self.ui.ask_action(player, call_amt)
            else:
                action = "fold" if call_amt > player.chips // 2 else "call"
                self.ui.log(f"{player.name} {action}s")

            if action == "fold":
                player.folded = True
            elif action == "call":
                self.table.add_to_pot(player.bet(call_amt))
            elif action == "raise":
                minimum = max(self.big_blind, call_amt + self.big_blind)
                raise_amt = self.ui.ask_raise(minimum, player.chips) if player.is_human \
                            else min(minimum, player.chips)
                self.table.add_to_pot(player.bet(raise_amt))
                current_bet = player.current_bet

            self.ui.refresh(self)
            if self._one_left(): break

        for p in self.players: p.current_bet = 0

    def _showdown(self):
        active = [p for p in self.players if not p.folded]
        if len(active) == 1:
            active[0].chips += self.table.pot
            self.ui.log(f"🏆 {active[0].name} wins {self.table.pot} (last standing)!")
            return
        ranked = [(self.evaluator.best_rank(p.hole_cards + self.table.community_cards), p)
                  for p in active]
        best    = max(r for r,_ in ranked)
        winners = [p for r,p in ranked if r == best]
        share   = self.table.pot // len(winners)
        for w in winners: w.chips += share
        self.ui.log(f"🏆 {' & '.join(w.name for w in winners)} wins {share} — {best.label}!")

    def _one_left(self):
        return sum(1 for p in self.players if not p.folded) == 1


# ── Web UI ────────────────────────────────────────────────────────────────────

_state: dict = {
    "phase": "idle",        # idle | playing | hand_over
    "community_cards": [],
    "pot": 0,
    "players": [],
    "log": [],
    "waiting": False,
    "call_amount": 0,
    "raise_min": 10,
    "raise_max": 1000,
}
_action_q: queue.Queue = queue.Queue()
_raise_q:  queue.Queue = queue.Queue()


class WebUI:
    def __init__(self, game): self._game = game

    def refresh(self, game):
        reveal = _state["phase"] == "hand_over"
        _state["community_cards"] = [str(c) for c in game.table.community_cards]
        _state["pot"]     = game.table.pot
        _state["players"] = [_player_dict(p, reveal) for p in game.players]

    def log(self, msg):
        _state["log"].append(msg)
        _state["log"] = _state["log"][-30:]

    def ask_action(self, player, call_amt):
        _state["waiting"]      = True
        _state["call_amount"]  = call_amt
        action = _action_q.get()          # blocks until browser clicks a button
        _state["waiting"] = False
        return action

    def ask_raise(self, minimum, maximum):
        _state["raise_min"] = minimum
        _state["raise_max"] = maximum
        return _raise_q.get()             # blocks until browser submits amount

    def hand_over(self):
        _state["phase"]   = "hand_over"
        _state["waiting"] = False
        # reveal opponent cards
        self.refresh(self._game)


def _player_dict(p: Player, reveal=False):
    show_cards = p.is_human or reveal
    return {
        "name":       p.name,
        "chips":      p.chips,
        "is_human":   p.is_human,
        "folded":     p.folded,
        "hole_cards": [str(c) for c in p.hole_cards] if show_cards else
                      (["??" for _ in p.hole_cards] if p.hole_cards else []),
    }


# ── Flask ─────────────────────────────────────────────────────────────────────

app = Flask(__name__)
_players = [
    Player("You",       chips=1000, is_human=True),
    Player("Ada Bot",   chips=1000),
    Player("Grace Bot", chips=1000),
]
_game  = None
_web_ui = None


@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")


@app.route("/state")
def state():
    return jsonify(_state)


@app.route("/deal", methods=["POST"])
def deal():
    global _game, _web_ui
    if _state["phase"] == "playing":
        return jsonify({"ok": False})
    _state["log"]     = []
    _state["phase"]   = "playing"
    _state["waiting"] = False
    _state["community_cards"] = []
    _state["pot"]     = 0
    _state["players"] = [_player_dict(p) for p in _players]
    _game   = TexasHoldemGame(_players, ui=_web_ui)
    _web_ui._game = _game
    threading.Thread(target=_game.play_hand, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/action", methods=["POST"])
def action():
    data = request.json or {}
    act  = data.get("action")
    if act == "raise":
        _raise_q.put(int(data.get("amount", _state["raise_min"])))
        _action_q.put("raise")
    elif act in ("fold", "call"):
        _action_q.put(act)
    return jsonify({"ok": True})


# ── HTML (embedded) ───────────────────────────────────────────────────────────

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Texas Hold'em</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #1b4332; color: #f0f0f0;
    font-family: Helvetica, Arial, sans-serif;
    display: flex; flex-direction: column; align-items: center;
    padding: 24px 16px; min-height: 100vh; gap: 12px;
  }
  h1 { color: #ffd700; font-size: 22px; letter-spacing: 2px; }

  /* ── player sections ── */
  .row      { display: flex; gap: 28px; justify-content: center; flex-wrap: wrap; }
  .player   { text-align: center; }
  .pname    { font-weight: bold; font-size: 14px; }
  .pchips   { color: #ffd700; font-size: 13px; margin: 2px 0 4px; }
  .p-cards  { display: flex; gap: 5px; justify-content: center; }

  /* ── cards ── */
  .card {
    width: 46px; height: 66px; border-radius: 6px;
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; font-size: 15px; font-weight: bold;
    line-height: 1.2; border: 1px solid #bbb; background: #fff;
    user-select: none;
  }
  .card.red   { color: #cc2222; }
  .card.black { color: #111; }
  .card.back  { background: #2d6a4f; border-color: #4a9b6f; }
  .card.slot  { background: rgba(255,255,255,.08); border: 1px dashed rgba(255,255,255,.25); }
  .folded-tag { color: #7f8c8d; font-size: 11px; margin-top: 4px; }

  /* ── divider ── */
  hr { width: 100%; max-width: 420px; border: none; border-top: 1px solid #2d6a4f; }

  /* ── pot ── */
  #pot { font-size: 20px; font-weight: bold; color: #ffd700; }

  /* ── log ── */
  #log {
    width: 100%; max-width: 420px; height: 90px; overflow-y: auto;
    background: #163d22; border-radius: 6px; padding: 8px 10px;
    font-family: monospace; font-size: 12px; color: #b0e0b8;
    white-space: pre-wrap;
  }

  /* ── status ── */
  #status { font-size: 13px; color: #a8d5b0; min-height: 18px; }

  /* ── buttons ── */
  .btns { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
  button {
    padding: 10px 24px; font-size: 14px; font-weight: bold;
    border: none; border-radius: 6px; cursor: pointer;
    background: #ffd700; color: #1a1a1a; transition: background .15s;
  }
  button:hover:not(:disabled) { background: #ffe44d; }
  button:disabled { background: #3a5a47; color: #6a8a74; cursor: default; }
  #deal-btn { background: #27ae60; color: #fff; }
  #deal-btn:hover:not(:disabled) { background: #2ecc71; }

  /* ── raise area ── */
  #raise-area {
    display: none; align-items: center; gap: 8px;
    flex-wrap: wrap; justify-content: center;
  }
  #raise-area input {
    width: 90px; padding: 9px; font-size: 14px; text-align: center;
    border: none; border-radius: 6px; background: #fff; color: #111;
  }
</style>
</head>
<body>

<h1>♠ Texas Hold'em ♥</h1>

<div class="row" id="opponents"></div>

<hr>
<div id="pot">Pot: 0</div>
<div class="row" id="community"></div>
<hr>

<div id="log"></div>
<div id="status"></div>

<div class="btns">
  <button id="fold-btn"  disabled onclick="act('fold')">Fold</button>
  <button id="call-btn"  disabled onclick="act('call')">Call</button>
  <button id="raise-btn" disabled onclick="showRaise()">Raise</button>
  <button id="deal-btn"  onclick="deal()">Deal Hand</button>
</div>

<div id="raise-area">
  <input type="number" id="raise-in" min="10" value="10">
  <button onclick="confirmRaise()">Confirm raise</button>
  <button onclick="cancelRaise()" style="background:#555;color:#ddd">Cancel</button>
</div>

<div class="row" id="you"></div>

<script>
const SUITS = {H:'♥',D:'♦',C:'♣',S:'♠'};
let logLen = 0;

function makeCard(code) {
  const el = document.createElement('div');
  if (!code || code === '??') { el.className = 'card back'; return el; }
  const s = code.slice(-1), r = code.slice(0,-1);
  el.className = 'card ' + (s==='H'||s==='D' ? 'red' : 'black');
  el.innerHTML = r + '<br>' + (SUITS[s]||s);
  return el;
}
function makeSlot() {
  const el = document.createElement('div');
  el.className = 'card slot';
  return el;
}

async function poll() {
  try {
    const s = await fetch('/state').then(r=>r.json());
    render(s);
  } catch(_) {}
  setTimeout(poll, 600);
}

function render(s) {
  // pot
  document.getElementById('pot').textContent = 'Pot: ' + s.pot;

  // community (always 5 slots)
  const comm = document.getElementById('community');
  comm.innerHTML = '';
  for (let i=0; i<5; i++)
    comm.appendChild(i < s.community_cards.length ? makeCard(s.community_cards[i]) : makeSlot());

  // opponents
  const opp = document.getElementById('opponents');
  opp.innerHTML = '';
  s.players.filter(p=>!p.is_human).forEach(p => {
    const col = document.createElement('div');
    col.className = 'player';
    col.innerHTML = `<div class="pname">${p.name}</div><div class="pchips">💰 ${p.chips}</div>`;
    const row = document.createElement('div'); row.className = 'p-cards';
    if (p.folded) {
      col.innerHTML += '<div class="folded-tag">folded</div>';
    } else {
      (p.hole_cards.length ? p.hole_cards : ['??','??']).forEach(c => row.appendChild(makeCard(c)));
      col.appendChild(row);
    }
    opp.appendChild(col);
  });

  // human
  const you = document.getElementById('you');
  you.innerHTML = '';
  const human = s.players.find(p=>p.is_human);
  if (human) {
    const col = document.createElement('div'); col.className = 'player';
    col.innerHTML = `<div class="pname">${human.name}</div><div class="pchips">💰 ${human.chips}</div>`;
    const row = document.createElement('div'); row.className = 'p-cards';
    (human.hole_cards.length ? human.hole_cards : []).forEach(c => row.appendChild(makeCard(c)));
    col.appendChild(row);
    you.appendChild(col);
  }

  // log — only append new lines
  const logEl = document.getElementById('log');
  if (s.log.length === 0) { logEl.textContent = ''; logLen = 0; }
  else if (s.log.length > logLen) {
    logEl.textContent += s.log.slice(logLen).join('\n') + '\n';
    logLen = s.log.length;
    logEl.scrollTop = logEl.scrollHeight;
  }

  // buttons
  const waiting = s.waiting && s.phase === 'playing';
  document.getElementById('fold-btn').disabled  = !waiting;
  document.getElementById('raise-btn').disabled = !waiting;
  const cb = document.getElementById('call-btn');
  cb.disabled = !waiting;
  cb.textContent = s.call_amount === 0 ? 'Check' : 'Call ' + s.call_amount;
  const db = document.getElementById('deal-btn');
  db.disabled = s.phase === 'playing';
  db.textContent = s.phase === 'idle' ? 'Deal Hand' : 'New Hand';

  // raise input bounds
  const ri = document.getElementById('raise-in');
  ri.min = s.raise_min; ri.max = s.raise_max;
  if (!ri.value || +ri.value < s.raise_min) ri.value = s.raise_min;

  // status
  const st = document.getElementById('status');
  st.textContent = waiting            ? 'Your turn — choose an action'
                 : s.phase==='hand_over' ? 'Hand over — deal again?'
                 : s.phase==='playing'   ? 'Waiting for bots…'
                 : '';
}

function showRaise()   { document.getElementById('raise-area').style.display='flex'; }
function cancelRaise() { document.getElementById('raise-area').style.display='none'; }
function confirmRaise() {
  const amt = +document.getElementById('raise-in').value;
  cancelRaise();
  fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'raise',amount:amt})});
}
function act(action) {
  fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action})});
}
async function deal() {
  logLen = 0;
  await fetch('/deal',{method:'POST'});
}

poll();
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _web_ui = WebUI(None)
    _game   = TexasHoldemGame(_players, ui=_web_ui)
    _web_ui._game = _game
    _state["players"] = [_player_dict(p) for p in _players]
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, threaded=True, use_reloader=False)
