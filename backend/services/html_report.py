from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timedelta

from backend.models import ParsedData
from backend.services.currency import convert_to_eur
from backend.services.report_generator import _category_totals, _filter_expenses, _personal_stats


def _time_series(expenses) -> tuple[list[dict], str]:
    """Daily totals, bucketed to weekly if the trip spans more than ~45 days
    (otherwise a multi-month trip would cram hundreds of x-axis points)."""
    daily: dict = defaultdict(float)
    for e in expenses:
        if e.date:
            daily[e.date.date()] += e.amount
    if not daily:
        return [], "day"

    dates = sorted(daily.keys())
    span_days = (dates[-1] - dates[0]).days
    if span_days > 45:
        weekly: dict = defaultdict(float)
        for d, amt in daily.items():
            week_start = d - timedelta(days=d.weekday())
            weekly[week_start] += amt
        points = sorted(weekly.items())
        bucket = "week"
    else:
        points = sorted(daily.items())
        bucket = "day"

    return [{"date": d.isoformat(), "amount": round(amt, 2)} for d, amt in points], bucket


def _balance_series(data: ParsedData, expenses) -> list[dict]:
    paid_by: dict[str, float] = defaultdict(float)
    for e in expenses:
        paid_by[e.payer] += e.amount
    grand_total = sum(e.amount for e in expenses)
    share_per = grand_total / len(data.members) if data.members else 0.0
    return [
        {
            "member": b.member,
            "paid": round(paid_by.get(b.member, 0.0), 2),
            "share": round(share_per, 2),
            "balance": round(paid_by.get(b.member, 0.0) - share_per, 2),
        }
        for b in data.balances
    ]


def _build_payload(
    data: ParsedData,
    trip_name: str,
    report_mode: str,
    personal_member: str | None,
    exclude_personal_expenses: bool,
    exclude_categories: list[str] | None,
) -> dict:
    data = convert_to_eur(data)
    expenses = _filter_expenses(data, report_mode, personal_member, exclude_personal_expenses, exclude_categories)

    totals = _category_totals(expenses)
    grand_total = sum(totals.values())
    categories = [
        {"category": cat, "amount": round(amt, 2), "pct": round(amt / grand_total * 100, 1) if grand_total else 0}
        for cat, amt in sorted(totals.items(), key=lambda x: -x[1])
    ]

    time_series, bucket = _time_series(expenses)

    personal_stats = None
    if report_mode == "personal" and personal_member:
        stats = _personal_stats(data, personal_member)
        personal_stats = {
            "member": personal_member,
            "global_total": round(stats["global_total"], 2),
            "global_per_person": round(stats["global_per_person"], 2),
            "personal_paid": round(stats["personal_paid"], 2),
            "personal_share": round(stats["personal_share"], 2),
            "diff_from_avg": round(stats["diff_from_avg"], 2),
        }

    return {
        "trip_name": trip_name,
        "report_mode": report_mode,
        "personal_member": personal_member,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "grand_total": round(grand_total, 2),
        "item_count": len(expenses),
        "categories": categories,
        "time_series": time_series,
        "time_series_bucket": bucket,
        # Balance sheet only makes sense for the whole group
        "balances": _balance_series(data, [e for e in data.expenses if not e.is_reimbursement]) if report_mode == "global" else [],
        "personal_stats": personal_stats,
    }


