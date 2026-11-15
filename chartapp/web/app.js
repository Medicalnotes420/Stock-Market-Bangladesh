// Page logic. Prices stay the strings the API sent: no arithmetic on them here (see chart.js).
import {closeOnly, create} from './chart.js';

const $ = id => document.getElementById(id);
const chart = create($('chart'));
let known = new Map();    // ticker -> {type, first, last, bars}
let bars = [];            // bars of the ticker on screen
let byDate = new Map();   // date -> bar
let fired = new Map();    // date -> names of the patterns that fired on it
let loading = 0;

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function legend(b) {
  if (!b) return '';
  const signals = fired.has(b.t) ? `   signal: ${fired.get(b.t).join(', ')}` : '';
  if (closeOnly(b)) return `${b.t}   Close ${b.c}   (close only)${signals}`;
  const flags = b.flags.length && !cut ? `   [${b.flags.join(', ')}]` : '';
  // not in the labeling view: an adjustment factor says a bonus or split came later
  const raw = b.adj === '1.0' || cut ? '' : `   adjusted; traded close ${b.c_raw}`;
  return `${b.t}   O ${b.o}   H ${b.h}   L ${b.l}   C ${b.c}   Vol ${b.v.toLocaleString()}${raw}${flags}${signals}`;
}

function cell(row, text) {
  const td = row.insertCell();
  td.textContent = text;
  return td;
}

function table(signals) {
  const body = $('signals').tBodies[0];
  body.replaceChildren();
  for (const s of signals.toReversed()) {  // newest first
    const row = body.insertRow();
    const pick = document.createElement('button');
    pick.type = 'button';
    pick.textContent = s.signal_date;
    pick.setAttribute('aria-pressed', 'false');
    pick.addEventListener('click', () => {
      const on = pick.getAttribute('aria-pressed') !== 'true';  // a second click clears the selection
      for (const b of body.querySelectorAll('button')) b.setAttribute('aria-pressed', 'false');
      pick.setAttribute('aria-pressed', String(on));
      chart.select(on ? s : null, bars);
    });
    row.insertCell().append(pick);
    cell(row, s.pattern);
    cell(row, s.direction);
    cell(row, Object.entries(s.levels).map(([name, value]) => `${name} ${value}`).join(', '));
    cell(row, s.points.map(p => `${p.role} ${p.p} on ${p.t}`).join(', '));
    cell(row, s.note);
  }
}

// Labeling view: /?to=2019-03-14#TICKER shows the chart as it stood that day, with later bars and the
// plugins' own signals hidden, so an example can be labeled without knowing what came next.
const cut = new URLSearchParams(location.search).get('to');

async function load(ticker) {
  const mine = ++loading;
  $('status').textContent = `Loading ${ticker}…`;
  try {
    const d = await api('/api/bars/' + encodeURIComponent(ticker) + (cut ? '?to=' + encodeURIComponent(cut) : ''));
    if (mine !== loading) return;  // a newer pick overtook this one
    bars = d.bars;
    byDate = new Map(bars.map(b => [b.t, b]));
    fired = new Map();
    chart.set(bars);
    // gap and lock markers now; signals when they arrive. Not in the labeling view: those flags are worked
    // out with later data
    chart.mark(cut ? [] : bars, []);
    table([]);
    const k = known.get(ticker);
    $('status').textContent = cut
      ? `${ticker} · ${d.type} · cut off at ${cut}: ${bars.length.toLocaleString()} bars, later bars hidden`
      : `${ticker} · ${d.type} · ${k.bars.toLocaleString()} bars, ${k.first} to ${k.last}`;
    $('legend').textContent = legend(bars.at(-1));
    $('ticker').value = ticker;
    document.title = `${ticker} · DSE EOD`;
  } catch (e) {
    if (mine === loading) $('status').textContent = `Could not load ${ticker}: ${e.message}`;
    return;
  }
  // signals take a couple of seconds the first time a ticker is opened, so the chart does not wait for them.
  // The guard is "are these bars still on screen", not the load counter: a later pick that failed to load
  // leaves this chart up, and its signals must still arrive.
  if (cut) {
    $('sigstatus').textContent = 'hidden in the labeling view';
    return;
  }
  const shown = bars;
  $('sigstatus').textContent = 'Finding signals…';
  try {
    const signals = await api('/api/detections/' + encodeURIComponent(ticker));
    if (bars !== shown) return;
    for (const s of signals) fired.set(s.signal_date, [...(fired.get(s.signal_date) ?? []), s.pattern]);
    chart.mark(bars, signals);
    table(signals);
    $('sigstatus').textContent = signals.length === 1 ? '1 signal' : `${signals.length} signals`;
    $('legend').textContent = legend(bars.at(-1));
  } catch (e) {
    if (bars === shown) $('sigstatus').textContent = `Could not load signals: ${e.message}`;
  }
}

function hashTicker() {
  const raw = location.hash.slice(1);
  try { return decodeURIComponent(raw); } catch { return raw; }  // a hand-typed "#%E0%A4%A" must not throw
}

function fromHash() {
  const t = hashTicker();
  if (known.has(t)) load(t);
  else if (t) $('status').textContent = `Unknown ticker ${t}`;
}

async function badge() {
  const meta = await api('/api/meta');
  const n = meta.sessions_behind;
  $('stale').textContent = n === 0 ? `Data is current: last bar ${meta.last_bar}`
    : `Data is ${n} session${n === 1 ? '' : 's'} old: last bar ${meta.last_bar}`;
  $('stale').classList.toggle('old', n > 0);
}

async function start() {
  // the badge is on its own: a failed /api/meta must not take the chart down with it
  badge().catch(e => { $('stale').textContent = `Data age unknown: ${e.message}`; $('stale').classList.add('old'); });
  const tickers = await api('/api/tickers');
  known = new Map(tickers.map(t => [t.ticker, t]));
  $('tickers').replaceChildren(...tickers.map(t => new Option(t.type, t.ticker)));
  if (!location.hash) location.hash = '00DSEX';  // fires hashchange
  else fromHash();
}

$('pick').addEventListener('submit', e => {
  e.preventDefault();
  const t = $('ticker').value.trim().toUpperCase();
  if (t === hashTicker() && known.has(t)) load(t);  // same hash fires no hashchange: retry after a failed load
  else if (known.has(t)) location.hash = encodeURIComponent(t);
  else $('status').textContent = `Unknown ticker ${t}`;
});
addEventListener('hashchange', fromHash);
chart.onHover(time => { $('legend').textContent = legend(byDate.get(time) ?? bars.at(-1)); });
start().catch(e => { $('status').textContent = `Could not start: ${e.message}`; });
