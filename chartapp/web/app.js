// Page logic. Prices stay the strings the API sent: no arithmetic on them here (see chart.js).
import {closeOnly, create} from './chart.js';

const $ = id => document.getElementById(id);
const chart = create($('chart'));
let known = new Map();   // ticker -> {type, first, last, bars}
let byDate = new Map();  // date -> bar of the ticker on screen
let latest = null;
let loading = 0;

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function legend(b) {
  if (!b) return '';
  const flags = b.flags.length ? `   [${b.flags.join(', ')}]` : '';
  const raw = b.adj === '1.0' ? '' : `   adjusted; traded close ${b.c_raw}`;
  if (closeOnly(b)) return `${b.t}   Close ${b.c}   (close only)`;
  return `${b.t}   O ${b.o}   H ${b.h}   L ${b.l}   C ${b.c}   Vol ${b.v.toLocaleString()}${raw}${flags}`;
}

async function load(ticker) {
  const mine = ++loading;
  $('status').textContent = `Loading ${ticker}…`;
  try {
    const d = await api('/api/bars/' + encodeURIComponent(ticker));
    if (mine !== loading) return;  // a newer pick overtook this one
    byDate = new Map(d.bars.map(b => [b.t, b]));
    latest = d.bars.at(-1);
    chart.set(d.bars);
    const k = known.get(ticker);
    $('status').textContent = `${ticker} · ${d.type} · ${k.bars.toLocaleString()} bars, ${k.first} to ${k.last}`;
    $('legend').textContent = legend(latest);
    $('ticker').value = ticker;
    document.title = `${ticker} · DSE EOD`;
  } catch (e) {
    if (mine === loading) $('status').textContent = `Could not load ${ticker}: ${e.message}`;
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
chart.onHover(time => { $('legend').textContent = legend(byDate.get(time) ?? latest); });
start().catch(e => { $('status').textContent = `Could not start: ${e.message}`; });
