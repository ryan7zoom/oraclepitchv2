"""
engine/v2/render.py

The v2 match dashboard: prediction first, same-game builder second,
historical form notes third, the full model market list last (handicaps at
the very bottom).
"""

from datetime import datetime
from html import escape
from typing import Dict, List

from engine.trends.names import display
from engine.v2.features import LEAGUE_NAMES

CSS = """
:root{--bg:#f4f6fa;--card:#fff;--ink:#0f172a;--mute:#64748b;--line:#e2e8f0;
--accent:#0f766e;--accent2:#115e59;--soft:#ecfdf5;--warn:#b45309;--shadow:0 1px 2px rgba(15,23,42,.05),0 10px 30px rgba(15,23,42,.06)}
:root[data-theme=dark]{--bg:#0b1118;--card:#141c26;--ink:#e8eef6;--mute:#94a3b8;--line:#263241;
--accent:#2dd4bf;--accent2:#5eead4;--soft:#0d2b2a;--warn:#fbbf24;--shadow:none}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:26px 16px 60px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px}
h1{margin:0;font-size:34px;letter-spacing:-.02em;font-weight:800}
.sub{color:var(--mute);font-size:13px;margin:4px 0 0}
#theme{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:9px 16px;border-radius:999px;font:inherit;font-size:14px;cursor:pointer;white-space:nowrap}
.note{color:var(--mute);font-size:13px;margin:10px 0 18px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 18px}
.chips button{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:7px 13px;border-radius:999px;font:inherit;font-size:13px;cursor:pointer}
.chips button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.day{font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin:26px 4px 10px}
details.m{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:0 0 12px;box-shadow:var(--shadow);overflow:hidden}
details.m>summary{list-style:none;cursor:pointer;padding:16px 18px}
details.m>summary::-webkit-details-marker{display:none}
.top{display:flex;justify-content:space-between;gap:10px;align-items:baseline;color:var(--mute);font-size:12px}
.lg{font-weight:700;color:var(--accent)}
.ko{font-weight:600}
.teams{font-size:20px;font-weight:750;letter-spacing:-.01em;margin:5px 0 3px}
.teams b{font-weight:750}
.exp{color:var(--mute);font-size:12px}
.bar{display:flex;height:7px;border-radius:4px;overflow:hidden;gap:2px;margin:10px 0 4px}
.bar i{display:block}
.pcts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:6px 0 0;font-size:12px;color:var(--mute)}
.pcts b{display:block;color:var(--ink);font-size:15px}
.body{padding:0 18px 18px;border-top:1px solid var(--line)}
.sec{font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--mute);margin:22px 0 8px}
.pick{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:12px 14px;font-size:14px}
.pick b{color:var(--accent2)}
.build{border:1px solid var(--line);border-radius:14px;padding:13px 14px;margin:0 0 10px;background:linear-gradient(180deg,var(--soft),transparent)}
.build .bh{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:8px}
.build .bh b{font-size:16px}
.build .joint{font-size:21px;font-weight:800;color:var(--accent)}
.leg{display:flex;gap:10px;align-items:baseline;padding:5px 0;border-top:1px dashed var(--line);font-size:14px}
.leg .n{color:var(--mute);font-size:12px;min-width:16px}
.leg .l{flex:1}
.leg .p{font-weight:700;font-variant-numeric:tabular-nums}
.leg .h{color:var(--mute);font-size:12px;min-width:44px;text-align:right}
.small{color:var(--mute);font-size:12px;margin-top:8px}
.note-line{display:flex;gap:9px;align-items:baseline;padding:5px 0;font-size:14px}
.note-line .h{flex:none;min-width:46px;text-align:center;font-size:12px;font-weight:800;color:var(--accent);background:var(--soft);border-radius:6px;padding:1px 6px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0 10px}
td,th{padding:6px 5px;border-bottom:1px solid var(--line);text-align:right}
td:first-child,th:first-child{text-align:left}
th{color:var(--mute);font-weight:600}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.hc{opacity:.9}
.foot{color:var(--mute);font-size:12px;margin:28px 2px 0}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:14px;padding:20px;color:var(--mute)}
@media(max-width:560px){h1{font-size:28px}.two{grid-template-columns:1fr}.teams{font-size:18px}}
"""

HEAD_JS = """(function(){try{var t=localStorage.getItem('op-theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}})();"""

JS = """
(function(){
var r=document.documentElement,b=document.getElementById('theme');
function lab(){if(b)b.textContent=r.getAttribute('data-theme')==='dark'?'Light mode':'Dark mode'}
if(b)b.onclick=function(){var n=r.getAttribute('data-theme')==='dark'?'light':'dark';r.setAttribute('data-theme',n);
try{localStorage.setItem('op-theme',n)}catch(e){}lab()};lab();
var lg='all';var btns=document.querySelectorAll('.chips button');
btns.forEach(function(x){x.onclick=function(){btns.forEach(function(y){y.classList.remove('on')});x.classList.add('on');
lg=x.dataset.l;document.querySelectorAll('details.m').forEach(function(m){m.style.display=(lg==='all'||m.dataset.league===lg)?'':'none'});
document.querySelectorAll('.day').forEach(function(d){var n=d.nextElementSibling,s=false;
while(n&&!n.classList.contains('day')){if(n.tagName==='DETAILS'&&n.style.display!=='none')s=true;n=n.nextElementSibling}
d.style.display=s?'':'none'})}});
})();
"""


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _money(x: float) -> str:
    return f"{x:.2f}"


