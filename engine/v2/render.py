"""
engine/v2/render.py

The v2 match dashboard, Apple-style glass.

Each match is one frosted card. Opened, it shows the safe-style bet builder
first (one combined bet, the combined chance as a ring), then the prediction,
the history-based form notes, the older goals/corners/cards builders and the
most-corners / most-cards table.
"""

from datetime import datetime
from html import escape
from typing import Dict, List

from engine.trends.names import display
from engine.v2.features import LEAGUE_NAMES

LIGHT = (
    "--bg:#e9eff9;--ink:#0f1728;--mute:#566176;--faint:#8591a6;"
    "--glass:rgba(255,255,255,.56);--glass2:rgba(255,255,255,.80);--inner:rgba(255,255,255,.55);"
    "--edge:rgba(255,255,255,.80);--hi:rgba(255,255,255,.65);--line:rgba(15,23,40,.09);"
    "--accent:#0a7cff;--accent-soft:rgba(10,124,255,.12);--ok:#1fae7a;--ok-soft:rgba(31,174,122,.14);"
    "--warn:#ff9500;--bad:#ff453a;--track:rgba(15,23,40,.10);--hole:#f4f8ff;"
    "--shadow:0 1px 2px rgba(30,50,90,.06),0 14px 44px rgba(52,78,130,.16);"
    "--blob1:#8ec1ff;--blob2:#c4b2ff;--blob3:#9ff0d3;--blobo:.62;color-scheme:light"
)
DARK = (
    "--bg:#060a13;--ink:#eef3fb;--mute:#9ba8bf;--faint:#6d7a92;"
    "--glass:rgba(28,36,54,.52);--glass2:rgba(34,44,66,.78);--inner:rgba(255,255,255,.055);"
    "--edge:rgba(255,255,255,.11);--hi:rgba(255,255,255,.10);--line:rgba(255,255,255,.08);"
    "--accent:#4aa3ff;--accent-soft:rgba(74,163,255,.18);--ok:#34d3a0;--ok-soft:rgba(52,211,160,.16);"
    "--warn:#ffb340;--bad:#ff6b61;--track:rgba(255,255,255,.12);--hole:#141c2c;"
    "--shadow:0 1px 0 rgba(255,255,255,.04) inset,0 18px 50px rgba(0,0,0,.5);"
    "--blob1:#1c46c9;--blob2:#5b2bc0;--blob3:#0c6b62;--blobo:.5;color-scheme:dark"
)

