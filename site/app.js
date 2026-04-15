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

const BRAND_NAME = "RedCarpet Signals";
const BRAND_DESCRIPTOR = "Signals shaping the awards race, starting with Best Picture.";
const TAB_CONFIG = {
  "best-picture": {
    title: "RedCarpet Signals | Best Picture Board",
    scope: "Best Picture Board",
    copy: "Live contenders, movement, and historical race context",
  },
  "best-actor": {
    title: "RedCarpet Signals | Best Actor",
    scope: "Best Actor",
    copy: "Next board in progress",
  },
  "best-actress": {
    title: "RedCarpet Signals | Best Actress",
    scope: "Best Actress",
    copy: "Next board in progress",
  },
  "best-director": {
    title: "RedCarpet Signals | Best Director",
    scope: "Best Director",
    copy: "Next board in progress",
  },
  "box-office": {
    title: "RedCarpet Signals | Box Office",
    scope: "Domestic / Worldwide Box Office",
    copy: "Signals view coming soon",
  },
};
const GENRE_LABELS = {
  12: "Adventure",
  14: "Fantasy",
  16: "Animation",
  18: "Drama",
  27: "Horror",
  28: "Action",
  35: "Comedy",
  36: "History",
  37: "Western",
  53: "Thriller",
  80: "Crime",
  878: "Sci-Fi",
  9648: "Mystery",
  10402: "Music",
  10749: "Romance",
  10751: "Family",
  10752: "War",
};

function filmTitle(card) {
  return card?.title ?? card?.film ?? "Film";
}

