(function () {
  "use strict";
  var island = document.getElementById("ecdf-data");
  var mount = document.getElementById("ecdf");
  var tooltip = document.getElementById("tooltip");
  if (!island || !mount || !tooltip || typeof uPlot === "undefined") { return; }
  var data = JSON.parse(island.textContent);
  var aligned = [data.x].concat(data.series.map(function (series) { return series.values; }));
  var AXIS_FONT = '11px system-ui, -apple-system, "Segoe UI", sans-serif';
  var HEIGHT = 300;
  var chart = null;
  var held = null;

  // Colors resolve to literals at build time: a canvas keeps what it was
  // drawn with, so a scheme change or printing rebuilds the chart.
  function palette(forPrint) {
    var style = getComputedStyle(document.documentElement);
    var suffix = forPrint ? "-light" : "";
    function token(name) { return style.getPropertyValue(name + suffix).trim(); }
    return {
      series: data.series.map(function (series) { return token("--series-" + series.slot); }),
      grid: token("--grid"),
      axis: token("--axis"),
      muted: token("--muted")
    };
  }

  // The true ECDF value at `tokens`: the last column at or below it, as
  // the old crosshair read it, not the nearest sample uPlot would snap to.
  function shareAt(values, tokens) {
    var share = 0;
    for (var i = 0; i < data.x.length && data.x[i] <= tokens; i += 1) { share = values[i]; }
    return share;
  }

  function hideTooltip() { tooltip.style.visibility = "hidden"; }

  function renderTooltip(tokens, leftPx) {
    while (tooltip.firstChild) { tooltip.removeChild(tooltip.firstChild); }
    var at = document.createElement("div");
    at.className = "at";
    at.textContent = "≤ " + Math.round(tokens).toLocaleString() + " tokens";
    tooltip.appendChild(at);
    data.series.forEach(function (series) {
      var row = document.createElement("div");
      row.className = "row";
      var key = document.createElement("span");
      key.className = "key";
      key.style.borderTopColor = "var(--series-" + series.slot + ")";
      var value = document.createElement("b");
      value.textContent = Math.round(100 * shareAt(series.values, tokens)) + "%";
      var label = document.createElement("span");
      label.textContent = series.label;
      row.appendChild(key); row.appendChild(value); row.appendChild(label);
      tooltip.appendChild(row);
    });
    tooltip.style.visibility = "visible";
    var figure = mount.parentNode.getBoundingClientRect();
    var over = chart.over.getBoundingClientRect();
    var pixelX = over.left - figure.left + leftPx;
    tooltip.style.top = (over.top - figure.top + 8) + "px";
    tooltip.style.left = "0px";
    var width = tooltip.getBoundingClientRect().width;
    var left = pixelX + 12 + width > figure.width ? pixelX - width - 12 : pixelX + 12;
    tooltip.style.left = Math.max(0, left) + "px";
  }

  function onCursor(u) {
    if (u.cursor.left == null || u.cursor.left < 0) {
      hideTooltip();
      return;
    }
    // A keyboard-held position is exact; a pointer position round-trips
    // through pixels, which is as fine as a pointer can say.
    var tokens = held !== null ? held : Math.min(data.xmax, Math.max(0, u.posToVal(u.cursor.left, "x")));
    renderTooltip(tokens, u.cursor.left);
  }

  function xSplits() {
    var splits = [];
    for (var value = 0; value <= data.xmax; value += data.tick) { splits.push(value); }
    return splits;
  }

  function options(width, colors) {
    return {
      width: width,
      height: HEIGHT,
      legend: { show: false },
      cursor: { y: false, points: { show: false }, drag: { x: false, y: false } },
      scales: {
        x: { time: false, range: [0, data.xmax] },
        y: { range: [0, 1] }
      },
      axes: [
        {
          stroke: colors.muted,
          font: AXIS_FONT,
          size: 34,
          gap: 6,
          ticks: { show: false },
          border: { show: true, stroke: colors.axis, width: 1 },
          grid: { stroke: colors.grid, width: 1 },
          splits: xSplits,
          values: function (u, splits) {
            return splits.map(function (value) { return value === 0 ? "0" : value / 1024 + "K"; });
          }
        },
        {
          stroke: colors.muted,
          font: AXIS_FONT,
          size: 48,
          gap: 8,
          ticks: { show: false },
          grid: { stroke: colors.grid, width: 1 },
          splits: function () { return [0, 0.25, 0.5, 0.75, 1]; },
          values: function (u, splits) {
            return splits.map(function (value) { return Math.round(100 * value) + "%"; });
          }
        }
      ],
      series: [{}].concat(data.series.map(function (series, index) {
        return {
          label: series.label,
          stroke: colors.series[index],
          width: 2,
          paths: uPlot.paths.stepped({ align: 1 }),
          points: { show: false }
        };
      })),
      hooks: { setCursor: [onCursor] }
    };
  }

  function chartWidth() { return Math.max(280, mount.clientWidth); }

  function parkCursor() {
    if (chart) { chart.setCursor({ left: -10, top: -10 }); }
    hideTooltip();
  }

  function build(forPrint) {
    held = null;
    if (chart) { chart.destroy(); chart = null; }
    hideTooltip();
    chart = new uPlot(options(chartWidth(), palette(forPrint)), aligned, mount);
  }

  // Arrow keys hold the crosshair at an x the pointer then takes over.
  mount.addEventListener("keydown", function (event) {
    if (!chart) { return; }
    var step = data.xmax / 64;
    if (event.key === "ArrowRight") { held = held === null ? 0 : Math.min(data.xmax, held + step); }
    else if (event.key === "ArrowLeft") { held = held === null ? 0 : Math.max(0, held - step); }
    else if (event.key === "Escape") { held = null; parkCursor(); return; }
    else { return; }
    event.preventDefault();
    chart.setCursor({ left: chart.valToPos(held, "x"), top: chart.over.clientHeight / 2 });
  });
  // Capture phase: the pointer takes over before uPlot's own mousemove
  // re-renders the tooltip, so it can never read a stale held position.
  mount.addEventListener("pointermove", function () { held = null; }, true);
  mount.addEventListener("blur", function () { held = null; parkCursor(); });

  build(false);
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(function () {
      if (chart && Math.abs(chart.width - chartWidth()) > 1) {
        chart.setSize({ width: chartWidth(), height: HEIGHT });
      }
    }).observe(mount);
  }
  var scheme = window.matchMedia("(prefers-color-scheme: dark)");
  if (typeof scheme.addEventListener === "function") {
    scheme.addEventListener("change", function () {
      window.requestAnimationFrame(function () { build(false); });
    });
  }
  window.addEventListener("beforeprint", function () { build(true); });
  window.addEventListener("afterprint", function () { build(false); });
})();
