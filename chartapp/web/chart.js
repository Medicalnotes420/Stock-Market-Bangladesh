// The only file that turns price strings into numbers (docs/design/eod-chart-app.md 8).
// Numbers made here go to the chart and nowhere else.

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

export function create(el) {
  const L = globalThis.LightweightCharts;
  const chart = L.createChart(el, {autoSize: true});
  const candles = chart.addSeries(L.CandlestickSeries);
  const line = chart.addSeries(L.LineSeries, {lineWidth: 2, priceLineVisible: false});
  const volume = chart.addSeries(L.HistogramSeries, {priceFormat: {type: 'volume'}, priceLineVisible: false}, 1);
  chart.panes()[0].setStretchFactor(4);
  chart.panes()[1].setStretchFactor(1);
  return {
    set(bars) {
      const d = split(bars);
      candles.setData(d.candles);
      line.setData(d.line);
      volume.setData(d.volume);
      // label only the series that holds the newest bar, or an old close shows as the current price
      const flat = bars.length > 0 && closeOnly(bars.at(-1));
      candles.applyOptions({lastValueVisible: !flat, priceLineVisible: !flat});
      line.applyOptions({lastValueVisible: flat});
      volume.applyOptions({lastValueVisible: !flat});
      // open on about a year of sessions; the rest is a scroll away
      chart.timeScale().setVisibleLogicalRange({from: bars.length - 250, to: bars.length + 5});
    },
    onHover(fn) { chart.subscribeCrosshairMove(p => fn(p.time)); },
  };
}
