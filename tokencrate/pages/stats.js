(function () {
  "use strict";
  // Click-to-sort on every table: a header's button sorts the body rows by
  // that column, a second click reverses; a footer (a total) stays put.
  function sortValue(cell) {
    var text = cell.textContent.trim();
    if (cell.classList.contains("n")) {
      // A session length reads `38s`, `4m 30s`, or `1h 12m`: seconds.
      var length = /^(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?$/.exec(text);
      if (length && text) { return 3600 * (length[1] || 0) + 60 * (length[2] || 0) + 1 * (length[3] || 0); }
      var number = parseFloat(text.replace(/,/g, ""));
      return isNaN(number) ? -Infinity : number;
    }
    return text.toLowerCase();
  }
  Array.prototype.forEach.call(document.querySelectorAll("thead th"), function (th) {
    var button = th.querySelector("button");
    if (!button) { return; }
    button.addEventListener("click", function () {
      var table = th.closest("table");
      var index = Array.prototype.indexOf.call(th.parentNode.children, th);
      var ascending = th.getAttribute("aria-sort") !== "ascending";
      Array.prototype.forEach.call(table.querySelectorAll("thead th"), function (other) { other.removeAttribute("aria-sort"); });
      th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
      var body = table.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var left = sortValue(a.cells[index]), right = sortValue(b.cells[index]);
        return (left < right ? -1 : left > right ? 1 : 0) * (ascending ? 1 : -1);
      });
      rows.forEach(function (row) { body.appendChild(row); });
    });
  });

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
  var colors = null;

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
      muted: token("--muted"),
      surface: token("--surface")
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
      var fit = Math.round(100 * shareAt(series.values, tokens));
      var value = document.createElement("b");
      value.textContent = fit + "% fit";
      var label = document.createElement("span");
      label.textContent = series.label + " \u00b7 " + (100 - fit) + "% would not";
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

  // The reference marks (the compaction p50, one preset's slot) as labelled
  // hairlines over the plot; a slot beyond the axis is named at its right
  // edge. Drawn after the series, in canvas pixels.
  function drawMarks(u) {
    var ctx = u.ctx;
    var ratio = window.devicePixelRatio || 1;
    var box = u.bbox;
    ctx.save();
    ctx.font = (11 * ratio) + 'px system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.textBaseline = "top";
    ctx.lineWidth = ratio;
    ctx.strokeStyle = colors.muted;
    ctx.fillStyle = colors.muted;
    (data.marks || []).forEach(function (mark, index) {
      var x = mark.beyond ? box.left + box.width : Math.round(u.valToPos(mark.value, "x", true));
      ctx.beginPath();
      ctx.moveTo(x, box.top);
      ctx.lineTo(x, box.top + box.height);
      ctx.stroke();
      var right = x > box.left + box.width / 2;
      ctx.textAlign = right ? "right" : "left";
      var label = mark.label + " " + mark.value.toLocaleString() + (mark.beyond ? " \u2192" : "");
      var textX = x + (right ? -4 : 4) * ratio;
      var textY = box.top + (4 + 14 * index) * ratio;
      var width = ctx.measureText(label).width;
      // A surface-colored backing keeps the label legible over the lines.
      ctx.fillStyle = colors.surface;
      ctx.fillRect(right ? textX - width - 2 * ratio : textX - 2 * ratio, textY - ratio, width + 4 * ratio, 13 * ratio);
      ctx.fillStyle = colors.muted;
      ctx.fillText(label, textX, textY);
    });
    ctx.restore();
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
          label: "context size (tokens)",
          labelFont: AXIS_FONT,
          labelSize: 14,
          labelGap: 2,
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
          label: "requests that fit",
          labelFont: AXIS_FONT,
          labelSize: 14,
          labelGap: 2,
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
      hooks: { setCursor: [onCursor], draw: [drawMarks] }
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
    colors = palette(forPrint);
    chart = new uPlot(options(chartWidth(), colors), aligned, mount);
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
