(function () {
  "use strict";
  // The live panel of the served stats page: built here, so a saved page
  // (which has no live script) carries none of it. The panel polls the
  // server's /live endpoint, whose samples hold numbers and the loaded
  // preset's name only, and draws two charts over the last ten minutes.
  var script = document.currentScript;
  var meta = document.querySelector("p.meta");
  if (!script || !meta || typeof uPlot === "undefined") { return; }
  var api = script.getAttribute("data-api") || "";
  var interval = Math.max(1000, Number(script.getAttribute("data-interval")) || 2000);
  var WINDOW = 600;
  var HEIGHT = 180;
  var AXIS_FONT = '11px system-ui, -apple-system, "Segoe UI", sans-serif';

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  var section = element("section");
  section.id = "live";
  var heading = element("h2", null, "Live");
  var state = element("span", "state", "connecting");
  heading.appendChild(state);
  section.appendChild(heading);
  var tiles = element("div", "tiles");
  var values = {};
  [["processing", "Requests processing"], ["deferred", "Requests queued"],
   ["prompt", "Prompt tokens/s"], ["generation", "Generated tokens/s"]].forEach(function (tile) {
    var box = element("div", "tile");
    box.appendChild(element("div", "label", tile[1]));
    values[tile[0]] = element("div", "value", "–");
    box.appendChild(values[tile[0]]);
    tiles.appendChild(box);
  });
  section.appendChild(tiles);
  function figure(caption) {
    var wrapper = element("figure");
    wrapper.appendChild(element("figcaption", null, caption));
    var mount = element("div", "live-chart");
    wrapper.appendChild(mount);
    section.appendChild(wrapper);
    return mount;
  }
  var throughputMount = figure("Throughput — tokens per second as the server counts them (at each request's end), last ten minutes");
  var occupancyMount = figure("Occupancy — requests processing and queued, last ten minutes");
  meta.parentNode.insertBefore(section, meta.nextSibling);

  var charts = [];
  var latest = { x: [], throughput: [[], []], occupancy: [[], []] };

  function palette(forPrint) {
    var style = getComputedStyle(document.documentElement);
    var suffix = forPrint ? "-light" : "";
    function token(name) { return style.getPropertyValue(name + suffix).trim(); }
    return { series: [token("--series-1"), token("--series-2")], grid: token("--grid"),
      axis: token("--axis"), muted: token("--muted") };
  }

  function clockLabel(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function options(mount, names, stepped, colors) {
    function axis(extra) {
      return Object.assign({ stroke: colors.muted, font: AXIS_FONT, gap: 6, ticks: { show: false },
        grid: { stroke: colors.grid, width: 1 } }, extra);
    }
    return {
      width: Math.max(280, mount.clientWidth),
      height: HEIGHT,
      legend: { live: true },
      cursor: { y: false, points: { show: false }, drag: { x: false, y: false } },
      scales: {
        x: { time: true },
        y: { range: function (u, min, max) { return [0, Math.max(1, max == null ? 1 : max)]; } }
      },
      axes: [
        axis({
          size: 30,
          border: { show: true, stroke: colors.axis, width: 1 },
          // Time of day on one line; uPlot's own date labels take two.
          values: function (u, splits) { return splits.map(function (t) { return clockLabel(t); }); }
        }),
        axis({ size: 48, gap: 8, incrs: stepped ? [1, 2, 5, 10, 20, 50, 100] : undefined })
      ],
      series: [{ value: function (u, value) { return value == null ? "" : clockLabel(value); } }]
        .concat(names.map(function (name, index) {
          return {
            label: name,
            stroke: colors.series[index],
            width: 2,
            spanGaps: false,
            paths: stepped ? uPlot.paths.stepped({ align: 1 }) : uPlot.paths.linear(),
            points: { show: false },
            value: function (u, value) { return value == null ? "–" : String(value); }
          };
        }))
    };
  }

  function build(forPrint) {
    charts.forEach(function (chart) { chart.destroy(); });
    var colors = palette(forPrint);
    charts = [
      new uPlot(options(throughputMount, ["prompt", "generated"], false, colors),
        [latest.x].concat(latest.throughput), throughputMount),
      new uPlot(options(occupancyMount, ["processing", "queued"], true, colors),
        [latest.x].concat(latest.occupancy), occupancyMount)
    ];
  }

  function number(value, digits) {
    return value == null ? "–" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
  }

  function render(data) {
    var samples = Array.isArray(data.samples) ? data.samples : [];
    var cutoff = samples.length ? samples[samples.length - 1].t - WINDOW : 0;
    var x = [], prompt = [], generated = [], processing = [], deferred = [];
    samples.forEach(function (sample) {
      if (typeof sample.t !== "number" || sample.t < cutoff) { return; }
      x.push(sample.t);
      prompt.push(typeof sample.prompt_rate === "number" ? sample.prompt_rate : null);
      generated.push(typeof sample.generation_rate === "number" ? sample.generation_rate : null);
      processing.push(typeof sample.processing === "number" ? sample.processing : null);
      deferred.push(typeof sample.deferred === "number" ? sample.deferred : null);
    });
    latest = { x: x, throughput: [prompt, generated], occupancy: [processing, deferred] };
    charts[0].setData([x, prompt, generated]);
    charts[1].setData([x, processing, deferred]);
    var last = samples[samples.length - 1];
    if (!last) { state.textContent = "no samples yet"; return; }
    if (!last.up) { state.textContent = "model server not reachable at " + api + " (is the stack up?)"; }
    else if (typeof last.model !== "string") { state.textContent = "no preset loaded"; }
    else if (last.processing == null) { state.textContent = last.model + " loaded, first sample"; }
    else { state.textContent = last.model + " loaded"; }
    values.processing.textContent = number(last.processing, 0);
    values.deferred.textContent = number(last.deferred, 0);
    values.prompt.textContent = number(last.prompt_rate, 1);
    values.generation.textContent = number(last.generation_rate, 1);
  }

  var timer = null;
  function schedule() {
    if (timer !== null) { clearTimeout(timer); }
    timer = setTimeout(poll, interval);
  }
  function poll() {
    timer = null;
    if (document.hidden) { return; }
    fetch("/live", { cache: "no-store", credentials: "omit" })
      .then(function (response) {
        if (!response.ok) { throw new Error(String(response.status)); }
        return response.json();
      })
      .then(render)
      .catch(function () { state.textContent = "stats server unreachable"; })
      .then(schedule);
  }

  build(false);
  poll();
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && timer === null) { poll(); }
  });
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(function () {
      charts.forEach(function (chart, index) {
        var mount = index === 0 ? throughputMount : occupancyMount;
        var width = Math.max(280, mount.clientWidth);
        if (Math.abs(chart.width - width) > 1) { chart.setSize({ width: width, height: HEIGHT }); }
      });
    }).observe(section);
  }
  var scheme = window.matchMedia("(prefers-color-scheme: dark)");
  if (typeof scheme.addEventListener === "function") {
    scheme.addEventListener("change", function () { window.requestAnimationFrame(function () { build(false); }); });
  }
  window.addEventListener("beforeprint", function () { build(true); });
  window.addEventListener("afterprint", function () { build(false); });
})();