def generate_html_report(
    data: ParsedData,
    trip_name: str,
    report_mode: str = "global",
    personal_member: str | None = None,
    exclude_personal_expenses: bool = False,
    exclude_categories: list[str] | None = None,
) -> str:
    payload = _build_payload(
        data, trip_name, report_mode, personal_member, exclude_personal_expenses, exclude_categories,
    )
    # Defense-in-depth: a category name (user-editable, can come from the AI or
    # from Tricount's own category_custom field) could contain "</script>" —
    # escaping the closing tag sequence keeps it inert wherever it's embedded.
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return _HTML_TEMPLATE.replace("__TITLE__", _escape_html(trip_name)).replace("__DATA_JSON__", data_json)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Charts</title>
<style>
  :root {
    color-scheme: light;
    --surface:     #fcfcfb;
    --page:        #f9f9f7;
    --ink:         #0b0b0b;
    --ink-2:       #52514e;
    --ink-muted:   #898781;
    --grid:        #e1e0d9;
    --border:      rgba(11,11,11,0.14);
    --series-1:    #2a78d6;
    --good:        #1a7a3c;
    --critical:    #c0392b;
    --tooltip-bg:  #0b0b0b;
    --tooltip-ink: #ffffff;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --surface:   #1a1a19;
      --page:      #0d0d0d;
      --ink:       #ffffff;
      --ink-2:     #c3c2b7;
      --ink-muted: #898781;
      --grid:      #2c2c2a;
      --border:    rgba(255,255,255,0.16);
      --series-1:  #3987e5;
      --good:      #2fae5d;
      --critical:  #e0665a;
      --tooltip-bg: #ffffff;
      --tooltip-ink: #0b0b0b;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface:   #1a1a19;
    --page:      #0d0d0d;
    --ink:       #ffffff;
    --ink-2:     #c3c2b7;
    --ink-muted: #898781;
    --grid:      #2c2c2a;
    --border:    rgba(255,255,255,0.16);
    --series-1:  #3987e5;
    --good:      #2fae5d;
    --critical:  #e0665a;
    --tooltip-bg: #ffffff;
    --tooltip-ink: #0b0b0b;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--page);
    color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  main { max-width: 880px; margin: 0 auto; padding: 32px 20px 60px; }

  header { margin-bottom: 28px; }
  h1 {
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.01em;
    margin: 0 0 6px;
  }
  .meta { color: var(--ink-2); font-size: 13px; }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 20px 20px 8px;
    margin-bottom: 20px;
  }
  .card h2 {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-2);
    margin: 0 0 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--grid);
  }
  .card .subtotal {
    font-size: 20px;
    font-weight: 800;
    margin: -8px 0 16px;
    font-variant-numeric: tabular-nums;
  }

  /* ── Horizontal bar chart (category breakdown) ── */
  .barrow {
    display: grid;
    grid-template-columns: minmax(110px, 34%) 1fr auto;
    align-items: center;
    gap: 10px;
    padding: 5px 0;
    cursor: default;
  }
  .barrow .label {
    font-size: 12.5px;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .barrow .track {
    position: relative;
    height: 18px;
    background: var(--grid);
  }
  .barrow .fill {
    position: absolute;
    inset: 0 auto 0 0;
    height: 100%;
    background: var(--series-1);
    border-radius: 0 4px 4px 0;
    transition: opacity 0.1s;
  }
  .barrow:hover .fill { opacity: 0.8; }
  .barrow .value {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    color: var(--ink-2);
    min-width: 78px;
    text-align: right;
  }

  /* ── Diverging bar chart (balance) ── */
  .divrow {
    display: grid;
    grid-template-columns: minmax(90px, 26%) 1fr auto;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
  }
  .divrow .label { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .divrow .track {
    position: relative;
    height: 18px;
    background: var(--grid);
  }
  .divrow .baseline {
    position: absolute;
    top: -3px; bottom: -3px; left: 50%;
    width: 1px;
    background: var(--ink-muted);
  }
  .divrow .fill {
    position: absolute;
    top: 0; bottom: 0;
    border-radius: 4px;
  }
  .divrow .fill.pos { left: 50%; background: var(--good); border-radius: 0 4px 4px 0; }
  .divrow .fill.neg { right: 50%; background: var(--critical); border-radius: 4px 0 0 4px; }
  .divrow .value { font-size: 12px; font-variant-numeric: tabular-nums; min-width: 84px; text-align: right; }
  .divrow .value.pos { color: var(--good); }
  .divrow .value.neg { color: var(--critical); }

  /* ── Line chart (spending over time) ── */
  .linechart { position: relative; width: 100%; }
  .linechart svg { display: block; width: 100%; height: auto; overflow: visible; }
  .linechart .grid-line { stroke: var(--grid); stroke-width: 1; }
  .linechart .axis-label { fill: var(--ink-muted); font-size: 10px; font-family: inherit; }
  .linechart .area { fill: var(--series-1); opacity: 0.1; }
  .linechart .line { fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .linechart .dot { fill: var(--series-1); stroke: var(--surface); stroke-width: 2; opacity: 0; transition: opacity 0.1s; }
  .linechart .crosshair { stroke: var(--ink-muted); stroke-width: 1; opacity: 0; pointer-events: none; }
  .linechart .hit { fill: transparent; }

  /* ── Tooltip ── */
  .tooltip {
    position: fixed;
    pointer-events: none;
    background: var(--tooltip-bg);
    color: var(--tooltip-ink);
    font-size: 12px;
    padding: 6px 10px;
    border-radius: 3px;
    opacity: 0;
    transform: translate(-50%, -100%);
    white-space: nowrap;
    z-index: 10;
    transition: opacity 0.08s;
  }
  .tooltip .tt-value { font-weight: 700; }
  .tooltip .tt-label { color: var(--tooltip-ink); opacity: 0.75; margin-top: 1px; }

  /* ── Table view (accessibility fallback) ── */
  details.table-view { margin: 4px 0 16px; }
  details.table-view summary {
    cursor: pointer;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ink-2);
    padding: 4px 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
    margin-top: 8px;
  }
  table th {
    text-align: left;
    font-size: 10px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ink-muted);
    border-bottom: 1px solid var(--grid);
    padding: 5px 8px 5px 0;
  }
  table td {
    padding: 5px 8px 5px 0;
    border-bottom: 1px solid var(--grid);
    font-variant-numeric: tabular-nums;
  }
  table td:last-child, table th:last-child { text-align: right; }

  .empty-note { color: var(--ink-muted); font-size: 13px; padding: 8px 0 16px; }

  footer { color: var(--ink-muted); font-size: 11px; text-align: center; margin-top: 24px; }
</style>
</head>
<body>
<main>
  <header>
    <h1 id="hdr-title"></h1>
    <div class="meta" id="hdr-meta"></div>
  </header>

  <section class="card" id="card-categories">
    <h2>Spending by category</h2>
    <div class="subtotal" id="categories-total"></div>
    <div id="categories-chart"></div>
    <details class="table-view">
      <summary>Table view</summary>
      <table id="categories-table"><thead><tr><th>Category</th><th>Amount</th><th>%</th></tr></thead><tbody></tbody></table>
    </details>
  </section>

  <section class="card" id="card-timeseries">
    <h2>Spending over time</h2>
    <div class="linechart" id="timeseries-chart"></div>
    <details class="table-view">
      <summary>Table view</summary>
      <table id="timeseries-table"><thead><tr><th>Date</th><th>Amount</th></tr></thead><tbody></tbody></table>
    </details>
  </section>

  <section class="card" id="card-balances" style="display:none">
    <h2>Balance sheet</h2>
    <div id="balances-chart"></div>
    <details class="table-view">
      <summary>Table view</summary>
      <table id="balances-table"><thead><tr><th>Participant</th><th>Paid</th><th>Fair share</th><th>Balance</th></tr></thead><tbody></tbody></table>
    </details>
  </section>

  <section class="card" id="card-personal" style="display:none">
    <h2>Personal vs global</h2>
    <div id="personal-chart"></div>
  </section>

  <footer>Generated by EasyExpense</footer>
</main>

<div class="tooltip" id="tooltip" role="tooltip"></div>

<script>
(function () {
  "use strict";
  var DATA = __DATA_JSON__;

  var fmt = function (n) {
    return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
  };
  var text = function (el, str) { el.textContent = str; };

  var tooltip = document.getElementById("tooltip");
  function showTooltip(x, y, valueStr, labelStr) {
    tooltip.innerHTML = "";
    var v = document.createElement("div");
    v.className = "tt-value";
    v.textContent = valueStr;
    var l = document.createElement("div");
    l.className = "tt-label";
    l.textContent = labelStr;
    tooltip.appendChild(v);
    tooltip.appendChild(l);
    tooltip.style.left = x + "px";
    tooltip.style.top = (y - 10) + "px";
    tooltip.style.opacity = "1";
  }
  function hideTooltip() { tooltip.style.opacity = "0"; }

  // ── Header ──
  text(document.getElementById("hdr-title"), DATA.trip_name);
  var metaParts = ["Generated " + DATA.generated];
  if (DATA.report_mode === "personal" && DATA.personal_member) {
    metaParts.push("Report for " + DATA.personal_member);
  } else {
    metaParts.push(DATA.item_count + " expenses");
  }
  text(document.getElementById("hdr-meta"), metaParts.join(" · "));

  // ── Category bar chart ──
  (function renderCategories() {
    var cats = DATA.categories;
    text(document.getElementById("categories-total"), fmt(DATA.grand_total));
    var chart = document.getElementById("categories-chart");
    var tbody = document.querySelector("#categories-table tbody");
    if (!cats.length) {
      chart.innerHTML = '<div class="empty-note">No expenses in this view.</div>';
      return;
    }
    var max = cats[0].amount;
    cats.forEach(function (c) {
      var row = document.createElement("div");
      row.className = "barrow";

      var label = document.createElement("div");
      label.className = "label";
      label.textContent = c.category;

      var track = document.createElement("div");
      track.className = "track";
      var fill = document.createElement("div");
      fill.className = "fill";
      fill.style.width = (max ? (c.amount / max * 100) : 0) + "%";
      track.appendChild(fill);

      var value = document.createElement("div");
      value.className = "value";
      value.textContent = fmt(c.amount);

      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(value);

      var onMove = function (ev) {
        showTooltip(ev.clientX, ev.clientY, fmt(c.amount) + " (" + c.pct + "%)", c.category);
      };
      row.addEventListener("pointermove", onMove);
      row.addEventListener("pointerenter", onMove);
      row.addEventListener("pointerleave", hideTooltip);
      row.tabIndex = 0;
      row.addEventListener("focus", function () {
        var r = row.getBoundingClientRect();
        showTooltip(r.left + r.width / 2, r.top, fmt(c.amount) + " (" + c.pct + "%)", c.category);
      });
      row.addEventListener("blur", hideTooltip);

      chart.appendChild(row);

      var tr = document.createElement("tr");
      var tds = [c.category, fmt(c.amount), c.pct + "%"];
      tds.forEach(function (t) {
        var td = document.createElement("td");
        td.textContent = t;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  })();

  // ── Time series line chart ──
  (function renderTimeSeries() {
    var points = DATA.time_series;
    var container = document.getElementById("timeseries-chart");
    var tbody = document.querySelector("#timeseries-table tbody");
    if (!points.length) {
      container.innerHTML = '<div class="empty-note">No dated expenses in this view.</div>';
      return;
    }

    var W = 800, H = 220, padL = 46, padR = 10, padT = 14, padB = 24;
    var innerW = W - padL - padR, innerH = H - padT - padB;
    var maxY = Math.max.apply(null, points.map(function (p) { return p.amount; })) || 1;

    function xAt(i) { return padL + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW); }
    function yAt(v) { return padT + innerH - (v / maxY) * innerH; }

    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    // Gridlines (0, mid, max)
    [0, 0.5, 1].forEach(function (frac) {
      var y = padT + innerH * (1 - frac);
      var gl = document.createElementNS(svgNS, "line");
      gl.setAttribute("class", "grid-line");
      gl.setAttribute("x1", padL); gl.setAttribute("x2", W - padR);
      gl.setAttribute("y1", y); gl.setAttribute("y2", y);
      svg.appendChild(gl);
      var lbl = document.createElementNS(svgNS, "text");
      lbl.setAttribute("class", "axis-label");
      lbl.setAttribute("x", 2); lbl.setAttribute("y", y + 3);
      lbl.textContent = Math.round(maxY * frac).toLocaleString();
      svg.appendChild(lbl);
    });

    // Area + line
    var areaD = "M " + xAt(0) + " " + yAt(0);
    var lineD = "M " + xAt(0) + " " + yAt(points[0].amount);
    points.forEach(function (p, i) {
      if (i > 0) lineD += " L " + xAt(i) + " " + yAt(p.amount);
      areaD += " L " + xAt(i) + " " + yAt(p.amount);
    });
    areaD += " L " + xAt(points.length - 1) + " " + yAt(0) + " Z";

    var area = document.createElementNS(svgNS, "path");
    area.setAttribute("class", "area");
    area.setAttribute("d", areaD);
    svg.appendChild(area);

    var line = document.createElementNS(svgNS, "path");
    line.setAttribute("class", "line");
    line.setAttribute("d", lineD);
    svg.appendChild(line);

    // Sparse x-axis labels (first, middle, last — at most ~6)
    var step = Math.max(1, Math.ceil(points.length / 6));
    points.forEach(function (p, i) {
      if (i % step !== 0 && i !== points.length - 1) return;
      var lbl = document.createElementNS(svgNS, "text");
      lbl.setAttribute("class", "axis-label");
      lbl.setAttribute("x", xAt(i));
      lbl.setAttribute("y", H - 6);
      lbl.setAttribute("text-anchor", i === 0 ? "start" : (i === points.length - 1 ? "end" : "middle"));
      lbl.textContent = p.date.slice(5);
      svg.appendChild(lbl);
    });

    // Crosshair + dot
    var crosshair = document.createElementNS(svgNS, "line");
    crosshair.setAttribute("class", "crosshair");
    crosshair.setAttribute("y1", padT); crosshair.setAttribute("y2", H - padB);
    svg.appendChild(crosshair);

    var dot = document.createElementNS(svgNS, "circle");
    dot.setAttribute("class", "dot");
    dot.setAttribute("r", 4);
    svg.appendChild(dot);

    // Hit layer: one rect per point, hit area wider than the point spacing
    points.forEach(function (p, i) {
      var hit = document.createElementNS(svgNS, "rect");
      hit.setAttribute("class", "hit");
      var slot = innerW / points.length;
      hit.setAttribute("x", Math.max(padL, xAt(i) - slot / 2));
      hit.setAttribute("y", padT);
      hit.setAttribute("width", Math.max(slot, 4));
      hit.setAttribute("height", innerH);
      hit.style.cursor = "crosshair";
      var activate = function (ev) {
        crosshair.setAttribute("x1", xAt(i)); crosshair.setAttribute("x2", xAt(i));
        crosshair.style.opacity = "1";
        dot.setAttribute("cx", xAt(i)); dot.setAttribute("cy", yAt(p.amount));
        dot.style.opacity = "1";
        var clientX = ev.clientX, clientY = ev.clientY;
        if (ev.type === "focus") {
          var r = hit.getBoundingClientRect();
          clientX = r.left + r.width / 2; clientY = r.top;
        }
        showTooltip(clientX, clientY, fmt(p.amount), p.date);
      };
      hit.addEventListener("pointerenter", activate);
      hit.addEventListener("pointermove", activate);
      hit.addEventListener("pointerleave", function () {
        crosshair.style.opacity = "0"; dot.style.opacity = "0"; hideTooltip();
      });
      hit.tabIndex = 0;
      hit.addEventListener("focus", activate);
      hit.addEventListener("blur", function () {
        crosshair.style.opacity = "0"; dot.style.opacity = "0"; hideTooltip();
      });
      svg.appendChild(hit);

      var tr = document.createElement("tr");
      [p.date, fmt(p.amount)].forEach(function (t) {
        var td = document.createElement("td");
        td.textContent = t;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });

    container.appendChild(svg);
  })();

  // ── Balance sheet diverging bars ──
  (function renderBalances() {
    var balances = DATA.balances;
    if (!balances.length) return;
    document.getElementById("card-balances").style.display = "";
    var chart = document.getElementById("balances-chart");
    var tbody = document.querySelector("#balances-table tbody");
    var maxAbs = Math.max.apply(null, balances.map(function (b) { return Math.abs(b.balance); })) || 1;

    balances.forEach(function (b) {
      var row = document.createElement("div");
      row.className = "divrow";

      var label = document.createElement("div");
      label.className = "label";
      label.textContent = b.member;

      var track = document.createElement("div");
      track.className = "track";
      var baseline = document.createElement("div");
      baseline.className = "baseline";
      track.appendChild(baseline);

      var fill = document.createElement("div");
      var pct = Math.abs(b.balance) / maxAbs * 50;
      fill.className = "fill " + (b.balance >= 0 ? "pos" : "neg");
      fill.style.width = pct + "%";
      track.appendChild(fill);

      var value = document.createElement("div");
      value.className = "value " + (b.balance >= 0 ? "pos" : "neg");
      value.textContent = (b.balance >= 0 ? "+" : "") + fmt(b.balance);

      row.appendChild(label);
      row.appendChild(track);
      row.appendChild(value);

      var onMove = function (ev) {
        showTooltip(ev.clientX, ev.clientY, (b.balance >= 0 ? "+" : "") + fmt(b.balance), "Paid " + fmt(b.paid) + " — fair share " + fmt(b.share));
      };
      row.addEventListener("pointermove", onMove);
      row.addEventListener("pointerenter", onMove);
      row.addEventListener("pointerleave", hideTooltip);
      row.tabIndex = 0;
      row.addEventListener("focus", function () {
        var r = row.getBoundingClientRect();
        showTooltip(r.left + r.width / 2, r.top, (b.balance >= 0 ? "+" : "") + fmt(b.balance), "Paid " + fmt(b.paid) + " — fair share " + fmt(b.share));
      });
      row.addEventListener("blur", hideTooltip);

      chart.appendChild(row);

      var tr = document.createElement("tr");
      [b.member, fmt(b.paid), fmt(b.share), (b.balance >= 0 ? "+" : "") + fmt(b.balance)].forEach(function (t) {
        var td = document.createElement("td");
        td.textContent = t;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  })();

  // ── Personal vs global ──
  (function renderPersonal() {
    var s = DATA.personal_stats;
    if (!s) return;
    document.getElementById("card-personal").style.display = "";
    var chart = document.getElementById("personal-chart");
    var rows = [
      { label: s.member + " — allocated share", amount: s.personal_share },
      { label: "Fair share (average)", amount: s.global_per_person },
    ];
    var max = Math.max(rows[0].amount, rows[1].amount) || 1;
    rows.forEach(function (r) {
      var row = document.createElement("div");
      row.className = "barrow";
      var label = document.createElement("div");
      label.className = "label";
      label.textContent = r.label;
      var track = document.createElement("div");
      track.className = "track";
      var fill = document.createElement("div");
      fill.className = "fill";
      fill.style.width = (r.amount / max * 100) + "%";
      track.appendChild(fill);
      var value = document.createElement("div");
      value.className = "value";
      value.textContent = fmt(r.amount);
      row.appendChild(label); row.appendChild(track); row.appendChild(value);
      chart.appendChild(row);
    });
    var diffNote = document.createElement("div");
    diffNote.className = "meta";
    diffNote.style.marginTop = "10px";
    var sign = s.diff_from_avg >= 0 ? "+" : "";
    diffNote.textContent = "Difference from fair share: " + sign + fmt(s.diff_from_avg);
    chart.appendChild(diffNote);
  })();
})();
</script>
</body>
</html>
"""