def _bar(r: Dict[str, float]) -> str:
    return (f'<div class="bar"><i style="width:{r["H"]*100:.1f}%;background:var(--accent)"></i>'
            f'<i style="width:{r["D"]*100:.1f}%;background:#94a3b8"></i>'
            f'<i style="width:{r["A"]*100:.1f}%;background:var(--warn)"></i></div>')


def _markets_table(markets, kind: str, title: str) -> str:
    rows = [m for m in markets if m.kind == kind]
    if not rows:
        return ""
    # keep a compact set: for totals/team totals, one row per line with both sides
    if kind in ("total", "team"):
        if kind == "team":
            blocks = []
            for side, label in (("home", "Home team goals"), ("away", "Away team goals")):
                sub = [m for m in rows if m.side.startswith(side + ":")]
                blocks.append(_line_table(sub, label))
            return "".join(blocks)
        return _line_table(rows, title)
    body = "".join(f"<tr><td>{escape(m.label)}</td><td>{_pct(m.prob)}</td></tr>" for m in rows)
    return f"<div><div class='sec'>{escape(title)}</div><table>{body}</table></div>"


def _line_table(rows, title: str) -> str:
    lines = sorted({m.line for m in rows})
    body = []
    for ln in lines:
        over = next((m for m in rows if m.line == ln and m.side.endswith("over")), None)
        under = next((m for m in rows if m.line == ln and m.side.endswith("under")), None)
        if over and under:
            body.append(f"<tr><td>{ln:g}</td><td>{_pct(over.prob)}</td><td>{_pct(under.prob)}</td></tr>")
    return (f"<div><div class='sec'>{escape(title)}</div><table><tr><th>Line</th><th>Over</th><th>Under</th></tr>"
            + "".join(body) + "</table></div>")


def _most_table(items) -> str:
    if not items:
        return '<div class="small">No simulation data.</div>'
    body = "".join(f"<tr><td>{escape(x['label'])}</td><td>{_pct(x['prob'])}</td></tr>" for x in items)
    return f"<table>{body}</table>"


def _builder_html(slip, title: str) -> str:
    if not slip.legs:
        return ""
    legs = "".join(
        f'<div class="leg"><span class="n">{i+1}</span><span class="l">{escape(l.label)}</span>'
        f'<span class="h">{l.hit_text}</span><span class="p">{_pct(l.prob)}</span></div>'
        for i, l in enumerate(slip.legs))
    return (f'<div class="build"><div class="bh"><b>{escape(title)}</b>'
            f'<span class="joint">{_pct(slip.joint)}</span></div>{legs}'
            f'<div class="small">Joint chance from the correlated match simulation, not multiplied legs. '
            f'Fair price {_money(slip.fair)}. Model legs: {slip.model_legs}/{len(slip.legs)}.</div></div>')


def _match_html(card: dict) -> str:
    p = card["pred"]
    home, away = display(card["home"]), display(card["away"])
    r = p.result()
    main = card["main_total"]
    pick = card.get("pick", "")
    notes = "".join(
        f'<div class="note-line"><span class="h">{escape(n.hit_text)}</span>'
        f'<span>{escape(n.label)}</span></div>' for n in card["notes"])
    team_notes = "".join(
        f'<div class="note-line"><span class="h">{escape(n.hit_text)}</span>'
        f'<span>{escape(n.label)}</span></div>' for n in card.get("team_form", []))
    match_notes = "".join(
        f'<div class="note-line"><span class="h">{escape(n.hit_text)}</span>'
        f'<span>{escape(n.label)}</span></div>' for n in card.get("match_form", []))
    best = card["builder"]["best"]
    safe = card["builder"]["safe"]
    markets = card["markets"]
    return f"""
<details class="m" data-league="{escape(card['league'])}">
 <summary>
  <div class="top"><span><span class="lg">{escape(LEAGUE_NAMES.get(card['league'], card['league']))}</span> &middot; <span class="ko">{escape(card['kickoff'])}</span></span><span>{escape(card.get('date_label', card['date']))}</span></div>
  <div class="teams"><b>{escape(home)}</b> v <b>{escape(away)}</b></div>
  <div class="exp">Expected goals {p.lam_h:.2f} &ndash; {p.lam_a:.2f} &middot; model {escape(p.elo_source)}{' &middot; xG in use' if p.xg_used else ''}</div>
  <div class="exp">Form {escape(card.get('form', {}).get('home', '—'))} &ndash; {escape(card.get('form', {}).get('away', '—'))} (home &ndash; away, last 5)</div>
  {_bar(r)}
  <div class="pcts"><span>Home<b>{_pct(r['H'])}</b></span><span>Draw<b>{_pct(r['D'])}</b></span><span>Away<b>{_pct(r['A'])}</b></span></div>
 </summary>
 <div class="body">
  <div class="sec">Prediction</div>
  <div class="pick"><b>{escape(pick)}</b><br>
   Main total: {escape(main.label)} at {_pct(main.prob)} &middot; fair {_money(main.fair)}</div>
  <div class="sec">Form says <span style="font-weight:500;text-transform:none;letter-spacing:0">(history, not model)</span></div>
  <div class="two">
   <div><div class="small"><b>Team form</b></div>{team_notes or notes or '<div class="small">No qualifying team note.</div>'}</div>
   <div><div class="small"><b>Match total form</b></div>{match_notes or '<div class="small">No qualifying match note.</div>'}</div>
  </div>
  <div class="sec">Bet builder</div>
  {_builder_html(best, f"Best {len(best.legs)}-leg same-game builder") if best.legs else '<div class="small">No qualifying builder for this match.</div>'}
  {_builder_html(safe, "Safer 3-leg version") if safe.legs and best.legs and len(safe.legs) < len(best.legs) else ""}
  <div class="sec">Most corners / most cards</div>
  {_most_table(card.get('most', []))}
 </div>
</details>"""


