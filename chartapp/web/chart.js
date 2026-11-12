// The only file that turns price strings into numbers (docs/design/eod-chart-app.md 8).
// Numbers made here go to the chart and nowhere else.

const UP = '#26a69a', DOWN = '#ef5350', NEUTRAL = '#1565c0', FLAG = '#b26a00', SHAPE = '#6a1b9a';

// Close only: no range and no volume, as on the index where only the close is copied.
// Compared as numbers: "12.0" and "12.0000" are the same price.
export const closeOnly = b => b.v === 0 && Number(b.o) === Number(b.h) && Number(b.h) === Number(b.l)
  && Number(b.l) === Number(b.c);

// Every series gets every date ({time} alone draws nothing), so the series stay aligned
// and the line breaks between separate close-only runs.
export function split(bars) {
  const candles = [], line = [], volume = [];
  bars.forEach((b, i) => {
    const time = b.t, flat = closeOnly(b), next = bars[i + 1];
    candles.push(flat ? {time}
      : {time, open: Number(b.o), high: Number(b.h), low: Number(b.l), close: Number(b.c)});
    // the candle just before a close-only run lends its close, so the line joins the candles
    line.push(flat || (next && closeOnly(next)) ? {time, value: Number(b.c)} : {time});
    volume.push(flat ? {time} : {time, value: b.v});
  });
  return {candles, line, volume};
}

const byTime = (a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0);  // the library wants markers in time order

// One marker per signal and per flagged bar, pinned to the bar's own high or low.
export function markers(bars, signals) {
  const out = [], bar = new Map(bars.map(b => [b.t, b]));
  const top = b => ({time: b.t, position: 'atPriceTop', price: Number(b.h)});
  const bottom = b => ({time: b.t, position: 'atPriceBottom', price: Number(b.l)});
  for (const b of bars) {
    if (b.flags.includes('gap')) out.push({...top(b), shape: 'square', color: FLAG, text: 'gap'});
    if (b.flags.includes('upper_lock')) out.push({...top(b), shape: 'circle', color: FLAG, size: 0.5});
    if (b.flags.includes('lower_lock')) out.push({...bottom(b), shape: 'circle', color: FLAG, size: 0.5});
  }
  for (const s of signals) {
    const b = bar.get(s.signal_date);
    if (!b) continue;
    if (s.direction === 'bullish') out.push({...bottom(b), shape: 'arrowUp', color: UP});
    else if (s.direction === 'bearish') out.push({...top(b), shape: 'arrowDown', color: DOWN});
    else out.push({...top(b), shape: 'circle', color: NEUTRAL});
  }
  return out.sort(byTime);
}

// What to draw for one selected signal. Nothing here is dated after the signal bar.
export function overlay(signal, bars) {
  const at = new Map(bars.map((b, i) => [b.t, i]));
  const end = at.get(signal.signal_date);
  const points = signal.points.map(p => ({time: p.t, position: 'atPriceMiddle', price: Number(p.p),
                                          shape: 'circle', color: SHAPE, text: p.role}));
  const lines = [];
  for (const g of signal.segments) {
    const pair = [{time: g.start.t, value: Number(g.start.p)}, {time: g.end.t, value: Number(g.end.p)}].sort(byTime);
    if (pair[0].time !== pair[1].time) lines.push({data: pair, dashed: false});
  }
  // a level runs from the shape's first point (or 20 bars back) to the signal bar, never past it
  const shape = signal.points.map(p => at.get(p.t)).filter(i => i !== undefined);
  if (end > 0) {
    const start = Math.min(end - 1, shape.length ? Math.min(...shape) : Math.max(0, end - 20));
    for (const value of Object.values(signal.levels)) {
      lines.push({data: [{time: bars[start].t, value: Number(value)}, {time: bars[end].t, value: Number(value)}],
                  dashed: true});
    }
  }
  return {points, lines, index: end};
}

export function create(el) {
  const L = globalThis.LightweightCharts;
  const chart = L.createChart(el, {autoSize: true});
  const candles = chart.addSeries(L.CandlestickSeries);
  const line = chart.addSeries(L.LineSeries, {lineWidth: 2, priceLineVisible: false});
  // unseen, with a close on every date: markers need a series that has data where candles have none
  const anchor = chart.addSeries(L.LineSeries, {lineVisible: false, pointMarkersVisible: false,
    lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false});
  const volume = chart.addSeries(L.HistogramSeries, {priceFormat: {type: 'volume'}, priceLineVisible: false}, 1);
  const marks = L.createSeriesMarkers(anchor, []);
  chart.panes()[0].setStretchFactor(4);
  chart.panes()[1].setStretchFactor(1);
  let base = [], extra = [];
  return {
    set(bars) {
      const d = split(bars);
      candles.setData(d.candles);
      line.setData(d.line);
      volume.setData(d.volume);
      anchor.setData(bars.map(b => ({time: b.t, value: Number(b.c)})));
      // label only the series that holds the newest bar, or an old close shows as the current price
      const flat = bars.length > 0 && closeOnly(bars.at(-1));
      candles.applyOptions({lastValueVisible: !flat, priceLineVisible: !flat});
      line.applyOptions({lastValueVisible: flat});
      volume.applyOptions({lastValueVisible: !flat});
      // open on about a year of sessions; the rest is a scroll away
      chart.timeScale().setVisibleLogicalRange({from: bars.length - 250, to: bars.length + 5});
    },
    mark(bars, signals) {
      base = markers(bars, signals);
      this.select(null, bars);
    },
    select(signal, bars) {
      extra.forEach(s => chart.removeSeries(s));
      extra = [];
      if (!signal) { marks.setMarkers(base); return; }
      const o = overlay(signal, bars);
      marks.setMarkers([...base, ...o.points].sort(byTime));
      for (const l of o.lines) {
        const s = chart.addSeries(L.LineSeries, {color: SHAPE, lineWidth: 1, lineStyle: l.dashed ? 2 : 0,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
        s.setData(l.data);
        extra.push(s);
      }
      if (o.index !== undefined) chart.timeScale().setVisibleLogicalRange({from: o.index - 150, to: o.index + 60});
    },
    onHover(fn) { chart.subscribeCrosshairMove(p => fn(p.time)); },
  };
}