function filmInitials(value) {
  const letters = String(value ?? "")
    .split(/[\s:/\-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join("")
    .toUpperCase();
  return letters || "RS";
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

function formatGenres(value) {
  if (!value) return "Genre mix pending";
  const parts = Array.isArray(value) ? value : String(value).split(",");
  const labels = parts
    .map((part) => String(part).trim())
    .filter(Boolean)
    .map((part) => {
      const numericKey = Number(part);
      if (!Number.isNaN(numericKey)) {
        return GENRE_LABELS[numericKey] ?? part;
      }
      return part;
    });
  return labels.length ? labels.join(" · ") : "Genre mix pending";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function posterMarkup(card, className = "") {
  const title = filmTitle(card);
  const classes = ["poster-frame", className].filter(Boolean).join(" ");
  if (card.poster_url) {
    return `<div class="${classes}"><img src="${card.poster_url}" alt="${escapeHtml(title)} poster" loading="lazy" /></div>`;
  }
  return `
    <div class="${classes} poster-fallback" aria-label="${escapeHtml(title)} poster placeholder">
      <span>${escapeHtml(filmInitials(title))}</span>
    </div>
  `;
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

function formatScore(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Math.round(Number(value)).toString();
}

const TOMATO_ICON = `<svg width="14" height="14" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <ellipse cx="50" cy="58" rx="36" ry="34" fill="#E8212A"/>
  <path d="M50 24 C50 24 44 10 30 14 C36 18 38 26 38 26" fill="#4CAF50"/>
  <path d="M50 24 C50 24 56 10 70 14 C64 18 62 26 62 26" fill="#4CAF50"/>
  <path d="M50 24 C50 24 50 8 50 8" stroke="#4CAF50" stroke-width="4" stroke-linecap="round"/>
</svg>`;

const AUDIENCE_ICON = `<svg width="14" height="14" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="20" y="38" width="60" height="44" rx="6" fill="#D97C16"/>
  <rect x="28" y="30" width="14" height="12" rx="3" fill="#F5C842"/>
  <rect x="43" y="26" width="14" height="16" rx="3" fill="#F5C842"/>
  <rect x="58" y="30" width="14" height="12" rx="3" fill="#F5C842"/>
  <circle cx="35" cy="60" r="6" fill="#FFF" opacity="0.25"/>
  <circle cx="50" cy="60" r="6" fill="#FFF" opacity="0.25"/>
  <circle cx="65" cy="60" r="6" fill="#FFF" opacity="0.25"/>
</svg>`;

function criticStripMarkup(card, className = "") {
  const classes = ["critic-strip", className].filter(Boolean).join(" ");
  const rtScore = formatScore(card.tomatometer_rating);
  const audScore = formatScore(card.audience_rating);
  const rtUrl = card.rt_url || null;
  const source = rtUrl
    ? `<a class="critic-source" href="${escapeHtml(rtUrl)}" target="_blank" rel="noopener">Rotten Tomatoes ↗</a>`
    : `<span class="critic-source">Rotten Tomatoes</span>`;
  return `
    <div class="critic-strip-wrap">
      <div class="${classes}">
        <span title="Tomatometer">${TOMATO_ICON}<strong>${rtScore}</strong></span>
        <span title="Audience Score">${AUDIENCE_ICON}<strong>${audScore}</strong></span>
      </div>
      ${source}
    </div>
  `;
}

function setActiveTab(tab) {
  const config = TAB_CONFIG[tab] ?? TAB_CONFIG["best-picture"];
  document.title = config.title;

  document.querySelectorAll("[data-tab]").forEach((button) => {
    const active = button.dataset.tab === tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  });

  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    const active = panel.dataset.tabPanel === tab;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });

  const scopePill = document.getElementById("scope-pill");
  const scopeCopy = document.getElementById("scope-copy");
  if (scopePill) scopePill.textContent = config.scope;
  if (scopeCopy) scopeCopy.textContent = config.copy;
}

function initTabs() {
  const buttons = [...document.querySelectorAll("[data-tab]")];
  if (!buttons.length) return;

  buttons.forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });

  setActiveTab("best-picture");
}

function renderHero(data) {
  const { hero, meta } = data;
  if (!hero || !meta) return;
  const currentMode = (data.season_modes ?? []).find((mode) => mode.slug === meta.current_forecast_season);
  document.getElementById("hero-eyebrow").textContent = meta.current_ceremony_year
    ? `${meta.current_ceremony_year} Best Picture Board`
    : "Best Picture Board";
  document.getElementById("hero-title").textContent = hero.title ?? "";
  document.getElementById("hero-probability").textContent = formatPercent(hero.probability);
  document.getElementById("hero-release").textContent = formatDate(hero.release_date);
  document.getElementById("hero-model").textContent = meta.model ? meta.model.toUpperCase() : "Unknown";
  document.getElementById("hero-season").textContent = formatSeason(meta.current_forecast_season);
  document.getElementById("hero-summary").textContent =
    currentMode
      ? `${BRAND_DESCRIPTOR} The live ${meta.current_ceremony_year} Best Picture board is running in ${formatSeason(meta.current_forecast_season).toLowerCase()} mode and currently leans most on ${currentMode.leans_on}.`
      : `${BRAND_DESCRIPTOR} This Best Picture board blends TMDb contender tracking with a walk-forward historical model.`;
  document.getElementById("hero-film-card").innerHTML = `
    <div class="hero-film-layout">
      ${posterMarkup(hero, "hero-poster")}
      <div class="hero-film-copy">
        <span class="rank-badge">#1</span>
        <strong>${escapeHtml(filmTitle(hero))}</strong>
        <span>${escapeHtml(formatGenres(hero.genres))}</span>
        ${criticStripMarkup(hero, "critic-strip-hero")}
        <p>${escapeHtml(hero.overview || "No synopsis available yet.")}</p>
        ${movementMarkup(hero)}
      </div>
    </div>
  `;
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
              ${formatDate(card.release_date)} · ${formatGenres(card.genres)}<br />
              TMDb rating ${card.rating?.toFixed(1) ?? "—"} from ${card.vote_count?.toLocaleString?.() ?? card.vote_count} votes<br />
              RT ${formatScore(card.tomatometer_rating)} · Audience ${formatScore(card.audience_rating)}<br />
              ${formatSeason(card.forecast_season)} mode${card.manual_contender_flag ? " · Curated contender" : ""}
            </div>
            ${awardBadgesMarkup(card)}
            ${card.movement_blurb ? `<p class="movement-blurb">${escapeHtml(card.movement_blurb)}</p>` : ""}
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

const SIGNAL_GROUPS = [
  {
    group: "Precursor Awards",
    signals: [
      { key: "pga_win", label: "PGA Win", desc: "Producers Guild of America — the single strongest Best Picture predictor. PGA and Oscar have aligned ~80% of the time." },
      { key: "dga_win", label: "DGA Win", desc: "Directors Guild of America — DGA winner goes on to win Best Picture roughly 70% of the time." },
      { key: "sag_win", label: "SAG Win (Ensemble)", desc: "Screen Actors Guild ensemble cast award. The only guild voted on entirely by actors, who make up the largest Oscar branch." },
      { key: "bafta_win", label: "BAFTA Win", desc: "British Academy of Film and Television Arts — often an early bellwether, especially for international films." },
      { key: "golden_globe_win", label: "Golden Globe Win", desc: "Drama category win is the more relevant signal for Best Picture. Comedy/Musical winners rarely cross over." },
      { key: "critics_choice_win", label: "Critics Choice Win", desc: "Broadcast Film Critics Association award, voted just before Oscar nominations. High overlap with Academy taste." },
    ],
  },
  {
    group: "Oscar Nominations",
    signals: [
      { key: "oscar_nomination_count", label: "Total Oscar Nominations", desc: "Films with 10+ nominations almost always include Best Picture. More nominations = broader Academy support across branches." },
      { key: "high_nomination_flag", label: "High Nomination Flag", desc: "Binary flag for films with an unusually large nomination haul (top tier). Acts as a non-linear boost." },
      { key: "nominee_probability", label: "Nominee Probability", desc: "Model output from a separate nominee-prediction stage. Helps filter the field before scoring winners." },
    ],
  },
  {
    group: "Critic Scores",
    signals: [
      { key: "tomatometer_rating", label: "Rotten Tomatoes Tomatometer", desc: "Aggregate critic approval percentage. Strong RT scores are near-necessary but not sufficient — no film under 70% has won in the modern era." },
      { key: "metacritic_score", label: "Metacritic Score", desc: "Weighted average of critic reviews. Often more discriminating than RT since it measures degree of praise, not just approval." },
      { key: "movie_rating", label: "TMDb User Rating", desc: "Crowd rating from TMDb. Captures general audience reception, which correlates with broad Academy support." },
      { key: "movie_vote_count_log", label: "TMDb Vote Count (log)", desc: "Log-scaled vote count. A proxy for cultural reach — widely seen films tend to have more Academy members who have actually watched them." },
    ],
  },
  {
    group: "Release & Timing",
    signals: [
      { key: "release_month", label: "Release Month", desc: "December releases dominate Best Picture — recency bias means films fresh in voters' minds get more attention. Limited Dec releases are flagged separately." },
    ],
  },
  {
    group: "Distributor",
    signals: [
      { key: "is_prestige_distributor", label: "Prestige Distributor", desc: "A24, Focus Features, Searchlight, Neon — specialty distributors with strong Oscar campaign infrastructure and Academy relationships." },
      { key: "is_major_studio_distributor", label: "Major Studio Distributor", desc: "Universal, Warner Bros., Paramount etc. Major studios have resources for large-scale campaigns but less prestige-film focus." },
      { key: "is_streaming_distributor", label: "Streaming Distributor", desc: "Netflix, Apple TV+, Amazon — streaming nominees have grown steadily but still face some Academy resistance relative to theatrical releases." },
    ],
  },
  {
    group: "Genre",
    signals: [
      { key: "is_drama_genre", label: "Drama", desc: "The dominant Best Picture genre. Nearly every winner is classified as drama." },
      { key: "is_history_genre", label: "Historical", desc: "Historical dramas have a strong track record — Braveheart, Gladiator, 12 Years a Slave, Oppenheimer." },
      { key: "is_biography_genre", label: "Biography", desc: "Biopics are a reliable Oscar category — The King's Speech, Bohemian Rhapsody, Oppenheimer." },
      { key: "is_war_genre", label: "War", desc: "War films have a consistent presence: Platoon, The Hurt Locker, 1917, All Quiet on the Western Front." },
      { key: "is_music_genre", label: "Music", desc: "Music-themed films have won occasionally — Whiplash, Bohemian Rhapsody, La La Land (runner-up)." },
      { key: "is_romance_genre", label: "Romance", desc: "Romance is rarely a winner on its own but often present as a secondary genre in Best Picture nominees." },
      { key: "prestige_genre_score", label: "Prestige Genre Score", desc: "Composite score combining genre signals into a single prestige-weighted value." },
    ],
  },
  {
    group: "Festivals",
    signals: [
      { key: "cannes_flag", label: "Cannes", desc: "Palme d'Or or major Cannes prize. Strong European art-house signal; occasionally translates to Oscar (Parasite, Amour)." },
      { key: "venice_flag", label: "Venice", desc: "Venice Film Festival premiere. The Venice-to-Oscar pipeline has been remarkably strong — Nomadland, Roma, The Shape of Water all won here first." },
      { key: "tiff_flag", label: "TIFF", desc: "Toronto International Film Festival. TIFF People's Choice Award is arguably the best early Oscar indicator — winners have gone on to win Best Picture multiple times." },
      { key: "telluride_flag", label: "Telluride", desc: "Small, invite-only festival that premieres many Oscar frontrunners before the wider circuit. A Telluride slot signals distributor confidence." },
      { key: "sundance_flag", label: "Sundance", desc: "Primary signal for independent films. Sundance winners occasionally cross into Best Picture (CODA)." },
      { key: "sxsw_flag", label: "SXSW", desc: "South by Southwest — less direct Oscar correlation but signals indie buzz and early critical attention." },
      { key: "festival_presence_score", label: "Festival Presence Score", desc: "Composite of all festival flags weighted by Oscar correlation strength." },
      { key: "major_festival_flag", label: "Major Festival Flag", desc: "Binary flag for Venice/TIFF/Telluride presence — the three festivals most directly linked to Oscar success." },
    ],
  },
  {
    group: "Director History",
    signals: [
      { key: "director_prior_directing_nominations", label: "Prior Directing Nominations", desc: "Number of times this director has been nominated for Best Director before. The Academy rewards established talent." },
      { key: "director_prior_directing_wins", label: "Prior Directing Wins", desc: "Prior Best Director wins. A previous winner has established credibility with voters." },
      { key: "director_has_prior_directing_win", label: "Prior Win Flag", desc: "Binary flag — has this director won before? Prior winners like Spielberg, Scorsese, Bigelow get a credibility bump." },
    ],
  },
];

const ACTOR_SIGNAL_GROUPS = [
  {
    group: "Oscar Pedigree",
    signals: [
      { label: "Prior Leading-Role Nominations", desc: "Number of previous Best Actor/Actress Oscar nominations. One of the two strongest predictors — the Academy rewards returning nominees." },
      { label: "Prior Oscar Wins", desc: "Past Best Actor/Actress wins. Previous winners face mixed momentum: the Academy sometimes avoids back-to-back, but win pedigree lifts baseline probability." },
    ],
  },
  {
    group: "Precursor Awards",
    signals: [
      { label: "SAG Nomination", desc: "Screen Actors Guild nomination for Outstanding Performance by a Male Actor in a Leading Role. Voted entirely by fellow actors — the most peer-reviewed signal." },
      { label: "SAG Win", desc: "SAG win in the leading actor category. The single strongest in-season predictor for Best Actor. SAG and Oscar voters share the largest overlap of any guild." },
      { label: "Golden Globe Nomination", desc: "Globe nomination in the Drama or Comedy/Musical category. Useful early signal before SAG and BAFTA ballots close." },
      { label: "Golden Globe Win", desc: "Globe win. Drama category winners convert to Oscar wins at a meaningfully higher rate than Comedy/Musical winners." },
      { label: "BAFTA Nomination", desc: "BAFTA nomination for Best Actor in a Leading Role. Strong overlap with Oscar nominators, particularly for international and prestige arthouse films." },
      { label: "BAFTA Win", desc: "BAFTA win is one of the clearest Oscar leading indicators — roughly 60% of BAFTA Best Actor winners go on to win the Oscar in the modern era." },
    ],
  },
  {
    group: "Film Quality",
    signals: [
      { label: "Rotten Tomatoes Score", desc: "Tomatometer rating for the film. Critics' reception signals whether the performance is being recognized alongside a strong film — key in early season." },
      { label: "Metacritic Score", desc: "Weighted average of critic reviews. Metacritic scores correlate more with awards-voter tastes than Tomatometer, particularly for prestige dramas." },
    ],
  },
];

const DIRECTOR_SIGNAL_GROUPS = [
  {
    group: "Oscar Pedigree",
    signals: [
      { label: "Prior Directing Nominations", desc: "Previous Best Director Oscar nominations. The Academy rarely gives the award to a first-time nominee — pedigree matters." },
      { label: "Prior Directing Wins", desc: "Past Best Director wins. Back-to-back wins are rare but not unprecedented (Spielberg, Bigelow)." },
    ],
  },
  {
    group: "Guild & Precursor Awards",
    signals: [
      { label: "DGA Nomination", desc: "Directors Guild nomination. DGA and Oscar Best Director align more than 80% of the time in the modern era — the strongest single predictor for this category." },
      { label: "DGA Win", desc: "DGA win. When the DGA and Oscar disagree, it's news. Since 2000, DGA winners have taken the Oscar roughly 85% of the time." },
      { label: "Golden Globe Win", desc: "Globe Best Director win. Drama category is the relevant signal." },
      { label: "BAFTA Win", desc: "BAFTA Best Director win. Strong overlap with Oscar director voters." },
    ],
  },
  {
    group: "Film Quality",
    signals: [
      { label: "Rotten Tomatoes Score", desc: "Critical reception of the film. Directors are judged on the whole film, so overall critical consensus matters more here than in acting categories." },
      { label: "Metacritic Score", desc: "Weighted average of critic reviews. Prestige drama directors benefit most from strong Metacritic scores with awards-focused outlets." },
    ],
  },
];

function renderMetrics(data) {
  const metrics = data.metrics;
  const stack = document.getElementById("metric-stack");
  const items = [
    {
      label: `Production Walk-Forward (${metrics.production_training_start}+ train)`,
      value: formatPercent(metrics.production_walk_forward_winner_accuracy),
      body: `The headline accuracy number. Trained only on films from ${metrics.production_training_start} onward — the modern awards era where precursor signals and streaming distributors exist. Each year is scored using only data from prior years, so no future information leaks in. Scored across ${metrics.production_first_scored_year}–${metrics.production_last_scored_year}.`,
    },
    {
      label: `Extended Validation (${metrics.extended_training_start}+ train)`,
      value: formatPercent(metrics.extended_walk_forward_winner_accuracy),
      body: `The same walk-forward method but starting training earlier (${metrics.extended_training_start}), giving a longer ${metrics.extended_scored_years}-year window (${metrics.extended_first_scored_year}–${metrics.extended_last_scored_year}). This is a tougher test — older eras had fewer precursor signals — so accuracy is typically lower. It exists to show the model isn't just overfit to the modern era.`,
    },
    {
      label: metrics.baseline_name,
      value: formatPercent(metrics.baseline_accuracy),
      body: "A rules-based comparison: pick the film with the most precursor wins, breaking ties by nominations, then Metacritic, then RT. No machine learning. Beating this baseline consistently is what validates the model.",
    },
    {
      label: "Confidence Calibration",
      value: `${metrics.extended_top_pick_brier_calibrated.toFixed(3)} Brier`,
      body: `Raw model probabilities tend to be overconfident. Confidence scores are shrunk toward the historical base rate so a "70% confidence" call actually means something. Brier score improved from ${metrics.extended_top_pick_brier_raw.toFixed(3)} → ${metrics.extended_top_pick_brier_calibrated.toFixed(3)} after calibration (lower is better).`,
    },
    {
      label: `Latest Holdout ${metrics.holdout_year}`,
      value: formatPercent(metrics.holdout_accuracy),
      body: `Predicted ${metrics.holdout_predicted_winner} over ${metrics.holdout_runner_up ?? "the field"} with ${formatConfidence(metrics.holdout_confidence_label)} confidence (${formatPercent(metrics.holdout_confidence_probability ?? 0)}).`,
    },
    {
      label: "Trained On",
      value: `${metrics.feature_count} Signals`,
      body: "Nomination totals, precursor awards, critic scores, release timing, distributor, genre, festival, and director-history features. Full breakdown in the Signals Engine below.",
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
          ${posterMarkup({ title: race.predicted_winner, poster_url: race.poster_url }, "race-poster")}
          <div class="race-card-copy">
            <p class="eyebrow">${race.year_film} Film Year</p>
            <h3>${race.predicted_winner}</h3>
            <p>Trained on ${race.train_start}-${race.train_end}. Predicted winner with ${formatPercent(race.predicted_probability)} win share.</p>
            <p>Runner-up: <strong>${race.runner_up ?? "Unknown"}</strong> at ${formatPercent(race.runner_up_probability ?? 0)}. Margin: ${formatPercent(race.leader_margin)}.</p>
            <p>Confidence: <strong>${formatConfidence(race.confidence_label)}</strong> (${formatPercent(race.confidence_probability ?? 0)}). Baseline picked <strong>${race.baseline_predicted_winner ?? "Unknown"}</strong>.</p>
            <p>Actual winner: <strong>${race.actual_winner}</strong></p>
            <span class="result ${race.correct ? "correct" : "miss"}">
              ${race.correct ? "Correct Call" : "Missed Call"}
            </span>
          </div>
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

function renderSignalsEngine(featureCount) {
  const container = document.getElementById("signals-engine-list");
  if (!container) return;
  container.innerHTML = `
    <div class="signals-list">
      ${SIGNAL_GROUPS.map((group) => `
        <div class="signal-group">
          <p class="signal-group-label">${group.group}</p>
          ${group.signals.map((s) => `
            <div class="signal-row">
              <span class="signal-name">${s.label}</span>
              <span class="signal-desc">${s.desc}</span>
            </div>
          `).join("")}
        </div>
      `).join("")}
    </div>
  `;
}

function renderMethodology(methodology) {
  const headline = methodology.headline
    ? methodology.headline.replace(/^The site uses/, `${BRAND_NAME} uses`)
    : "";
  document.getElementById("method-headline").textContent = headline;
  document.getElementById("method-list").innerHTML = methodology.bullets
    .map((bullet) => `<li>${bullet}</li>`)
    .join("");
}

function renderHistoricalYearControls(data) {
  const select = document.getElementById("year-select");
  const years = [...data.historical_years]
    .filter((item) => item.year_film >= 2015 || item.is_future_forecast)
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
      Future Best Picture board for <strong>${selected.year_film + 1}</strong> in <strong>${formatSeason(selected.forecast_season)}</strong> mode. 
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
          ${posterMarkup(row, "year-race-poster")}
          <div class="year-race-copy">
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
          <div class="year-race-probability">
            <strong>${formatPercent(row.probability)}</strong>
            <span class="metric-label">Win Share</span>
            ${probBarMarkup(row.probability)}
          </div>
        </article>
      `
    )
    .join("");
}

// ---------------------------------------------------------------------------
// Category board rendering (Best Actor / Actress / Director)
// ---------------------------------------------------------------------------

const CATEGORY_PRECURSOR_LABELS = {
  sag_win: "SAG",
  dga_win: "DGA",
  globe_win: "Globe",
  bafta_win: "BAFTA",
};

function categoryPrecursorBadges(row) {
  const badges = [];
  for (const [key, label] of Object.entries(CATEGORY_PRECURSOR_LABELS)) {
    if (row[key] != null && Number(row[key]) >= 1) {
      badges.push(`<span class="award-badge win">★ ${label}</span>`);
    }
  }
  return badges.length ? `<div class="award-badges">${badges.join("")}</div>` : "—";
}

function renderCategoryAccuracyStrip(categoryData, stripId) {
  const el = document.getElementById(stripId);
  if (!el) return;
  const rows = (categoryData.backtest_rows ?? []).slice().sort((a, b) => a.year_film - b.year_film);
  const total = categoryData.total_count ?? rows.length;
  const hits = categoryData.correct_count ?? rows.filter((r) => r.correct).length;
  const pct = total ? Math.round((hits / total) * 100) : 0;

  el.innerHTML = `
    <div class="accuracy-header">
      <span class="accuracy-big">${pct}%</span>
      <span class="accuracy-strip-summary">${hits}/${total} correct · Walk-forward ${categoryData.first_year ?? ""}–${categoryData.last_year ?? ""}</span>
    </div>
    <div class="accuracy-strip">
      ${rows.map((r) => `
        <div class="accuracy-year-dot" title="${r.year_film}: ${r.correct ? "Hit" : "Miss"} — predicted ${r.predicted_winner}, actual ${r.actual_winner}">
          <div class="dot ${r.correct ? "hit" : "miss"}"></div>
          <span class="yr-label">${String(r.year_film).slice(-2)}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderCategoryLiveNotice(categoryData, noticeId) {
  const el = document.getElementById(noticeId);
  if (!el) return;
  const hasLive = (categoryData.live_contenders ?? []).length > 0;
  if (hasLive) {
    el.innerHTML = ""; // hide placeholder when live board is shown
    return;
  }
  el.innerHTML = `
    <div class="category-live-notice-inner">
      <p class="eyebrow">Live Board</p>
      <p>
        The 2026 ${escapeHtml(categoryData.label)} nominees will appear here once announced.
        The historical backtest below shows how this model would have performed across
        <strong>${categoryData.total_count ?? 0}</strong> prior races
        (${categoryData.first_year ?? ""}–${categoryData.last_year ?? ""}).
      </p>
    </div>
  `;
}

function renderCategoryLiveBoard(categoryData, category) {
  const contenders = (categoryData.live_contenders ?? []).slice(0, 20);
  if (!contenders.length) return;

  // Find the panel in the correct tab
  const tabPanel = document.querySelector(`[data-tab-panel="best-${category}"]`);
  if (!tabPanel) return;

  // Create or find the live board section
  let liveSection = tabPanel.querySelector(".category-live-board");
  if (!liveSection) {
    const main = tabPanel.querySelector("main");
    if (!main) return;
    liveSection = document.createElement("section");
    liveSection.className = "panel panel-tall category-live-board";
    liveSection.innerHTML = `
      <div class="panel-head">
        <p class="eyebrow">Best ${category.charAt(0).toUpperCase() + category.slice(1)} · 2026 Contenders</p>
        <h2>Live Contender Board</h2>
      </div>
      <div class="contender-list" id="${category}-live-list"></div>
    `;
    main.insertBefore(liveSection, main.firstChild);
  }

  const listEl = liveSection.querySelector(`#${category}-live-list`);
  if (!listEl) return;

  listEl.innerHTML = contenders.map((c) => {
    const delta = c.rank_delta;
    const mvmt = c.movement ?? "new";
    const arrow = mvmt === "up" ? "↑" : mvmt === "down" ? "↓" : mvmt === "new" ? "★" : "—";
    const arrowClass = mvmt === "up" ? "up" : mvmt === "down" ? "down" : mvmt === "new" ? "new" : "same";
    const pct = Math.round((c.win_probability ?? 0) * 100);

    // Build precursor badges — directors use DGA instead of SAG
    const badges = [];
    if (category === "director") {
      if (c.dga_win) badges.push('<span class="award-badge win">★ DGA</span>');
      else if (c.dga_nom) badges.push('<span class="award-badge nom">DGA</span>');
    } else {
      if (c.sag_win) badges.push('<span class="award-badge win">★ SAG</span>');
      else if (c.sag_nom) badges.push('<span class="award-badge nom">SAG</span>');
    }
    if (c.globe_win) badges.push('<span class="award-badge win">★ Globe</span>');
    else if (c.globe_nom) badges.push('<span class="award-badge nom">Globe</span>');
    if (c.bafta_win) badges.push('<span class="award-badge win">★ BAFTA</span>');
    else if (c.bafta_nom) badges.push('<span class="award-badge nom">BAFTA</span>');
    const badgesHtml = badges.length ? `<div class="award-badges">${badges.join("")}</div>` : "";

    const profileImg = c.profile_url ?
      `<img class="contender-profile-img" src="${escapeHtml(c.profile_url)}" alt="${escapeHtml(c.name)}" loading="lazy">` :
      `<div class="contender-profile-placeholder">${escapeHtml(c.name.charAt(0))}</div>`;

    return `
      <article class="contender-row">
        <div class="contender-rank">
          <span class="rank-num">${c.rank}</span>
          <span class="rank-delta ${arrowClass}">${arrow}${delta != null && delta !== 0 ? Math.abs(delta) : ""}</span>
        </div>
        <div class="contender-profile">${profileImg}</div>
        <div class="contender-body">
          <div class="contender-title-row">
            <strong class="contender-name">${escapeHtml(c.name)}</strong>
            <span class="contender-film">${escapeHtml(c.film)}</span>
          </div>
          ${(() => {
            const noms = c.oscar_nominations ?? 0;
            const wins = c.oscar_wins ?? 0;
            if (noms === 0) return '';
            const label = wins > 0 ? `${wins}× win${wins > 1 ? 's' : ''}` : `${noms}× nom${noms > 1 ? 's' : ''}`;
            const cls = wins > 0 ? 'oscar-badge oscar-badge--win' : 'oscar-badge oscar-badge--nom';
            return `<span class="${cls}">🏆 ${label}</span>`;
          })()}
          ${badgesHtml}
          ${c.movement_blurb ? `<p class="actor-blurb">${escapeHtml(c.movement_blurb)}</p>` : ""}
          ${probBarMarkup(c.win_probability)}
        </div>
        <div class="contender-pct">${pct}%</div>
      </article>
    `;
  }).join("");
}

function renderCategoryTable(categoryData, tableId) {
  const el = document.getElementById(tableId);
  if (!el) return;
  const rows = (categoryData.backtest_rows ?? []).slice().sort((a, b) => b.year_film - a.year_film);
  el.innerHTML = rows
    .map((row) => `
      <tr>
        <td>${row.year_film}</td>
        <td><strong>${escapeHtml(row.predicted_winner ?? "—")}</strong></td>
        <td>${escapeHtml(row.predicted_film ?? "—")}</td>
        <td>${escapeHtml(row.actual_winner ?? "—")}</td>
        <td>${categoryPrecursorBadges(row)}</td>
        <td><span class="history-pill ${row.correct ? "correct" : "miss"}">${row.correct ? "Hit" : "Miss"}</span></td>
      </tr>
    `)
    .join("");
}

function renderCategorySignals(category) {
  const groups = category === "actor" || category === "actress" ? ACTOR_SIGNAL_GROUPS : DIRECTOR_SIGNAL_GROUPS ?? ACTOR_SIGNAL_GROUPS;
  const containerId = `${category}-signals-list`;
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = groups.map(group => `
    <div class="signal-group">
      <p class="signal-group-label">${group.group}</p>
      ${group.signals.map(s => `
        <div class="signal-row">
          <span class="signal-name">${s.label}</span>
          <span class="signal-desc">${s.desc}</span>
        </div>
      `).join("")}
    </div>
  `).join("");
}

function renderCategoryBoard(data, category) {
  const key = `${category}_data`;
  const categoryData = data[key];
  if (!categoryData) return;

  renderCategoryLiveBoard(categoryData, category);
  renderCategoryAccuracyStrip(categoryData, `${category}-accuracy-strip`);
  renderCategoryLiveNotice(categoryData, `${category}-live-notice`);
  renderCategoryTable(categoryData, `${category}-history-table`);
  renderCategorySignals(category);
}

// ---------------------------------------------------------------------------
// Visual 1 — Probability Donut
// ---------------------------------------------------------------------------

function renderDonut(cards) {
  const el = document.getElementById("donut-wrap");
  if (!el) return;

  const top = cards.slice(0, 6);
  const totalTop = top.reduce((s, c) => s + (c.probability ?? 0), 0);
  const other = Math.max(0, 1 - totalTop);

  const slices = [...top.map(c => ({ label: c.title, value: c.probability ?? 0, isOther: false }))];
  if (other > 0.005) slices.push({ label: "All Others", value: other, isOther: true });

  const COLORS = ["#c9a227", "#e8c55a", "#f0d98a", "#a07818", "#7a5c10", "#4e3a08"];
  const OTHER_COLOR = "#d9cfc5";
  const SIZE = 220;
  const CX = SIZE / 2, CY = SIZE / 2;
  const R_OUT = 96, R_IN = 58;

  // Build pie slices
  let angle = -Math.PI / 2;
  const GAP = 0.018;
  let paths = "";
  let legendItems = "";

  slices.forEach((slice, i) => {
    const sweep = slice.value * 2 * Math.PI - GAP;
    if (sweep <= 0) return;
    const a1 = angle + GAP / 2;
    const a2 = a1 + sweep;
    const x1o = CX + R_OUT * Math.cos(a1), y1o = CY + R_OUT * Math.sin(a1);
    const x2o = CX + R_OUT * Math.cos(a2), y2o = CY + R_OUT * Math.sin(a2);
    const x1i = CX + R_IN * Math.cos(a2), y1i = CY + R_IN * Math.sin(a2);
    const x2i = CX + R_IN * Math.cos(a1), y2i = CY + R_IN * Math.sin(a1);
    const large = sweep > Math.PI ? 1 : 0;
    const color = slice.isOther ? OTHER_COLOR : COLORS[i] ?? OTHER_COLOR;
    const pct = Math.round(slice.value * 100);
    const title = slice.label.length > 22 ? slice.label.slice(0, 20) + "…" : slice.label;

    paths += `<path d="M ${x1o} ${y1o} A ${R_OUT} ${R_OUT} 0 ${large} 1 ${x2o} ${y2o} L ${x1i} ${y1i} A ${R_IN} ${R_IN} 0 ${large} 0 ${x2i} ${y2i} Z"
      fill="${color}" class="donut-slice" data-label="${escapeHtml(slice.label)}" data-pct="${pct}">
      <title>${escapeHtml(slice.label)}: ${pct}%</title>
    </path>`;

    angle = a2 + GAP / 2;

    if (!slice.isOther) {
      legendItems += `
        <li class="donut-legend-item">
          <span class="donut-swatch" style="background:${color}"></span>
          <span class="donut-legend-title">${escapeHtml(title)}</span>
          <strong class="donut-legend-pct">${pct}%</strong>
        </li>`;
    }
  });

  // Center label — top film
  const topFilm = cards[0];
  const topPct = Math.round((topFilm?.probability ?? 0) * 100);
  const topTitle = (topFilm?.title ?? "—").length > 16
    ? (topFilm?.title ?? "—").slice(0, 14) + "…"
    : (topFilm?.title ?? "—");

  el.innerHTML = `
    <div class="donut-layout">
      <div class="donut-svg-wrap">
        <svg viewBox="0 0 ${SIZE} ${SIZE}" width="${SIZE}" height="${SIZE}" class="donut-svg">
          ${paths}
          <text x="${CX}" y="${CY - 10}" text-anchor="middle" class="donut-center-pct">${topPct}%</text>
          <text x="${CX}" y="${CY + 10}" text-anchor="middle" class="donut-center-label">${escapeHtml(topTitle)}</text>
          <text x="${CX}" y="${CY + 26}" text-anchor="middle" class="donut-center-sub">frontrunner</text>
        </svg>
      </div>
      <ul class="donut-legend">${legendItems}</ul>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Visual 2 — Race Tightness Gauge
// ---------------------------------------------------------------------------

function renderGauge(cards) {
  const el = document.getElementById("gauge-wrap");
  if (!el) return;

  // Certainty = how dominant the frontrunner is, 0=wide open, 1=near lock
  const p1 = cards[0]?.probability ?? 0;
  const p2 = cards[1]?.probability ?? 0;
  const gap = p1 - p2;
  const certainty = Math.min(1, Math.max(0, gap / 0.6));

  const labels = ["Wide Open", "Competitive", "Leaning", "Likely", "Near Lock"];
  // Zone color for the filled arc based on certainty
  const zoneColor = certainty < 0.2 ? "#5cb88a"
    : certainty < 0.4 ? "#b8c422"
    : certainty < 0.65 ? "#d9941a"
    : certainty < 0.85 ? "#c4621e"
    : "#be3535";

  // SVG: clean minimal speedometer — thin track + filled arc + needle
  const W = 320, H = 200;
  const CX = W / 2, CY = 170;
  const R = 130, trackW = 14;
  const rIn = R - trackW;

  // angle(t) = π*(t-1) maps t∈[0,1] → [-π, 0]; sin≤0 → above CY ✓
  function ptOuter(t) {
    const a = Math.PI * (t - 1);
    return [CX + R * Math.cos(a), CY + R * Math.sin(a)];
  }
  function ptInner(t) {
    const a = Math.PI * (t - 1);
    return [CX + rIn * Math.cos(a), CY + rIn * Math.sin(a)];
  }
  function annulusPath(from, to, color, opacity = 1) {
    const [x1o, y1o] = ptOuter(from);
    const [x2o, y2o] = ptOuter(to);
    const [x1i, y1i] = ptInner(to);
    const [x2i, y2i] = ptInner(from);
    const span = to - from;
    const large = span > 0.5 ? 1 : 0;
    const op = opacity < 1 ? ` opacity="${opacity}"` : "";
    return `<path d="M ${x1o.toFixed(1)} ${y1o.toFixed(1)} A ${R} ${R} 0 ${large} 0 ${x2o.toFixed(1)} ${y2o.toFixed(1)} L ${x1i.toFixed(1)} ${y1i.toFixed(1)} A ${rIn} ${rIn} 0 ${large} 1 ${x2i.toFixed(1)} ${y2i.toFixed(1)} Z" fill="${color}"${op}/>`;
  }

  // Tick marks at each zone label position
  const tickPositions = [
    { t: 0,    label: "Open" },
    { t: 0.5,  label: "" },
    { t: 1,    label: "Lock" },
  ];
  const ticks = tickPositions.map(({ t }) => {
    const a = Math.PI * (t - 1);
    const x1 = CX + (rIn - 5) * Math.cos(a), y1 = CY + (rIn - 5) * Math.sin(a);
    const x2 = CX + (R + 5)   * Math.cos(a), y2 = CY + (R + 5)   * Math.sin(a);
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="var(--surface-1)" stroke-width="1.5" stroke-linecap="round"/>`;
  }).join("\n");

  // Needle
  const needleAngle = Math.PI * (certainty - 1);
  const nLen = rIn - 8;
  const nx = CX + nLen * Math.cos(needleAngle);
  const ny = CY + nLen * Math.sin(needleAngle);

  // Zone label text positions just outside arc ends
  const [lx, ly] = [CX + (R + 18) * Math.cos(Math.PI * -1), CY + (R + 18) * Math.sin(Math.PI * -1)];
  const [rx, ry] = [CX + (R + 18) * Math.cos(0),            CY + (R + 18) * Math.sin(0)];

  const labelIdx = Math.min(4, Math.floor(certainty * 5));
  const raceLabel = labels[labelIdx];
  const gapPct = Math.round(gap * 100);
  const topTitle = cards[0]?.title ?? "—"; // full title, no truncation

  el.innerHTML = `
    <div class="gauge-layout">
      <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" class="gauge-svg">
        <!-- Background track (full arc, muted) -->
        ${annulusPath(0, 1, "var(--surface-2)", 1)}
        <!-- Filled arc up to certainty position -->
        ${certainty > 0.01 ? annulusPath(0, certainty, zoneColor) : ""}
        ${ticks}
        <!-- Needle shadow -->
        <line x1="${CX}" y1="${CY}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"
          stroke="rgba(0,0,0,0.3)" stroke-width="4" stroke-linecap="round"/>
        <!-- Needle -->
        <line x1="${CX}" y1="${CY}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"
          stroke="var(--ink)" stroke-width="2.5" stroke-linecap="round"/>
        <!-- Hub dot -->
        <circle cx="${CX}" cy="${CY}" r="6" fill="var(--ink)"/>
        <!-- Edge labels -->
        <text x="${(lx + 4).toFixed(1)}" y="${(ly + 5).toFixed(1)}" text-anchor="middle" class="gauge-edge-label">Open</text>
        <text x="${(rx - 4).toFixed(1)}" y="${(ry + 5).toFixed(1)}" text-anchor="middle" class="gauge-edge-label">Lock</text>
      </svg>
      <div class="gauge-readout">
        <strong class="gauge-label" style="color:${zoneColor}">${escapeHtml(raceLabel)}</strong>
        <p class="gauge-film">${escapeHtml(topTitle)}</p>
        <p class="gauge-sub">leads the field by <strong>${gapPct}pp</strong></p>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Visual 3 — Signal Matrix
// ---------------------------------------------------------------------------

function renderSignalMatrix(cards) {
  const el = document.getElementById("signal-matrix");
  if (!el) return;

  const PRECURSORS = [
    { key: "pga_win",            label: "PGA" },
    { key: "dga_win",            label: "DGA" },
    { key: "sag_win",            label: "SAG" },
    { key: "bafta_win",          label: "BAFTA" },
    { key: "golden_globe_win",   label: "Globe" },
    { key: "critics_choice_win", label: "Critics" },
  ];

  const top = cards.slice(0, 10);

  // Column headers
  const headers = PRECURSORS.map(p => `<th class="matrix-th">${p.label}</th>`).join("");

  // Rows
  const rows = top.map(card => {
    const cells = PRECURSORS.map(p => {
      const val = card[p.key] ?? 0;
      const won = Number(val) >= 1;
      return `<td class="matrix-cell ${won ? "matrix-win" : "matrix-miss"}" title="${card.title} — ${p.label}: ${won ? "WON" : "Not won"}">
        ${won ? `<span class="matrix-star">★</span>` : `<span class="matrix-dot"></span>`}
      </td>`;
    }).join("");

    const totalWins = PRECURSORS.filter(p => Number(card[p.key] ?? 0) >= 1).length;
    const pct = Math.round((card.probability ?? 0) * 100);
    const rankDelta = card.rank_delta;
    const mvmt = card.movement ?? "same";
    const arrow = mvmt === "up" ? "↑" : mvmt === "down" ? "↓" : mvmt === "new" ? "★" : "";
    const arrowClass = mvmt === "up" ? "up" : mvmt === "down" ? "down" : "";
    const title = card.title.length > 24 ? card.title.slice(0, 22) + "…" : card.title;

    return `<tr class="matrix-row">
      <td class="matrix-film-cell">
        <span class="matrix-rank">#${card.rank}</span>
        <span class="matrix-title" title="${escapeHtml(card.title)}">${escapeHtml(title)}</span>
        ${arrow ? `<span class="matrix-arrow ${arrowClass}">${arrow}</span>` : ""}
      </td>
      ${cells}
      <td class="matrix-wins-cell">
        <span class="matrix-wins-badge ${totalWins >= 4 ? "wins-high" : totalWins >= 2 ? "wins-mid" : "wins-low"}">${totalWins}/6</span>
      </td>
      <td class="matrix-prob-cell">${pct}%</td>
    </tr>`;
  }).join("");

  el.innerHTML = `
    <div class="matrix-scroll">
      <table class="matrix-table">
        <thead>
          <tr>
            <th class="matrix-th matrix-film-th">Film</th>
            ${headers}
            <th class="matrix-th">Wins</th>
            <th class="matrix-th">Odds</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="matrix-legend">
      <span class="matrix-star">★</span> = Precursor win &nbsp;·&nbsp;
      <span class="matrix-dot-inline"></span> = Not won this season
    </p>
  `;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function renderLastUpdated(meta) {
  const el = document.getElementById("site-updated");
  if (!el || !meta?.generated_at) return;
  const d = new Date(meta.generated_at);
  const formatted = d.toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
  el.innerHTML = `<span class="updated-label">Updated</span> <span class="updated-date">${formatted}</span>`;
}

async function main() {
  initTabs();
  try {
    const data = await loadSiteData();
    const sections = [
      () => renderLastUpdated(data.meta),
      () => renderHero(data),
      () => renderContenders(data.forecast_cards ?? []),
      () => renderDonut(data.forecast_cards ?? []),
      () => renderGauge(data.forecast_cards ?? []),
      () => renderSignalMatrix(data.forecast_cards ?? []),
      () => renderMetrics(data),
      () => renderSeasonModes(data),
      () => renderHistoricalYearControls(data),
      () => renderRecentRaces(data.recent_races ?? []),
      () => renderHistory(data.backtest_rows ?? []),
      () => renderMethodology(data.methodology ?? { headline: "", bullets: [] }),
      () => renderSignalsEngine(data.metrics?.feature_count ?? 35),
      () => renderCategoryBoard(data, "actor"),
      () => renderCategoryBoard(data, "actress"),
      () => renderCategoryBoard(data, "director"),
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

// ── Mobile Collapsible Panels ───────────────────────────────────────────
(function initCollapsiblePanels() {
  function setup() {
    if (window.innerWidth > 768) return; // desktop: no collapsing

    document.querySelectorAll(".panel-collapsible").forEach((panel) => {
      const head = panel.querySelector(".panel-head");
      const body = panel.querySelector(".panel-collapse-body");
      if (!head || !body) return;

      // Skip if already initialized
      if (head.dataset.collapsible) return;
      head.dataset.collapsible = "1";

      // Start collapsed if panel is not the first in the tab
      const siblings = Array.from(panel.parentElement?.children ?? []).filter(
        (el) => el.classList.contains("panel-collapsible")
      );
      if (siblings.indexOf(panel) > 0) {
        panel.classList.add("is-collapsed");
      }

      head.addEventListener("click", () => {
        panel.classList.toggle("is-collapsed");
      });
    });
  }

  // Run on load after DOM is ready, and on tab switch
  document.addEventListener("DOMContentLoaded", setup);
  setTimeout(setup, 800); // after main() renders content

  // Re-check on resize crossing the 768px threshold
  let wasMobile = window.innerWidth <= 768;
  window.addEventListener("resize", () => {
    const isMobile = window.innerWidth <= 768;
    if (isMobile && !wasMobile) setup();
    if (!isMobile) {
      // Remove collapsed state on desktop
      document.querySelectorAll(".panel-collapsible.is-collapsed").forEach((p) => {
        p.classList.remove("is-collapsed");
      });
    }
    wasMobile = isMobile;
  });
})();

// ── Dark Mode Toggle ────────────────────────────────────────────────────
(function initDarkMode() {
  const STORAGE_KEY = "rcs-theme";
  const root = document.documentElement;
  const btn = document.getElementById("dark-mode-toggle");
  const icon = document.getElementById("toggle-icon");
  const label = document.getElementById("toggle-label");

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    if (icon) icon.textContent = theme === "dark" ? "☀️" : "🌙";
    if (label) label.textContent = theme === "dark" ? "Light" : "Dark";
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) {}
  }

  // Load saved preference, or default to system preference
  const saved = (() => { try { return localStorage.getItem(STORAGE_KEY); } catch (_) { return null; } })();
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));

  if (btn) {
    btn.addEventListener("click", () => {
      const current = root.getAttribute("data-theme");
      applyTheme(current === "dark" ? "light" : "dark");
    });
  }

  // Sync if system preference changes and user hasn't manually toggled
  window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    try {
      if (!localStorage.getItem(STORAGE_KEY)) applyTheme(e.matches ? "dark" : "light");
    } catch (_) {}
  });
})();

