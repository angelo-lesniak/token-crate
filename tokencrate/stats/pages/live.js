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
  var gpu = script.getAttribute("data-gpu") === "1";
  var WINDOW = 600;
  var HEIGHT = 140;
  var SPARK = 12;
  var AXIS_FONT = '11px system-ui, -apple-system, "Segoe UI", sans-serif';

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  var section = element("section");
  section.id = "live";
  // One line of the numbers, fixed to the top of the window once the
  // tiles are scrolled away; each figure carries a sparkline of the ring.
  // Out of the flow, so showing it moves nothing.
  var strip = element("div", "strip");
  var stripItems = {};
  function setState(kind) {
    section.setAttribute("data-state", kind);
    strip.setAttribute("data-state", kind);
  }
  setState("connecting");
  var heading = element("h2", null, "Live");
  heading.appendChild(element("span", "dot"));
  var state = element("span", "state", "connecting");
  heading.appendChild(state);
  section.appendChild(heading);
  var tiles = element("div", "tiles");
  var values = {};
  var reasons = {};
  [["processing", "Requests processing"], ["deferred", "Requests queued"],
   ["prompt", "Prompt tokens/s"], ["generation", "Generated tokens/s"],
   ["acceptance", "Draft acceptance"], ["memory", "GPU memory (MiB)"], ["power", "GPU power (W)"]
  ].forEach(function (tile) {
    if (!gpu && (tile[0] === "memory" || tile[0] === "power")) { return; }
    var box = element("div", "tile");
    box.appendChild(element("div", "label", tile[1]));
    values[tile[0]] = element("div", "value", "–");
    reasons[tile[0]] = element("div", "reason", "");
    box.appendChild(values[tile[0]]);
    box.appendChild(reasons[tile[0]]);
    tiles.appendChild(box);
  });
  section.appendChild(tiles);
  var charts = element("div", "live-charts");
  var empties = [];
  function figure(caption) {
    var wrapper = element("figure");
    wrapper.appendChild(element("figcaption", null, caption));
    var mount = element("div", "live-chart");
    wrapper.appendChild(mount);
    var empty = element("div", "empty", "");
    empty.hidden = true;
    empties.push(empty);
    wrapper.appendChild(empty);
    charts.appendChild(wrapper);
    return mount;
  }
  var throughputMount = figure("Throughput — tokens per second as the server counts them (at each request's end), last ten minutes");
  var occupancyMount = figure("Occupancy — requests processing and queued, last ten minutes");
  section.appendChild(charts);
  // After the verdict, which leads the page, and before the report's tiles.
  var lead = document.querySelector(".verdict") || meta;
  lead.parentNode.insertBefore(section, lead.nextSibling);
  lead.parentNode.insertBefore(strip, section);
  var nav = document.querySelector("nav");
  if (nav) {
    var link = element("a", null, "Live");
    link.href = "#live";
    nav.insertBefore(link, nav.firstChild);
  }
  var plots = [];
  var latest = { x: [], throughput: [[], []], occupancy: [[], []] };

  function palette(forPrint) {
    var style = getComputedStyle(document.documentElement);
    var suffix = forPrint ? "-light" : "";
    function token(name) { return style.getPropertyValue(name + suffix).trim(); }
    return { series: [token("--series-1"), token("--series-2")], grid: token("--grid"),
      axis: token("--axis"), muted: token("--muted") };
  }

  function clockLabel(seconds, withSeconds) {
    var format = { hour: "2-digit", minute: "2-digit" };
    if (withSeconds) { format.second = "2-digit"; }
    return new Date(seconds * 1000).toLocaleTimeString([], format);
  }

  function options(mount, names, stepped, colors) {
    function axis(extra) {
      return Object.assign({ stroke: colors.muted, font: AXIS_FONT, gap: 6, ticks: { show: false },
        grid: { stroke: colors.grid, width: 1 } }, extra);
    }
    // A floor keeps an idle chart from stretching noise over the whole
    // height: ten tokens per second, one request.
    var floor = stepped ? 1 : 10;
    return {
      width: Math.max(280, mount.clientWidth),
      height: HEIGHT,
      legend: { live: true },
      cursor: { y: false, points: { show: false }, drag: { x: false, y: false } },
      scales: {
        x: { time: true },
        y: { range: function (u, min, max) { return [0, Math.max(floor, max == null ? floor : max)]; } }
      },
      axes: [
        axis({
          size: 30,
          space: 90,
          border: { show: true, stroke: colors.axis, width: 1 },
          // Time of day on one line (uPlot's own date labels take two): to
          // the minute, with seconds while the window is under two minutes.
          values: function (u, splits) {
            var brief = splits.length > 1 && splits[splits.length - 1] - splits[0] < 120;
            return splits.map(function (t) { return clockLabel(t, brief); });
          }
        }),
        axis({ size: 48, gap: 8, incrs: stepped ? [1, 2, 5, 10, 20, 50, 100] : undefined })
      ],
      series: [{ value: function (u, value) { return value == null ? "" : clockLabel(value, true); } }]
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
    plots.forEach(function (plot) { plot.destroy(); });
    var colors = palette(forPrint);
    plots = [
      new uPlot(options(throughputMount, ["prompt", "generated"], false, colors),
        [latest.x].concat(latest.throughput), throughputMount),
      new uPlot(options(occupancyMount, ["processing", "queued"], true, colors),
        [latest.x].concat(latest.occupancy), occupancyMount)
    ];
  }

  function number(value, digits) {
    return value == null ? "–" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
  }

  function show(name, value, reason) {
    if (!values[name]) { return; }
    values[name].textContent = value;
    reasons[name].textContent = reason || "";
  }

  // A 12-point sparkline of the ring's last values as an inline polyline.
  function sparkline(series) {
    var points = series.slice(-SPARK).filter(function (value) { return typeof value === "number"; });
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 48 14");
    svg.setAttribute("aria-hidden", "true");
    if (points.length > 1) {
      var max = Math.max.apply(null, points);
      var line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      line.setAttribute("points", points.map(function (value, index) {
        return (index * 48 / (points.length - 1)).toFixed(1) + "," + (13 - (max ? 12 * value / max : 0)).toFixed(1);
      }).join(" "));
      svg.appendChild(line);
    }
    return svg;
  }

  function stripItem(key, label, value, series) {
    var item = stripItems[key];
    if (!item) {
      item = stripItems[key] = element("span");
      strip.appendChild(item);
    }
    while (item.firstChild) { item.removeChild(item.firstChild); }
    if (key === "state") { item.appendChild(element("span", "dot")); }
    item.appendChild(element("span", null, label));
    item.appendChild(element("b", null, value));
    if (series) { item.appendChild(sparkline(series)); }
  }

  function render(data) {
    var samples = Array.isArray(data.samples) ? data.samples : [];
    var cutoff = samples.length ? samples[samples.length - 1].t - WINDOW : 0;
    var x = [], prompt = [], generated = [], processing = [], deferred = [], memory = [];
    samples.forEach(function (sample) {
      if (typeof sample.t !== "number" || sample.t < cutoff) { return; }
      x.push(sample.t);
      prompt.push(typeof sample.prompt_rate === "number" ? sample.prompt_rate : null);
      generated.push(typeof sample.generation_rate === "number" ? sample.generation_rate : null);
      processing.push(typeof sample.processing === "number" ? sample.processing : null);
      deferred.push(typeof sample.deferred === "number" ? sample.deferred : null);
      memory.push(typeof sample.gpu_memory_mib === "number" ? sample.gpu_memory_mib : null);
    });
    latest = { x: x, throughput: [prompt, generated], occupancy: [processing, deferred] };
    plots[0].setData([x, prompt, generated]);
    plots[1].setData([x, processing, deferred]);
    var last = samples[samples.length - 1];
    if (!last) { state.textContent = "no samples yet"; return; }
    var kind = !last.up ? "down" : typeof last.model !== "string" ? "idle" : "up";
    setState(kind);
    var refreshed = " \u00b7 refreshed " + clockLabel(last.t, true);
    if (kind === "down") { state.textContent = "model server not reachable at " + api + " (is the stack up?)" + refreshed; }
    else if (kind === "idle") { state.textContent = "no preset loaded" + refreshed; }
    else if (!last.scraped) { state.textContent = last.model + " loaded, first sample" + refreshed; }
    else { state.textContent = last.model + " loaded" + refreshed; }
    // Why a tile has no number: the reason is the state, then the
    // sampler's own rules (a rate needs two scrapes of one preset).
    var why = kind === "down" ? "server unreachable" : kind === "idle" ? "no preset loaded"
      : !last.scraped ? "first sample" : "";
    var busy = (last.processing || 0) + (last.deferred || 0) > 0;
    // A request shows as occupancy, or, when it fell between two scrapes,
    // as the counters it advanced.
    var seen = x.some(function (t, index) {
      return processing[index] > 0 || deferred[index] > 0 || prompt[index] > 0 || generated[index] > 0;
    });
    show("processing", number(last.processing, 0), why);
    show("deferred", number(last.deferred, 0), why);
    ["prompt", "generation"].forEach(function (name) {
      var rate = last[name === "prompt" ? "prompt_rate" : "generation_rate"];
      if (typeof rate !== "number") { show(name, "–", why || "needs two scrapes"); }
      else if (rate === 0) { show(name, "0.0", busy ? "in progress, counted at the end" : "idle"); }
      else { show(name, number(rate, 1), ""); }
    });
    // The share of drafted tokens the MTP preset accepted since its load;
    // a preset without a draft model has none. The GPU tiles show what the
    // host's nvidia-smi reported beside the scrape, when it has one.
    if (typeof last.acceptance === "number") { show("acceptance", Math.round(100 * last.acceptance) + "%", ""); }
    else { show("acceptance", "–", why || "no draft model"); }
    var total = typeof last.gpu_memory_total_mib === "number" ? " / " + number(last.gpu_memory_total_mib, 0) : "";
    show("memory", number(last.gpu_memory_mib, 0) + (last.gpu_memory_mib == null ? "" : total),
      last.gpu_memory_mib == null ? "GPU query failed" : "in use / in all");
    show("power", number(last.gpu_power_w, 1), last.gpu_power_w == null ? "GPU query failed" : "");
    var quiet = kind === "up" && last.scraped && !seen;
    empties.forEach(function (empty) {
      empty.textContent = "no requests since " + clockLabel(x[0], true);
      empty.hidden = !quiet;
    });
    stripItem("state", "", typeof last.model === "string" ? last.model : kind === "down" ? "unreachable" : "no preset");
    stripItem("busy", "processing / queued", number(last.processing, 0) + " / " + number(last.deferred, 0), processing);
    stripItem("generated", "generated tok/s", number(last.generation_rate, 1), generated);
    if (gpu) { stripItem("memory", "GPU MiB", number(last.gpu_memory_mib, 0), memory); }
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
      .catch(function () {
        setState("down");
        state.textContent = "stats server unreachable";
        Object.keys(values).forEach(function (name) { show(name, "\u2013", "stats server unreachable"); });
      })
      .then(schedule);
  }

  build(false);
  poll();
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && timer === null) { poll(); }
  });
  if (typeof IntersectionObserver !== "undefined") {
    new IntersectionObserver(function (entries) {
      var entry = entries[0];
      strip.classList.toggle("shown", !entry.isIntersecting && entry.boundingClientRect.top < 0);
    }).observe(tiles);
  }
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(function () {
      plots.forEach(function (plot, index) {
        var mount = index === 0 ? throughputMount : occupancyMount;
        var width = Math.max(280, mount.clientWidth);
        if (Math.abs(plot.width - width) > 1) { plot.setSize({ width: width, height: HEIGHT }); }
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
