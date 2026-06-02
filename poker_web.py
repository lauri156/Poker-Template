from __future__ import annotations

import queue
import threading

from flask import Flask, jsonify, request, Response

from cards import Card, Deck, Rank, Suit
from player import Player
from table import Table
from evaluator import HandEvaluator, HandCategory, HandRank
from game import TexasHoldemGame

_state: dict = {
    "phase": "idle",
    "community_cards": [],
    "pot": 0,
    "players": [],
    "log": [],
    "waiting": False,
    "call_amount": 0,
    "raise_min": 10,
    "raise_max": 1000,
    "win_prob": [],
}
_action_q: queue.Queue = queue.Queue()
_raise_q:  queue.Queue = queue.Queue()

class WebUI:
    def __init__(self, game):
        self._game = game

    def show_message(self, msg: str) -> None:
        _state["log"].append(msg)
        _state["log"] = _state["log"][-30:]

    def show_table(self, community_cards, pot: int) -> None:
        if self._game:
            _state["community_cards"] = [str(c) for c in community_cards]
            _state["pot"] = pot
            _state["players"] = [_player_dict(p) for p in self._game.players]

            num_cards = len(community_cards)
            street = {0: "Pre-Flop", 3: "Flop", 4: "Turn", 5: "River"}.get(num_cards)
            if street:
                self._update_win_prob(street)

    def ask_action(self, player, call_amt: int) -> str:
        _state["waiting"]     = True
        _state["call_amount"] = call_amt
        action = _action_q.get()
        _state["waiting"] = False
        return action

    def ask_raise_amount(self, minimum: int, maximum: int) -> int:
        _state["raise_min"] = minimum
        _state["raise_max"] = maximum
        return _raise_q.get()

    def format_cards(self, cards) -> str:
        return " ".join(str(c) for c in cards)

    def refresh(self, game) -> None:
        reveal = _state["phase"] == "hand_over"
        _state["community_cards"] = [str(c) for c in game.table.community_cards]
        _state["pot"]     = game.table.pot
        _state["players"] = [_player_dict(p, reveal) for p in game.players]

    def hand_over(self) -> None:
        _state["phase"]   = "hand_over"
        _state["waiting"] = False
        if self._game:
            self.refresh(self._game)

    def _update_win_prob(self, street: str) -> None:
        human = next((p for p in self._game.players if p.is_human), None)
        if not human or not human.hole_cards:
            return
        num_opponents = sum(1 for p in self._game.players if not p.is_human and not p.folded)
        if num_opponents == 0:
            prob = 1.0
        else:
            prob = self._game.evaluator.monteCarlo(
                human.hole_cards,
                self._game.table.community_cards,
                num_opponents,
                simulations=500,
            )
        _state["win_prob"].append({"street": street, "prob": round(prob * 100, 1)})

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

app = Flask(__name__)
_players = [
    Player("You",       chips=1000, is_human=True),
    Player("Bot 1",   chips=1000),
    Player("Bot 2", chips=1000),
]
_game   = None
_web_ui = None

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/state")
def state():
    return jsonify(_state)

@app.route("/winprob")
def winprob():
    return jsonify(_state["win_prob"])