BASE_CSS = """
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;color:var(--ink);background:transparent;min-height:100vh;
font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI Variable Text","Segoe UI",system-ui,Roboto,sans-serif;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body::before{content:"";position:fixed;inset:0;z-index:-1;opacity:var(--blobo);
background:radial-gradient(620px 440px at 10% 6%,var(--blob1),transparent 70%),
radial-gradient(560px 480px at 94% 16%,var(--blob2),transparent 70%),
radial-gradient(680px 540px at 48% 104%,var(--blob3),transparent 70%)}
.wrap{max-width:780px;margin:0 auto;padding:34px 16px 70px}
.glass{background:var(--glass);border:1px solid var(--edge);
-webkit-backdrop-filter:blur(26px) saturate(175%);backdrop-filter:blur(26px) saturate(175%);
box-shadow:var(--shadow),inset 0 1px 0 var(--hi)}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){.glass{background:var(--glass2)}}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:6px}
h1{margin:0;font-size:40px;line-height:1.05;letter-spacing:-.035em;font-weight:700}
.sub{color:var(--mute);font-size:14px;margin:8px 0 0}
#theme{border-radius:999px;color:var(--ink);padding:8px 16px;font:inherit;font-size:14px;font-weight:500;cursor:pointer;white-space:nowrap}
.caption{color:var(--mute);font-size:13px;margin:12px 2px 0}
.chips{display:flex;gap:8px;overflow-x:auto;padding:16px 2px 6px;scrollbar-width:none}
.chips::-webkit-scrollbar{display:none}
.chips button{flex:none;border-radius:999px;color:var(--ink);padding:8px 15px;font:inherit;font-size:14px;font-weight:500;cursor:pointer}
.chips button.glass{-webkit-backdrop-filter:none;backdrop-filter:none;background:var(--glass2)}
.chips button.on{background:var(--accent);border-color:transparent;color:#fff;box-shadow:0 6px 18px rgba(10,124,255,.35)}
.day{font-size:15px;font-weight:600;color:var(--mute);margin:30px 6px 10px}
details.m{border-radius:24px;margin:0 0 14px;overflow:hidden}
details.m>summary{list-style:none;cursor:pointer;padding:18px 20px;display:grid;grid-template-columns:1fr auto;gap:6px 16px;align-items:center;position:relative}
details.m>summary::-webkit-details-marker{display:none}
.s-top{grid-column:1/-1;display:flex;align-items:center;gap:10px;font-size:13px;color:var(--mute)}
.lg{font-weight:600;color:var(--accent);background:var(--accent-soft);padding:2px 10px;border-radius:999px;font-size:12px}
.teams{font-size:22px;line-height:1.2;font-weight:650;letter-spacing:-.02em}
.teams i{font-style:normal;color:var(--faint);font-weight:500;padding:0 4px}
.meta{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--mute);font-size:12.5px;margin-top:5px;align-items:center}
.fm{display:inline-flex;gap:3px;vertical-align:middle;margin:0 4px}
.fm b{width:9px;height:9px;border-radius:50%;display:inline-block;background:var(--track)}
.fm b.W{background:var(--ok)}.fm b.L{background:var(--bad)}.fm b.D{background:var(--faint)}
.pill{grid-row:2;grid-column:2;text-align:center;min-width:92px;padding:9px 12px;border-radius:18px;background:var(--ok-soft);border:1px solid var(--line)}
.pill b{display:block;font-size:24px;line-height:1.1;font-weight:700;letter-spacing:-.02em;color:var(--ok)}
.pill span{display:block;font-size:11.5px;color:var(--mute);margin-top:2px}
.bar{grid-column:1/-1;display:flex;height:8px;border-radius:5px;overflow:hidden;gap:2px;margin-top:8px}
.bar i{display:block;border-radius:4px}
.pcts{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);font-size:12px;color:var(--mute)}
.pcts span:nth-child(2){text-align:center}.pcts span:nth-child(3){text-align:right}
.pcts b{font-weight:650;color:var(--ink);font-size:14px;margin-left:5px}
.body{padding:2px 20px 22px;border-top:1px solid var(--line)}
.sec{font-size:15px;font-weight:650;letter-spacing:-.01em;margin:24px 0 10px}
.sec small{font-weight:400;color:var(--mute);font-size:12.5px;margin-left:6px}
.ticket{border-radius:22px;padding:18px;margin-top:18px;background:var(--glass2);border:1px solid var(--edge);box-shadow:inset 0 1px 0 var(--hi),0 8px 28px rgba(40,70,130,.10)}
.t-head{display:flex;align-items:center;gap:16px}
.ring{--p:0;width:84px;height:84px;flex:none;border-radius:50%;position:relative;display:grid;place-items:center;
background:conic-gradient(var(--ok) calc(var(--p)*1%),var(--track) 0)}
.ring::before{content:"";position:absolute;inset:8px;border-radius:50%;background:var(--hole)}
.ring span{position:relative;font-size:21px;font-weight:700;letter-spacing:-.02em}
.t-title{font-size:17px;font-weight:650;letter-spacing:-.015em}
.t-meta{display:flex;flex-wrap:wrap;gap:2px 14px;color:var(--mute);font-size:13.5px;margin-top:3px}
.t-meta b{color:var(--ink);font-weight:650}
.legs{list-style:none;margin:16px 0 0;padding:0;display:grid;gap:8px}
.legs li{--w:0%;display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:14px;border:1px solid var(--line);
background:linear-gradient(90deg,var(--ok-soft) var(--w),transparent 0),var(--inner);font-size:15px}
.legs .l{flex:1}
.legs .tag{font-size:11px;color:var(--mute);border:1px solid var(--line);border-radius:999px;padding:0 8px;line-height:18px}
.legs .p{font-weight:650;font-variant-numeric:tabular-nums}
.fine{color:var(--mute);font-size:12.5px;margin:12px 2px 0}
.fine.warn{color:var(--warn)}
.pick{border-radius:16px;padding:13px 15px;font-size:14.5px;background:var(--inner);border:1px solid var(--line)}
.pick b{font-weight:650}
.build{border-radius:16px;padding:14px 15px;margin:0 0 10px;background:var(--inner);border:1px solid var(--line)}
.build .bh{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:8px}
.build .bh b{font-size:15px}
.build .joint{font-size:20px;font-weight:700;color:var(--ok)}
.leg{display:flex;gap:10px;align-items:baseline;padding:6px 0;border-top:1px solid var(--line);font-size:14px}
.leg .n{color:var(--faint);font-size:12px;min-width:16px}
.leg .l{flex:1}
.leg .p{font-weight:650;font-variant-numeric:tabular-nums}
.leg .h{color:var(--mute);font-size:12px;min-width:44px;text-align:right}
.small{color:var(--mute);font-size:12.5px;margin-top:8px}
.note-line{display:flex;gap:9px;align-items:baseline;padding:5px 0;font-size:14px}
.note-line .h{flex:none;min-width:46px;text-align:center;font-size:12px;font-weight:650;color:var(--ok);background:var(--ok-soft);border-radius:8px;padding:1px 6px}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:4px 0 10px}
td,th{padding:7px 4px;border-bottom:1px solid var(--line);text-align:right}
td:first-child,th:first-child{text-align:left}
th{color:var(--mute);font-weight:500}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
details.more>summary{cursor:pointer;color:var(--mute);font-size:13px;margin-top:20px;list-style:none}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::before{content:"\\25B8";display:inline-block;margin-right:6px;transition:transform .15s}
details.more[open]>summary::before{transform:rotate(90deg)}
details.more .inside{margin-top:10px}
details.about{border-radius:18px;padding:14px 18px;margin:18px 0 0;color:var(--mute);font-size:13.5px}
details.about>summary{cursor:pointer;color:var(--ink);font-weight:550}
.foot{color:var(--mute);font-size:12.5px;margin:30px 4px 0}
.empty{border-radius:20px;padding:22px;color:var(--mute)}
@media(max-width:600px){h1{font-size:32px}.two{grid-template-columns:1fr}.teams{font-size:19px}
.pill{min-width:78px}.pill b{font-size:21px}.ring{width:74px;height:74px}.wrap{padding-top:24px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

CSS = (":root{" + LIGHT + "}"
       "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){" + DARK + "}}"
       ":root[data-theme=dark]{" + DARK + "}" + BASE_CSS)

HEAD_JS = """(function(){try{var t=localStorage.getItem('op-theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}})();"""

JS = """
(function(){
var r=document.documentElement,b=document.getElementById('theme');
function cur(){var t=r.getAttribute('data-theme');if(t)return t;
return(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'}
function lab(){if(b)b.textContent=cur()==='dark'?'Light mode':'Dark mode'}
if(b)b.onclick=function(){var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);
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
            f'<i style="width:{r["D"]*100:.1f}%;background:var(--faint)"></i>'
            f'<i style="width:{r["A"]*100:.1f}%;background:var(--warn)"></i></div>')


def _form_dots(s: str) -> str:
    dots = "".join(f'<b class="{c if c in "WDL" else ""}"></b>' for c in s if c.strip())
    return f'<span class="fm" aria-label="{escape(s)}">{dots}</span>' if dots else "–"


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


def _safe_html(sh) -> str:
    """The safe-style builder: one combined bet, the combined chance as a ring."""
    if not sh:
        return ""
    pick = sh.get("pick")
    intro = (f'Favourite <b>{escape(sh["favourite"])}</b> ({_pct(sh["fav_win_prob"])} to win), '
             f'underdog <b>{escape(sh["underdog"])}</b>.')
    if pick is None or not pick.legs:
        return (f'<div class="sec">Safe-style builder</div><div class="small">{intro} '
                f'No builder in this match reaches a fair price of 1.20.</div>')
    legs = "".join(
        f'<li style="--w:{l.prob*100:.1f}%"><span class="l">{escape(l.label)}</span>'
        + ('<span class="tag" title="From team form, not the model">form</span>' if l.source != "model" else "")
        + f'<span class="p">{_pct(l.prob)}</span></li>'
        for l in pick.legs)
    warn = ("" if pick.floor_met else
            '<div class="fine warn">Nothing in this match reaches a fair price of 1.20; '
            'this is the highest price available.</div>')
    hidden = ("" if sh.get("underdog_shown", True) else
              '<div class="fine">Underdog shots and corners are hidden: this league does not have '
              'enough shots and corner data yet.</div>')
    return (f'<div class="sec">Safe-style builder</div><div class="small" style="margin-top:-4px">{intro}</div>'
            f'<div class="ticket"><div class="t-head">'
            f'<div class="ring" style="--p:{pick.joint*100:.1f}" role="img" aria-label="Combined chance {_pct(pick.joint)}">'
            f'<span>{_pct(pick.joint)}</span></div>'
            f'<div><div class="t-title">{len(pick.legs)}-leg builder</div>'
            f'<div class="t-meta"><span>Fair price <b>{_money(pick.fair)}</b></span>'
            f'<span>Combined chance <b>{_pct(pick.joint)}</b></span></div></div></div>'
            f'<ul class="legs">{legs}</ul>'
            f'<div class="fine">Combined chance comes from the correlated match simulation, not multiplied legs. '
            f'Compare the fair price with your bookmaker and take it only if the bookmaker pays more.</div>'
            f'{warn}{hidden}</div>')


def _notes(items) -> str:
    return "".join(f'<div class="note-line"><span class="h">{escape(n.hit_text)}</span>'
                   f'<span>{escape(n.label)}</span></div>' for n in items)


def _match_html(card: dict) -> str:
    p = card["pred"]
    home, away = display(card["home"]), display(card["away"])
    r = p.result()
    main = card["main_total"]
    pick = card.get("pick", "")
    notes = _notes(card["notes"])
    team_notes = _notes(card.get("team_form", []))
    match_notes = _notes(card.get("match_form", []))
    best = card["builder"]["best"]
    safe = card["builder"]["safe"]
    sh = card.get("shapes")
    sp = sh.get("pick") if sh else None
    pill = (f'<div class="pill"><b>{_pct(sp.joint)}</b><span>fair {_money(sp.fair)}</span></div>'
            if sp is not None and sp.legs else "")
    fm = card.get("form", {})
    return f"""
<details class="m glass" data-league="{escape(card['league'])}">
 <summary>
  <div class="s-top"><span class="lg">{escape(LEAGUE_NAMES.get(card['league'], card['league']))}</span><span>{escape(card['kickoff'])}</span></div>
  <div><div class="teams">{escape(home)}<i>v</i>{escape(away)}</div>
  <div class="meta"><span>Expected goals {p.lam_h:.2f} &ndash; {p.lam_a:.2f}</span><span>{escape(p.elo_source)}{' with xG' if p.xg_used else ''}</span>
  <span>Form{_form_dots(fm.get('home', ''))}&ndash;{_form_dots(fm.get('away', ''))}</span></div></div>
  {pill}
  {_bar(r)}
  <div class="pcts"><span>Home<b>{_pct(r['H'])}</b></span><span>Draw<b>{_pct(r['D'])}</b></span><span>Away<b>{_pct(r['A'])}</b></span></div>
 </summary>
 <div class="body">
  {_safe_html(sh)}
  <div class="sec">Prediction</div>
  <div class="pick"><b>{escape(pick)}</b><br>
   Main total: {escape(main.label)} at {_pct(main.prob)}, fair {_money(main.fair)}</div>
  <div class="sec">Form says<small>history, not the model</small></div>
  <div class="two">
   <div><div class="small"><b>Team form</b></div>{team_notes or notes or '<div class="small">No qualifying team note.</div>'}</div>
   <div><div class="small"><b>Match total form</b></div>{match_notes or '<div class="small">No qualifying match note.</div>'}</div>
  </div>
  <details class="more"><summary>Bet builder (goals, corners, cards)</summary><div class="inside">
  {_builder_html(best, f"Best {len(best.legs)}-leg same-game builder") if best.legs else '<div class="small">No qualifying builder for this match.</div>'}
  {_builder_html(safe, "Safer 3-leg version") if safe.legs and best.legs and len(safe.legs) < len(best.legs) else ""}
  </div></details>
  <div class="sec">Most corners / most cards</div>
  {_most_table(card.get('most', []))}
 </div>
</details>"""


def render(cards: List[dict], generated_at: datetime, data_through: str,
           model_source: str, warnings: List[str], tz_label: str = "GMT+8",
           record: dict = None, backtest: dict = None) -> str:
    leagues = [lg for lg in LEAGUE_NAMES if any(c["league"] == lg for c in cards)]
    chips = '<button class="glass on" data-l="all">All</button>' + "".join(
        f'<button class="glass" data-l="{lg}">{escape(LEAGUE_NAMES[lg])}</button>' for lg in leagues)
    parts, day = [], None
    for c in sorted(cards, key=lambda c: (c["date"], c["kickoff"], c["league"], c["home"])):
        label = c.get("date_label", c["date"])
        if label != day:
            day = label
            parts.append(f'<div class="day">{escape(day)}</div>')
        parts.append(_match_html(c))
    if not parts:
        parts.append('<div class="empty glass">No fixtures in the next few days.</div>')
    warn = f'<p class="caption">{escape(" | ".join(warnings))}</p>' if warnings else ""
    rec = ""
    if record and record.get("n"):
        rec = (f'<p class="caption">Live record since {escape(record["from"])}: '
               f'{record["n"]} graded matches, result {record["result_acc"]*100:.0f}%, '
               f'over 2.5 {record["over_acc"]*100:.0f}%, BTTS {record["btts_acc"]*100:.0f}%.</p>')
    bt = ""
    if backtest and backtest.get("summary", {}).get("ALL"):
        a = backtest["summary"]["ALL"]
        bt = (f'<details class="about glass"><summary>How good is this? '
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
    how = ('<details class="about glass"><summary>How to read this</summary>'
           '<p>Each percentage is the model&rsquo;s chance. The safe-style builder is the combination of 2 to 5 legs '
           'with the highest combined chance that still has a fair price of at least 1.20. The combined chance is '
           'measured on a correlated simulation of the same match, not multiplied. Legs marked <b>form</b> come from '
           'recent team rates, not the model. Form notes are historical hit rates such as <b>9/10</b>. '
           'Ratings refresh weekly; results, odds and injuries refresh daily.</p></details>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>OraclePitch</title><script>{HEAD_JS}</script><style>{CSS}</style></head>
<body><div class="wrap">
<div class="head"><div><h1>OraclePitch</h1>
<p class="sub">{len(LEAGUE_NAMES)} leagues, model v2, {escape(model_source)}, data through {escape(data_through)}</p></div>
<button id="theme" class="glass">Dark mode</button></div>
{rec}
<div class="chips">{chips}</div>
{warn}
{''.join(parts)}
{how}
{bt}
<p class="foot">Generated {generated_at.strftime('%d %b %Y %H:%M')} {escape(tz_label)}. No bet is a guarantee; the builder is a probability estimate, not advice.</p>
</div><script>{JS}</script></body></html>"""
