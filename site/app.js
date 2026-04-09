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
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function formatConfidence(value) {
  if (!value) return "Low";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
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
  if (!hero || !meta) return;
  const currentMode = (data.season_modes ?? []).find((mode) => mode.slug === meta.current_forecast_season);
  document.getElementById("hero-eyebrow").textContent = `${meta.current_ceremony_year ?? ""} Best Picture Forecast`;
  document.getElementById("hero-title").textContent = hero.title ?? "";
  document.getElementById("hero-probability").textContent = formatPercent(hero.probability);
  document.getElementById("hero-release").textContent = formatDate(hero.release_date);
  document.getElementById("hero-model").textContent = meta.model ? meta.model.toUpperCase() : "Unknown";
  document.getElementById("hero-season").textContent = formatSeason(meta.current_forecast_season);
  document.getElementById("hero-film-name").textContent = hero.title ?? "";
  document.getElementById("hero-film-genres").textContent = hero.genres || "Genre mix pending";
  document.getElementById("hero-film-overview").textContent = hero.overview || "No synopsis available yet.";
  document.getElementById("hero-summary").textContent =
    currentMode
      ? `Current front-runner for the ${meta.current_ceremony_year} Oscars in ${formatSeason(meta.current_forecast_season).toLowerCase()} mode. This board leans most on ${currentMode.leans_on}.`
      : `Current front-runner for the ${meta.current_ceremony_year} Oscars in ${formatSeason(meta.current_forecast_season).toLowerCase()} mode, blending TMDb contender tracking with a walk-forward historical model.`;
  document.getElementById("hero-film-card").insertAdjacentHTML("beforeend", movementMarkup(hero));
}

function probBarMarkup(probability) {
  const pct = Math.round((probability ?? 0) * 100);
  return `<div class="prob-bar-wrap"><div class="prob-bar-fill" style="width:${pct}%"></div></div>`;
}

const PRECURSOR_LABELS = {
  pga_win: "PGA",
  dga_win: "DGA",
  sag_win: "SAG",
  bafta_win: "BAFTA",
  golden_globe_win: "Globe",
  critics_choice_win: "Critics Choice",
};