@app.route("/deal", methods=["POST"])
def deal():
    global _game, _web_ui
    if _state["phase"] == "playing":
        return jsonify({"ok": False})
    _state["log"]             = []
    _state["win_prob"]        = []
    _state["phase"]           = "playing"
    _state["waiting"]         = False
    _state["community_cards"] = []
    _state["pot"]             = 0
    _state["players"]         = [_player_dict(p) for p in _players]
    _game = TexasHoldemGame(_players, ui=_web_ui)
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
  .row      { display: flex; gap: 28px; justify-content: center; flex-wrap: wrap; }
  .player   { text-align: center; }
  .pname    { font-weight: bold; font-size: 14px; }
  .pchips   { color: #ffd700; font-size: 13px; margin: 2px 0 4px; }
  .p-cards  { display: flex; gap: 5px; justify-content: center; }
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
  hr { width: 100%; max-width: 420px; border: none; border-top: 1px solid #2d6a4f; }
  #pot { font-size: 20px; font-weight: bold; color: #ffd700; }
  #log {
    width: 100%; max-width: 420px; height: 90px; overflow-y: auto;
    background: #163d22; border-radius: 6px; padding: 8px 10px;
    font-family: monospace; font-size: 12px; color: #b0e0b8; white-space: pre-wrap;
  }
  #status { font-size: 13px; color: #a8d5b0; min-height: 18px; }
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

<canvas id="win-chart" style="max-width:420px;width:100%;margin-top:8px"></canvas>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const SUITS = {H:'♥',D:'♦',C:'♣',S:'♠'};
let logLen = 0;

const chart = new Chart(document.getElementById('win-chart'), {
  type: 'line',
  data: {
    labels: [],
    datasets: [{
      label: 'Win probability (%)',
      data: [],
      borderColor: '#ffd700',
      backgroundColor: 'rgba(255,215,0,0.1)',
      pointBackgroundColor: '#ffd700',
      tension: 0.3,
      fill: true,
    }]
  },
  options: {
    scales: {
      y: { min: 0, max: 100, ticks: { color: '#b0e0b8' }, grid: { color: '#2d6a4f' } },
      x: { ticks: { color: '#b0e0b8' }, grid: { color: '#2d6a4f' } }
    },
    plugins: { legend: { labels: { color: '#f0f0f0' } } },
    backgroundColor: 'transparent',
  }
});

async function updateChart() {
  const data = await fetch('/winprob').then(r => r.json());
  chart.data.labels   = data.map(d => d.street);
  chart.data.datasets[0].data = data.map(d => d.prob);
  chart.update();
}

function makeCard(code) {
  const el = document.createElement('div');
  if (!code || code === '??') { el.className = 'card back'; return el; }
  const s = code.slice(-1), r = code.slice(0,-1);
  el.className = 'card ' + (s==='H'||s==='D' ? 'red' : 'black');
  el.innerHTML = r + '<br>' + (SUITS[s]||s);
  return el;
}
function makeSlot() {
  const el = document.createElement('div'); el.className = 'card slot'; return el;
}

async function poll() {
  try { const s = await fetch('/state').then(r=>r.json()); render(s); updateChart(); } catch(_) {}
  setTimeout(poll, 600);
}

function render(s) {
  document.getElementById('pot').textContent = 'Pot: ' + s.pot;
  const comm = document.getElementById('community');
  comm.innerHTML = '';
  for (let i=0; i<5; i++)
    comm.appendChild(i < s.community_cards.length ? makeCard(s.community_cards[i]) : makeSlot());
  const opp = document.getElementById('opponents');
  opp.innerHTML = '';
  s.players.filter(p=>!p.is_human).forEach(p => {
    const col = document.createElement('div'); col.className = 'player';
    col.innerHTML = `<div class="pname">${p.name}</div><div class="pchips">💰 ${p.chips}</div>`;
    const row = document.createElement('div'); row.className = 'p-cards';
    if (p.folded) { col.innerHTML += '<div class="folded-tag">folded</div>'; }
    else {
      (p.hole_cards.length ? p.hole_cards : ['??','??']).forEach(c => row.appendChild(makeCard(c)));
      col.appendChild(row);
    }
    opp.appendChild(col);
  });
  const you = document.getElementById('you');
  you.innerHTML = '';
  const human = s.players.find(p=>p.is_human);
  if (human) {
    const col = document.createElement('div'); col.className = 'player';
    col.innerHTML = `<div class="pname">${human.name}</div><div class="pchips">💰 ${human.chips}</div>`;
    const row = document.createElement('div'); row.className = 'p-cards';
    (human.hole_cards.length ? human.hole_cards : []).forEach(c => row.appendChild(makeCard(c)));
    col.appendChild(row); you.appendChild(col);
  }
  const logEl = document.getElementById('log');
  if (s.log.length === 0) { logEl.textContent = ''; logLen = 0; }
  else if (s.log.length > logLen) {
    logEl.textContent += s.log.slice(logLen).join('\n') + '\n';
    logLen = s.log.length; logEl.scrollTop = logEl.scrollHeight;
  }
  const waiting = s.waiting && s.phase === 'playing';
  document.getElementById('fold-btn').disabled  = !waiting;
  document.getElementById('raise-btn').disabled = !waiting;
  const cb = document.getElementById('call-btn');
  cb.disabled = !waiting;
  cb.textContent = s.call_amount === 0 ? 'Check' : 'Call ' + s.call_amount;
  const db = document.getElementById('deal-btn');
  db.disabled = s.phase === 'playing';
  db.textContent = s.phase === 'idle' ? 'Deal Hand' : 'New Hand';
  const ri = document.getElementById('raise-in');
  ri.min = s.raise_min; ri.max = s.raise_max;
  if (!ri.value || +ri.value < s.raise_min) ri.value = s.raise_min;
  document.getElementById('status').textContent =
    waiting              ? 'Your turn — choose an action'
    : s.phase==='hand_over' ? 'Hand over — deal again?'
    : s.phase==='playing'   ? 'Waiting for bots…' : '';
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
  chart.data.labels = []; chart.data.datasets[0].data = []; chart.update();
  await fetch('/deal',{method:'POST'});
}
poll();
</script>
</body>
</html>"""

if __name__ == "__main__":
    _web_ui = WebUI(None)
    _game   = TexasHoldemGame(_players, ui=_web_ui)
    _web_ui._game = _game
    _state["players"] = [_player_dict(p) for p in _players]
    print("Open http://localhost:5000 in your browser")
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)
