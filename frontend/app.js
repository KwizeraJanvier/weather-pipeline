const citySelect = document.getElementById("city-select");
const chartStatus = document.getElementById("chart-status");
const rainTableBody = document.querySelector("#rain-table tbody");
let chart;

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function loadCities() {
  const cities = await fetchJSON("/api/cities");
  citySelect.innerHTML = cities.map((c) => `<option value="${c}">${c}</option>`).join("");
}

async function loadRainStats() {
  const stats = await fetchJSON("/api/rain-stats");
  rainTableBody.innerHTML = stats
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
  chartStatus.textContent = "Loading...";
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
        {
          label: "Actual max temp (°C)",
          data: actualPoints,
          borderColor: "#2f6fed",
          backgroundColor: "#2f6fed",
          tension: 0.25,
        },
        {
          label: "Forecast max temp (°C)",
          data: forecastPoints,
          borderColor: "#f2a93c",
          backgroundColor: "#f2a93c",
          borderDash: [6, 4],
          tension: 0.25,
        },
      ],
    },
    options: {
      scales: {
        x: { type: "time", time: { unit: "day" } },
        y: { title: { display: true, text: "°C" } },
      },
    },
  });

  chartStatus.textContent = `${actual.length} actual days, ${forecast.length} forecast days`;
}

async function init() {
  try {
    await loadCities();
    await loadRainStats();
    if (citySelect.options.length) {
      await loadCityChart(citySelect.value);
    }
  } catch (err) {
    chartStatus.textContent = `Error: ${err.message}`;
    console.error(err);
  }
}

citySelect.addEventListener("change", () => loadCityChart(citySelect.value));

init();
