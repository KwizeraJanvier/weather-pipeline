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
        <td>${s.city}</td>
        <td>${s.rain_days} / ${s.total_days}</td>
        <td>${s.rain_pct}%</td>
        <td>${s.avg_temp_rain_day ?? "-"}&deg;C</td>
        <td>${s.avg_temp_non_rain_day ?? "-"}&deg;C</td>
      </tr>`
    )
    .join("");
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
  chart = new Chart(document.getElementById("temp-chart"), {
    type: "line",
    data: {
      datasets: [
        { label: "Actual max temp (°C)", data: actualPoints, borderColor: "#2f6fed", backgroundColor: "#2f6fed", tension: 0.25 },
        { label: "Forecast max temp (°C)", data: forecastPoints, borderColor: "#f2a93c", backgroundColor: "#f2a93c", borderDash: [6, 4], tension: 0.25 },
      ],
    },
    options: {
      scales: {
        x: { type: "time", time: { unit: "day" } },
        y: { title: { display: true, text: "°C" } },
      },
    },
  });

  status.textContent = `${actual.length} actual days, ${forecast.length} forecast days`;
}

async function initDashboard() {
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

async function loadTasks(runId) {
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