def render(cards: List[dict], generated_at: datetime, data_through: str,
           model_source: str, warnings: List[str], tz_label: str = "GMT+8",
           record: dict = None, backtest: dict = None) -> str:
    leagues = [lg for lg in LEAGUE_NAMES if any(c["league"] == lg for c in cards)]
    chips = '<button class="on" data-l="all">All</button>' + "".join(
        f'<button data-l="{lg}">{escape(LEAGUE_NAMES[lg])}</button>' for lg in leagues)
    parts, day = [], None
    for c in sorted(cards, key=lambda c: (c["date"], c["kickoff"], c["league"], c["home"])):
        label = c.get("date_label", c["date"])
        if label != day:
            day = label
            parts.append(f'<div class="day">{escape(day)}</div>')
        parts.append(_match_html(c))
    if not parts:
        parts.append('<div class="empty">No fixtures in the next few days.</div>')
    warn = f'<div class="note">{escape(" | ".join(warnings))}</div>' if warnings else ""
    rec = ""
    if record and record.get("n"):
        rec = (f'<div class="note">Live record since {escape(record["from"])}: '
               f'{record["n"]} graded matches &middot; result {record["result_acc"]*100:.0f}% '
               f'&middot; over 2.5 {record["over_acc"]*100:.0f}% &middot; BTTS {record["btts_acc"]*100:.0f}%.</div>')
    bt = ""
    if backtest and backtest.get("summary", {}).get("ALL"):
        a = backtest["summary"]["ALL"]
        bt = (f'<details class="note"><summary style="cursor:pointer">How good is this? '
              f'{a["n"]:,} walk-forward matches</summary>'
              f'<table><tr><th>Market</th><th>Model</th><th>League base</th><th>Closing market</th></tr>'
              f'<tr><td>1X2 log loss</td><td>{a["logloss"]:.3f}</td><td>{a["base"]:.3f}</td>'
              f'<td>{a["market"]:.3f}</td></tr>'
              f'<tr><td>Over/under 2.5</td><td>{a["over_logloss"]:.3f}</td><td>&ndash;</td>'
              f'<td>0.669</td></tr>'
              f'<tr><td>Both teams to score</td><td>{a.get("btts_logloss", 0):.3f}</td><td>&ndash;</td><td>&ndash;</td></tr>'
              f'<tr><td>Home team over 1.5</td><td>{a.get("team15_logloss", 0):.3f}</td><td>&ndash;</td><td>&ndash;</td></tr></table>'
              f'<div class="small">Lower is better. Totals are shrunk toward the league average to reduce overconfidence; '
              f'the model has not beaten the closing line yet.</div></details>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OraclePitch</title><script>{HEAD_JS}</script><style>{CSS}</style></head>
<body><div class="wrap">
<div class="head"><div><h1>OraclePitch</h1>
<p class="sub">Top five leagues &middot; model v2 &middot; {escape(model_source)} &middot; data through {escape(data_through)}</p></div>
<button id="theme">Dark mode</button></div>
<p class="note">Probabilities are the model's chance of each market. The builder's joint chance comes from a correlated simulation of the same match. Ratings (ClubElo and xG) refresh weekly; results, odds and injuries refresh daily. Form lines are generated around this match's expected count (a 25-shot match sits near 24.5; a 20-shot match near 19.5) and are labelled team or match total. They are historical hit rates, not model output, and are shown as <b>9/10</b>.</p>
{rec}
{bt}
<div class="chips">{chips}</div>
{warn}
{''.join(parts)}
<p class="foot">Generated {generated_at.strftime('%d %b %Y %H:%M')} {escape(tz_label)}. No bet is a guarantee; the builder is a probability estimate, not advice.</p>
</div><script>{JS}</script></body></html>"""
