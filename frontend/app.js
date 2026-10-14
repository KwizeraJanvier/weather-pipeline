let chart;
let currentUser = null;

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location.href = "/login.html";
    throw new Error("not logged in");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${url} -> ${res.status}`);
  return data;
}

// ---- Auth / shell ----------------------------------------------------

async function initShell() {
  currentUser = await fetchJSON("/api/auth/me");
  document.getElementById("user-email").textContent = currentUser.email;
  document.getElementById("user-role").textContent = currentUser.role;
  document.getElementById("user-avatar").textContent = currentUser.email.charAt(0).toUpperCase();
  if (currentUser.role === "admin") {
    document.getElementById("nav-database").hidden = false;
    document.getElementById("nav-audit").hidden = false;
  }

  document.getElementById("logout-btn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login.html";
  });

  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.addEventListener("click", () => showSection(btn.dataset.section));
  });
}

function showSection(name) {
  document.querySelectorAll(".section").forEach((s) => (s.hidden = s.id !== `section-${name}`));
  document.querySelectorAll(".nav-link").forEach((b) => b.classList.toggle("active", b.dataset.section === name));
  if (name === "database" && !tablesLoaded) loadTables();
  if (name === "pipeline" && !runsLoaded) loadRuns();
  if (name === "metabase" && !metabaseLoaded) loadMetabase();
  if (name === "audit") loadAuditLog();
}

// ---- Dashboard ---------------------------------------------------------

async function loadCities() {
  const cities = await fetchJSON("/api/cities");
  const select = document.getElementById("city-select");
  select.innerHTML = cities.map((c) => `<option value="${c}">${c}</option>`).join("");
}

async function loadRainStats() {
  const stats = await fetchJSON("/api/rain-stats");
  document.querySelector("#rain-table tbody").innerHTML = stats
    .map(
      (s) => `
      <tr>
        <td><strong>${s.city}</strong></td>
        <td>${s.rain_days} / ${s.total_days}</td>
        <td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, s.rain_pct)}%"></div></div>${s.rain_pct}%</div></td>
        <td>${s.avg_temp_rain_day ?? "-"}&deg;C</td>
        <td>${s.avg_temp_non_rain_day ?? "-"}&deg;C</td>
      </tr>`
    )
    .join("");
  const days = Math.max(0, ...stats.map((s) => s.total_days));
  document.getElementById("kpi-cities").textContent = stats.length;
  document.getElementById("kpi-days").textContent = days;
}

async function loadCityChart(city) {
  const status = document.getElementById("chart-status");
  status.textContent = "Loading...";
  const [actual, forecast] = await Promise.all([
    fetchJSON(`/api/weather/${encodeURIComponent(city)}?days=30`),
    fetchJSON(`/api/forecast/${encodeURIComponent(city)}`),
  ]);

  const actualPoints = actual.map((r) => ({ x: r.date, y: r.temperature_max_c }));
  const forecastPoints = forecast.map((r) => ({ x: r.date, y: r.predicted_temp_max_c }));

  if (chart) chart.destroy();
  const ctx = document.getElementById("temp-chart").getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 340);
  grad.addColorStop(0, "rgba(29,111,232,0.28)");
  grad.addColorStop(1, "rgba(29,111,232,0.00)");
  chart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        { label: "Actual max temp (°C)", data: actualPoints, borderColor: "#1d6fe8", backgroundColor: grad, fill: true, borderWidth: 2.5, pointRadius: 0, pointHoverRadius: 5, tension: 0.35 },
        { label: "Forecast max temp (°C)", data: forecastPoints, borderColor: "#f2a93c", backgroundColor: "#f2a93c", borderWidth: 2.5, borderDash: [7, 5], pointRadius: 3, pointHoverRadius: 6, tension: 0.35 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", align: "end", labels: { usePointStyle: true, boxWidth: 8, color: "#5f6f8c" } },
        tooltip: { backgroundColor: "#0b1530", padding: 10, cornerRadius: 8, displayColors: true },
      },
      scales: {
        x: { type: "time", time: { unit: "day", tooltipFormat: "MMM d, yyyy" }, grid: { display: false }, ticks: { color: "#5f6f8c", maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { grid: { color: "rgba(20,50,110,0.08)" }, ticks: { color: "#5f6f8c", callback: (v) => `${v}°` } },
      },
    },
  });

  const lastActual = actual[actual.length - 1];
  const firstForecast = forecast[0];
  document.getElementById("kpi-latest").textContent = lastActual ? `${lastActual.temperature_max_c}°C` : "-";
  document.getElementById("kpi-latest-sub").textContent = lastActual ? `${city} · ${lastActual.date}` : "";
  document.getElementById("kpi-forecast").textContent = firstForecast ? `${Number(firstForecast.predicted_temp_max_c).toFixed(1)}°C` : "-";
  document.getElementById("kpi-forecast-sub").textContent = firstForecast ? `${city} · ${firstForecast.date}` : "";

  status.textContent = `${actual.length} actual days, ${forecast.length} forecast days`;
}

async function loadPipelineKpi() {
  try {
    const runs = await fetchJSON("/api/pipeline/runs");
    const el = document.getElementById("kpi-pipeline");
    if (!runs.length) {
      el.textContent = "No runs yet";
      return;
    }
    const r = runs[0];
    el.innerHTML = `<span class="pill pill-${r.state}">${r.state}</span>`;
    document.getElementById("kpi-pipeline-sub").textContent = fmtTime(r.end_date || r.start_date);
  } catch (err) {
    document.getElementById("kpi-pipeline").textContent = "n/a";
  }
}

async function initDashboard() {
  loadPipelineKpi();
  await loadCities();
  await loadRainStats();
  const select = document.getElementById("city-select");
  if (select.options.length) await loadCityChart(select.value);
  select.addEventListener("change", () => loadCityChart(select.value));
  startAutoRefresh();
}

// The pipeline updates once a day, so there's nothing to gain from
// WebSockets/true streaming - this just polls often enough that new data
// shows up without a manual reload, and pauses while the tab isn't visible
// so it's not doing pointless work in a background tab.
const REFRESH_INTERVAL_MS = 60_000;
let refreshTimer = null;

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAutoRefresh();
    else startAutoRefresh();
  });
}

function stopAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
}

async function refreshDashboard() {
  const select = document.getElementById("city-select");
  await Promise.all([loadRainStats(), select.options.length ? loadCityChart(select.value) : Promise.resolve()]);
  const indicator = document.getElementById("live-indicator");
  indicator.title = `Last updated ${new Date().toLocaleTimeString()}`;
}

// ---- Metabase (embedded dashboard) --------------------------------------

let metabaseLoaded = false;

async function loadMetabase() {
  metabaseLoaded = true;
  const status = document.getElementById("metabase-status");
  const frame = document.getElementById("metabase-frame");
  try {
    const { url } = await fetchJSON("/api/metabase/embed-url");
    frame.src = url;
    frame.hidden = false;
    status.hidden = true;
  } catch (err) {
    metabaseLoaded = false; // allow retry once it's configured
    status.textContent = err.message;
  }
}

// ---- Database (admin only) ---------------------------------------------

let tablesLoaded = false;

function renderResultTable(el, columns, rows) {
  if (!columns.length) {
    el.innerHTML = "<tbody><tr><td>No rows</td></tr></tbody>";
    return;
  }
  const head = `<thead><tr>${columns.map((c) => `<th>${c}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${rows
    .map((row) => `<tr>${columns.map((c) => `<td>${row[c] ?? ""}</td>`).join("")}</tr>`)
    .join("")}</tbody>`;
  el.innerHTML = head + body;
}

async function loadTables() {
  tablesLoaded = true;
  const tables = await fetchJSON("/api/db/tables");
  const picker = document.getElementById("table-picker");
  picker.innerHTML =
    `<option value="">Pick a table to insert a starter query...</option>` +
    tables.map((t) => `<option value="${t.table_schema}.${t.table_name}">${t.table_schema}.${t.table_name}</option>`).join("");
  picker.addEventListener("change", () => {
    if (picker.value) {
      document.getElementById("sql-box").value = `select * from ${picker.value} order by date desc limit 20`;
    }
  });
}

async function runQuery() {
  const sql = document.getElementById("sql-box").value;
  const status = document.getElementById("query-status");
  status.textContent = "Running...";
  try {
    const result = await fetchJSON("/api/db/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql }),
    });
    renderResultTable(document.getElementById("query-result-table"), result.columns, result.rows);
    status.textContent = `${result.rows.length} rows`;
  } catch (err) {
    status.textContent = err.message;
  }
}