function awardBadgesMarkup(row) {
  const badges = [];
  for (const [key, label] of Object.entries(PRECURSOR_LABELS)) {
    const val = row[key];
    if (val == null) continue;
    if (Number(val) >= 1) {
      badges.push(`<span class="award-badge win">★ ${label}</span>`);
    }
  }
  return badges.length ? `<div class="award-badges">${badges.join("")}</div>` : "";
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
            ${awardBadgesMarkup(card)}
          </div>
          <div class="contender-probability">
            <strong>${formatPercent(card.probability)}</strong>
            <span>Win Chance</span>
            ${probBarMarkup(card.probability)}
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
      label: `Production Walk-Forward (${metrics.production_training_start}+ train)`,
      value: formatPercent(metrics.production_walk_forward_winner_accuracy),
      body: `Retrained year by year on prior film years only, scoring ${metrics.production_first_scored_year}-${metrics.production_last_scored_year}.`,
    },
    {
      label: `Extended Validation (${metrics.extended_training_start}+ train)`,
      value: formatPercent(metrics.extended_walk_forward_winner_accuracy),
      body: `Same walk-forward setup across ${metrics.extended_scored_years} scored years from ${metrics.extended_first_scored_year}-${metrics.extended_last_scored_year}.`,
    },
    {
      label: metrics.baseline_name,
      value: formatPercent(metrics.baseline_accuracy),
      body: "Simple rule: most precursor wins, then precursor nominations, Oscar nominations, Metacritic, and Rotten Tomatoes.",
    },
    {
      label: "Confidence Calibration",
      value: `${metrics.extended_top_pick_brier_calibrated.toFixed(3)} Brier`,
      body: `Top-pick confidence is shrunk toward prior walk-forward accuracy. Extended-window Brier improved from ${metrics.extended_top_pick_brier_raw.toFixed(3)} to ${metrics.extended_top_pick_brier_calibrated.toFixed(3)}.`,
    },
    {
      label: `Latest Holdout ${metrics.holdout_year}`,
      value: formatPercent(metrics.holdout_accuracy),
      body: `Predicted ${metrics.holdout_predicted_winner} over ${metrics.holdout_runner_up ?? "the field"} with ${formatConfidence(metrics.holdout_confidence_label)} confidence (${formatPercent(metrics.holdout_confidence_probability ?? 0)}).`,
    },
    {
      label: "Trained On",
      value: `${metrics.feature_count} Signals`,
      body: "Oscar nominations, precursor awards, critic scores, release timing, distributor, genre, festival, and director-history features.",
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

function renderSeasonModes(data) {
  const modes = data.season_modes ?? [];
  const currentMode = modes.find((mode) => mode.current_mode);
  document.getElementById("season-mode-summary").textContent = currentMode
    ? `The live ${data.meta.current_ceremony_year} board is currently in ${currentMode.label.toLowerCase()} mode. Later-season cards stay marked TBD until the calendar actually reaches those phases, so we are not pretending to have festival or precursor evidence before it exists.`
    : "Forecast modes shift the board from broad contender discovery early in the race toward stronger awards evidence later in the season.";

  const container = document.getElementById("season-mode-grid");
  container.innerHTML = modes
    .map((mode) => {
      const currentExample = mode.current_example;
      const priorExamples = mode.prior_examples ?? [];
      const currentExampleMarkup = currentExample
        ? `
            <div class="season-example current">
              <div class="season-example-head">
                <strong>Live ${currentExample.ceremony_year} Board</strong>
                <span>${formatSeason(mode.slug)} mode</span>
              </div>
              <p>Projected winner: <strong>${escapeHtml(currentExample.top_pick)}</strong> at ${formatPercent(currentExample.top_pick_probability)}${currentExample.runner_up ? ` over ${escapeHtml(currentExample.runner_up)}` : ""}.</p>
              <div class="season-example-list">
                ${currentExample.top_three
                  .map(
                    (item, index) => `
                      <span>#${index + 1} ${escapeHtml(item.title)} · ${formatPercent(item.probability)}</span>
                    `
                  )
                  .join("")}
              </div>
            </div>
          `
        : "";
      const examplesMarkup = priorExamples.length
        ? priorExamples
            .map(
              (example) => `
                <div class="season-example">
                  <div class="season-example-head">
                    <strong>${example.ceremony_year} Oscars</strong>
                    <span>${formatSeason(mode.slug)} mode</span>
                  </div>
                  <p>Projected winner: <strong>${escapeHtml(example.top_pick)}</strong> at ${formatPercent(example.top_pick_probability)}${example.runner_up ? ` over ${escapeHtml(example.runner_up)}` : ""}.</p>
                  <div class="season-example-list">
                    ${example.top_three
                      .map(
                        (item, index) => `
                          <span>#${index + 1} ${escapeHtml(item.title)} · ${formatPercent(item.probability)}</span>
                        `
                      )
                      .join("")}
                  </div>
                </div>
              `
            )
            .join("")
        : `<p class="season-empty">Archived ${mode.label.toLowerCase()} example pending.</p>`;

      return `
        <article class="season-mode-card ${mode.current_mode ? "current" : ""} ${mode.status ?? ""}">
          <div class="season-mode-head">
            <p class="eyebrow">${mode.current_mode ? "Current Mode" : "Forecast Mode"}</p>
            <h3>${mode.label}</h3>
          </div>
          <div class="season-status-pill ${mode.status ?? ""}">${mode.status_label ?? "Forecast Mode"}</div>
          <p>${mode.summary}</p>
          <p><strong>Leans on:</strong> ${mode.leans_on}.</p>
          <p><strong>Best for:</strong> ${mode.best_for}.</p>
          <p class="season-status-copy">${mode.status_summary ?? ""}</p>
          <div class="season-example-stack">
            ${currentExampleMarkup}
            ${examplesMarkup}
          </div>
        </article>
      `;
    })
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
          <p>Trained on ${race.train_start}-${race.train_end}. Predicted winner with ${formatPercent(race.predicted_probability)} win share.</p>
          <p>Runner-up: <strong>${race.runner_up ?? "Unknown"}</strong> at ${formatPercent(race.runner_up_probability ?? 0)}. Margin: ${formatPercent(race.leader_margin)}.</p>
          <p>Confidence: <strong>${formatConfidence(race.confidence_label)}</strong> (${formatPercent(race.confidence_probability ?? 0)}). Baseline picked <strong>${race.baseline_predicted_winner ?? "Unknown"}</strong>.</p>
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
  const sorted = rows.slice().sort((a, b) => a.year_film - b.year_film);
  const total = sorted.length;
  const hits = sorted.filter((r) => r.correct).length;
  const accuracyPct = total ? Math.round((hits / total) * 100) : 0;

  const strip = document.getElementById("accuracy-strip");
  if (strip) {
    strip.innerHTML = `
      <div class="accuracy-header">
        <span class="accuracy-big">${accuracyPct}%</span>
        <span class="accuracy-strip-summary">${hits}/${total} correct · Walk-forward validation</span>
      </div>
      <div class="accuracy-strip">
        ${sorted
          .map(
            (r) => `
          <div class="accuracy-year-dot" title="${r.year_film}: ${r.correct ? "Hit" : "Miss"} — predicted ${r.predicted_winner}, actual ${r.actual_winner}">
            <div class="dot ${r.correct ? "hit" : "miss"}"></div>
            <span class="yr-label">${String(r.year_film).slice(-2)}</span>
          </div>`
          )
          .join("")}
      </div>
    `;
  }

  const container = document.getElementById("history-table");
  container.innerHTML = sorted
    .slice()
    .reverse()
    .map(
      (row) => `
        <tr>
          <td>${row.year_film}</td>
          <td>${row.predicted_winner}</td>
          <td>${row.actual_winner}</td>
          <td>${row.baseline_predicted_winner ?? "—"}</td>
          <td>${formatConfidence(row.confidence_label)}</td>
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
      ${selected.forecast_mode_summary ? `${selected.forecast_mode_summary} ` : ""}
      ${selected.forecast_mode_leans_on ? `This mode leans most on <strong>${selected.forecast_mode_leans_on}</strong>. ` : ""}
      Current projected winner: <strong>${predicted.film}</strong>.
    `;
  } else {
    summary.innerHTML = `
      Trained on <strong>${selected.train_start}-${selected.train_end}</strong>. 
      Predicted winner: <strong>${predicted.film}</strong> over <strong>${selected.rows[1]?.film ?? "the field"}</strong> by <strong>${formatPercent(predicted.margin_to_next ?? 0)}</strong>. 
      Confidence: <strong>${formatConfidence(selected.top_pick_confidence_label ?? predicted.confidence_label)}</strong> (${formatPercent(selected.top_pick_confidence ?? predicted.confidence_probability ?? 0)}). 
      Actual winner: <strong>${actual ? actual.film : "Unknown"}</strong>.
    `;
  }

  const list = document.getElementById("year-race-list");
  list.innerHTML = selected.rows
    .map(
      (row, index) => `
        <article class="year-race-card">
          <div>
            <h3>#${row.rank ?? index + 1} ${row.film}</h3>
            <p>
              ${row.oscar_nomination_count ?? "—"} Oscar nominations ·
              Tomatometer ${row.tomatometer_rating == null ? "—" : row.tomatometer_rating.toFixed(0)} ·
              Gap to next ${formatPercent(row.margin_to_next ?? 0)}
            </p>
            ${awardBadgesMarkup(row)}
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
          <div style="text-align:right">
            <strong>${formatPercent(row.probability)}</strong>
            <span class="metric-label" style="display:block">Win Share</span>
            ${probBarMarkup(row.probability)}
          </div>
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
      () => renderSeasonModes(data),
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
