async function loadSiteData() {
  if (window.__SITE_DATA__) {
    return window.__SITE_DATA__;
  }
  const response = await fetch("./data/site_data.json");
  if (!response.ok) {
    throw new Error("Could not load site data.");
  }
  return response.json();
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatSeason(value) {
  if (!value) return "Unknown";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function posterMarkup(card) {
  if (card.poster_url) {
    return `<div class="poster-frame"><img src="${card.poster_url}" alt="${escapeHtml(card.title)} poster" loading="lazy" /></div>`;
  }
  return `<div class="poster-frame">Poster pending</div>`;
}

function movementMarkup(card) {
  if (card.movement === "up") {
    return `<span class="movement-chip up">↑ Up ${card.rank_delta}</span>`;
  }
  if (card.movement === "down") {
    return `<span class="movement-chip down">↓ Down ${Math.abs(card.rank_delta)}</span>`;
  }
  if (card.movement === "same") {
    return `<span class="movement-chip same">• No change</span>`;
  }
  return `<span class="movement-chip new">New entry</span>`;
}

function renderHero(data) {
  const { hero, meta } = data;
  document.getElementById("hero-eyebrow").textContent = `${meta.current_ceremony_year} Best Picture Forecast`;
  document.getElementById("hero-title").textContent = hero.title;
  document.getElementById("hero-summary").textContent =
    `Current front-runner for the ${meta.current_ceremony_year} Oscars, based on the latest TMDb-first contender board and a walk-forward historical model.`;
  document.getElementById("hero-probability").textContent = formatPercent(hero.probability);
  document.getElementById("hero-release").textContent = formatDate(hero.release_date);
  document.getElementById("hero-model").textContent = meta.model.toUpperCase();
  document.getElementById("hero-season").textContent = formatSeason(meta.current_forecast_season);
  document.getElementById("hero-film-name").textContent = hero.title;
  document.getElementById("hero-film-genres").textContent = hero.genres || "Genre mix pending";
  document.getElementById("hero-film-overview").textContent = hero.overview || "No synopsis available yet.";
  document.getElementById("hero-summary").textContent =
    `Current front-runner for the ${meta.current_ceremony_year} Oscars in ${formatSeason(meta.current_forecast_season).toLowerCase()} mode, blending TMDb contender tracking with a walk-forward historical model.`;
  document.getElementById("hero-film-card").insertAdjacentHTML("beforeend", movementMarkup(hero));
}

function renderContenders(cards) {
  const container = document.getElementById("contender-list");
  container.innerHTML = cards
    .map(
      (card) => `
        <article class="contender-card">
          <div class="contender-rank">#${card.rank}</div>
          ${posterMarkup(card)}
          <div>
            <h3>${card.title}</h3>
            <div class="contender-meta">
              ${formatDate(card.release_date)} · ${card.genres || "Genres pending"}<br />
              TMDb rating ${card.rating?.toFixed(1) ?? "—"} from ${card.vote_count?.toLocaleString?.() ?? card.vote_count} votes<br />
              ${formatSeason(card.forecast_season)} mode${card.manual_contender_flag ? " · Curated contender" : ""}
            </div>
          </div>
          <div class="contender-probability">
            <strong>${formatPercent(card.probability)}</strong>
            <span>Win Chance</span>
            ${movementMarkup(card)}
          </div>
        </article>
      `
    )
    .join("");
}

function renderMetrics(data) {
  const metrics = data.metrics;
  const stack = document.getElementById("metric-stack");
  const items = [
    {
      label: "Walk-Forward Winner Accuracy",
      value: formatPercent(metrics.walk_forward_winner_accuracy),
      body: "The strongest honest measure of how often the model picked the eventual Best Picture winner year by year.",
    },
    {
      label: `Latest Holdout ${metrics.holdout_year}`,
      value: formatPercent(metrics.holdout_accuracy),
      body: `Predicted ${metrics.holdout_predicted_winner}, actual winner ${metrics.holdout_actual_winner}.`,
    },
    {
      label: "Forecast Season",
      value: formatSeason(metrics.current_forecast_season),
      body: "The future board now changes behavior by season so spring lists behave like watchlists and fall/winter lists behave more like awards forecasts.",
    },
    {
      label: "Feature Set",
      value: `${metrics.feature_count}`,
      body: "Awards, timing, critic score, distributor, director history, prestige genre, and festival signals.",
    },
  ];

  stack.innerHTML = items
    .map(
      (item) => `
        <article class="stat-card">
          <span class="metric-label">${item.label}</span>
          <strong>${item.value}</strong>
          <p>${item.body}</p>
        </article>
      `
    )
    .join("");
}

function renderRecentRaces(races) {
  const container = document.getElementById("recent-races");
  container.innerHTML = races
    .slice()
    .reverse()
    .map(
      (race) => `
        <article class="race-card">
          <p class="eyebrow">${race.year_film} Film Year</p>
          <h3>${race.predicted_winner}</h3>
          <p>Predicted winner with ${formatPercent(race.predicted_probability)} implied win share.</p>
          <p>Actual winner: <strong>${race.actual_winner}</strong></p>
          <span class="result ${race.correct ? "correct" : "miss"}">
            ${race.correct ? "Correct Call" : "Missed Call"}
          </span>
        </article>
      `
    )
    .join("");
}

function renderHistory(rows) {
  const container = document.getElementById("history-table");
  container.innerHTML = rows
    .slice()
    .reverse()
    .map(
      (row) => `
        <tr>
          <td>${row.year_film}</td>
          <td>${row.predicted_winner}</td>
          <td>${row.actual_winner}</td>
          <td><span class="history-pill ${row.correct ? "correct" : "miss"}">${row.correct ? "Hit" : "Miss"}</span></td>
        </tr>
      `
    )
    .join("");
}

function renderMethodology(methodology) {
  document.getElementById("method-headline").textContent = methodology.headline;
  document.getElementById("method-list").innerHTML = methodology.bullets
    .map((bullet) => `<li>${bullet}</li>`)
    .join("");
}

function renderHistoricalYearControls(data) {
  const select = document.getElementById("year-select");
  const years = [...data.historical_years]
    .sort((a, b) => b.year_film - a.year_film);

  if (!years.length) {
    select.innerHTML = `<option value="">No years available</option>`;
    document.getElementById("history-year-summary").textContent = "Historical race data is still being generated.";
    document.getElementById("year-race-list").innerHTML = "";
    return;
  }

  select.innerHTML = years
    .map(
      (item) =>
        `<option value="${item.year_film}">${item.year_film}${item.is_future_forecast ? " forecast" : ""}</option>`
    )
    .join("");

  select.value = years[0].year_film;
  const update = () => renderHistoricalYear(data, Number(select.value));
  select.addEventListener("change", update);
  update();
}

function renderHistoricalYear(data, year) {
  const selected = data.historical_years.find((item) => item.year_film === year);
  if (!selected) return;

  const summary = document.getElementById("history-year-summary");
  const predicted = selected.rows[0];
  const actual = selected.rows.find((row) => row.actual_winner);
  if (selected.is_future_forecast) {
    summary.innerHTML = `
      Future forecast for the <strong>${selected.year_film + 1}</strong> Oscars in <strong>${formatSeason(selected.forecast_season)}</strong> mode. 
      Current projected winner: <strong>${predicted.film}</strong>.
    `;
  } else {
    summary.innerHTML = `
      Trained on <strong>${selected.train_start}-${selected.train_end}</strong>. 
      Predicted winner: <strong>${predicted.film}</strong>. 
      Actual winner: <strong>${actual ? actual.film : "Unknown"}</strong>.
    `;
  }

  const list = document.getElementById("year-race-list");
  list.innerHTML = selected.rows
    .map(
      (row, index) => `
        <article class="year-race-card">
          <div>
            <h3>#${index + 1} ${row.film}</h3>
            <p>
              ${row.oscar_nomination_count ?? "—"} Oscar nominations ·
              Tomatometer ${row.tomatometer_rating == null ? "—" : row.tomatometer_rating.toFixed(0)} ·
              Momentum ${row.momentum_score == null ? "—" : row.momentum_score.toFixed(0)}
            </p>
            <span class="winner-badge ${row.actual_winner ? "actual" : "nominee"}">
              ${
                selected.is_future_forecast
                  ? row.manual_contender_flag
                    ? "Curated forecast contender"
                    : "Forecast contender"
                  : row.actual_winner
                    ? "Actual winner"
                    : "Nominee"
              }
            </span>
          </div>
          <strong>${formatPercent(row.probability)}</strong>
          <span class="metric-label">Win Share</span>
        </article>
      `
    )
    .join("");
}

async function main() {
  try {
    const data = await loadSiteData();
    const sections = [
      () => renderHero(data),
      () => renderContenders(data.forecast_cards ?? []),
      () => renderMetrics(data),
      () => renderHistoricalYearControls(data),
      () => renderRecentRaces(data.recent_races ?? []),
      () => renderHistory(data.backtest_rows ?? []),
      () => renderMethodology(data.methodology ?? { headline: "", bullets: [] }),
    ];

    sections.forEach((renderSection) => {
      try {
        renderSection();
      } catch (error) {
        console.error("Dashboard section failed to render.", error);
      }
    });
  } catch (error) {
    document.getElementById("hero-title").textContent = "Site data unavailable";
    document.getElementById("hero-summary").textContent = error.message;
    console.error(error);
  }
}

main();