// ---- Pipeline status -----------------------------------------------------

let runsLoaded = false;

function fmtTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "-";
}

async function loadRuns() {
  runsLoaded = true;
  const runs = await fetchJSON("/api/pipeline/runs");
  const tbody = document.querySelector("#runs-table tbody");
  tbody.innerHTML = runs
    .map(
      (r) => `
      <tr class="run-row" data-run-id="${r.run_id}">
        <td>${r.run_id}</td>
        <td>${r.run_type}</td>
        <td><span class="pill pill-${r.state}">${r.state}</span></td>
        <td>${fmtTime(r.start_date)}</td>
        <td>${fmtTime(r.end_date)}</td>
      </tr>`
    )
    .join("");
  tbody.querySelectorAll(".run-row").forEach((row) => {
    row.addEventListener("click", () => loadTasks(row.dataset.runId));
  });
  if (runs.length) loadTasks(runs[0].run_id);
}

const STEP_INFO = {
  extract_weather: ["Extract", "Open-Meteo API → raw layer"],
  dbt_run: ["Transform", "dbt: staging → marts"],
  forecast_weather: ["Forecast", "7-day temperature model"],
};

function duration(start, end) {
  if (!start || !end) return "";
  const sec = Math.max(0, Math.round((new Date(end) - new Date(start)) / 1000));
  return sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`;
}

async function loadTasks(runId) {
  document.querySelectorAll(".run-row").forEach((r) => r.classList.toggle("selected", r.dataset.runId === runId));
  const tasks = await fetchJSON(`/api/pipeline/runs/${encodeURIComponent(runId)}/tasks`);
  document.querySelector("#tasks-table tbody").innerHTML = tasks
    .map(
      (t) => `
      <tr>
        <td>${t.task_id}</td>
        <td><span class="pill pill-${t.state}">${t.state ?? "pending"}</span></td>
        <td>${fmtTime(t.start_date)}</td>
        <td>${fmtTime(t.end_date)}</td>
      </tr>`
    )
    .join("");

  document.getElementById("flow-sub").textContent = `Run ${runId}`;
  document.getElementById("flow").innerHTML = tasks
    .map((t) => {
      const [title, desc] = STEP_INFO[t.task_id] || [t.task_id, ""];
      const state = t.state ?? "pending";
      return `<div class="flow-node s-${state}">
        <h3>${title}</h3><p>${desc}</p>
        <span class="pill pill-${state}">${state}</span>
        <span class="status" style="margin-left:6px">${duration(t.start_date, t.end_date)}</span>
      </div>`;
    })
    .join('<div class="flow-arrow">&rarr;</div>');
}

// ---- Audit log (admin only) ----------------------------------------------

async function loadAuditLog() {
  const entries = await fetchJSON("/api/audit/log");
  document.querySelector("#audit-table tbody").innerHTML = entries
    .map(
      (e) => `
      <tr>
        <td>${fmtTime(e.created_at)}</td>
        <td>${e.email}</td>
        <td><span class="pill pill-${e.action.includes("fail") || e.action.includes("block") ? "failed" : "success"}">${e.action}</span></td>
        <td class="audit-detail">${e.detail ?? ""}</td>
      </tr>`
    )
    .join("");
}

// ---- Boot ----------------------------------------------------------------

async function init() {
  try {
    await initShell();
    await initDashboard();
    document.getElementById("run-query-btn").addEventListener("click", runQuery);
  } catch (err) {
    console.error(err);
  }
}

init();
