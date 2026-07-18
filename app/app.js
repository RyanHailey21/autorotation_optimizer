"use strict";

const elements = {
  form: document.querySelector("#configuration"),
  grid: document.querySelector("#airfoil-grid"),
  jobs: document.querySelector("#jobs"),
  jobsOutput: document.querySelector("#jobs-output"),
  force: document.querySelector("#force"),
  refreshPolar: document.querySelector("#refresh-polar"),
  bodyMass: document.querySelector("#body-mass"),
  releaseHeight: document.querySelector("#release-height"),
  radiusMin: document.querySelector("#radius-min"),
  radiusMax: document.querySelector("#radius-max"),
  maxEvaluations: document.querySelector("#max-evaluations"),
  xTolerance: document.querySelector("#x-tolerance"),
  omegaThreshold: document.querySelector("#omega-threshold"),
  run: document.querySelector("#run"),
  cancel: document.querySelector("#cancel"),
  reset: document.querySelector("#reset"),
  selectionCount: document.querySelector("#selection-count"),
  backendHelp: document.querySelector("#backend-help"),
  notice: document.querySelector("#notice"),
  status: document.querySelector("#run-status"),
  progress: document.querySelector("#progress"),
  message: document.querySelector("#run-message"),
  duration: document.querySelector("#run-duration"),
  log: document.querySelector("#log"),
  copyLog: document.querySelector("#copy-log"),
  emptyResult: document.querySelector("#empty-result"),
  resultContent: document.querySelector("#result-content"),
  openReport: document.querySelector("#open-report"),
  bestAirfoil: document.querySelector("#best-airfoil"),
  resultBackend: document.querySelector("#result-backend"),
  fallTime: document.querySelector("#fall-time"),
  impactSpeed: document.querySelector("#impact-speed"),
  totalMass: document.querySelector("#total-mass"),
  maxRpm: document.querySelector("#max-rpm"),
  generatedAt: document.querySelector("#generated-at"),
};

let defaults;
let polling;
let runActive = false;

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function showNotice(message) {
  elements.notice.textContent = message;
  elements.notice.hidden = !message;
}

function selectedAirfoils() {
  return [...elements.grid.querySelectorAll("input:checked")].map(input => input.value);
}

function updateSelectionCount() {
  const count = selectedAirfoils().length;
  elements.selectionCount.textContent = `${count} selected`;
  elements.run.disabled = runActive || count === 0;
}

function renderAirfoils(airfoils, selected) {
  const selectedSet = new Set(selected);
  elements.grid.replaceChildren(...airfoils.map(name => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = name;
    input.checked = selectedSet.has(name);
    input.addEventListener("change", updateSelectionCount);
    const span = document.createElement("span");
    span.textContent = name.replace("NACA", "");
    label.append(input, span);
    return label;
  }));
  updateSelectionCount();
}

function applyDefaults() {
  if (!defaults) return;
  elements.form.elements.backend.value = defaults.backend;
  elements.jobs.value = defaults.jobs;
  elements.jobsOutput.value = defaults.jobs;
  elements.force.checked = defaults.force;
  elements.refreshPolar.checked = defaults.refresh_polar;
  elements.bodyMass.value = defaults.solver.body_mass_kg;
  elements.releaseHeight.value = defaults.solver.release_height_m;
  elements.radiusMin.value = defaults.solver.radius_min_m;
  elements.radiusMax.value = defaults.solver.radius_max_m;
  elements.maxEvaluations.value = defaults.solver.maximum_evaluations;
  elements.xTolerance.value = defaults.solver.relative_x_tolerance;
  elements.omegaThreshold.value = defaults.solver.omega_penalty_threshold_rad_s;
  renderAirfoils(defaults.airfoils, defaults.airfoils);
  updateBackendHelp();
}

function updateBackendHelp() {
  const fallback = elements.form.elements.backend.value === "fallback";
  elements.backendHelp.textContent = fallback
    ? "Approximate coefficients for fast workflow testing; not for engineering conclusions."
    : "Offline NeuralFoil tables; recommended for engineering runs.";
  elements.backendHelp.style.color = fallback ? "var(--warning)" : "";
}

function configuration() {
  return {
    backend: elements.form.elements.backend.value,
    airfoils: selectedAirfoils(),
    jobs: Number(elements.jobs.value),
    force: elements.force.checked,
    refresh_polar: elements.refreshPolar.checked,
    solver: {
      body_mass_kg: Number(elements.bodyMass.value),
      release_height_m: Number(elements.releaseHeight.value),
      radius_min_m: Number(elements.radiusMin.value),
      radius_max_m: Number(elements.radiusMax.value),
      maximum_evaluations: Number(elements.maxEvaluations.value),
      relative_x_tolerance: Number(elements.xTolerance.value),
      omega_penalty_threshold_rad_s: Number(elements.omegaThreshold.value),
    },
  };
}

function formatDuration(run) {
  if (!run?.started_at) return "";
  const end = run.finished_at || Date.now() / 1000;
  const seconds = Math.max(0, Math.round(end - run.started_at));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

function renderRun(run) {
  const active = run && ["queued", "running", "cancelling"].includes(run.status);
  runActive = Boolean(active);
  elements.status.textContent = run ? run.status : "Idle";
  elements.status.className = `status ${run?.status || "idle"}`;
  elements.progress.classList.toggle("active", Boolean(active));
  elements.message.textContent = run?.message || "Ready for a new optimization.";
  elements.duration.textContent = formatDuration(run);
  elements.run.disabled = Boolean(active) || selectedAirfoils().length === 0;
  elements.cancel.hidden = !active;
  [...elements.form.querySelectorAll("input")].forEach(input => input.disabled = Boolean(active));
  document.querySelectorAll("[data-preset]").forEach(button => button.disabled = Boolean(active));
  elements.reset.disabled = Boolean(active);
  if (run?.log?.length) {
    const shouldFollow = elements.log.scrollTop + elements.log.clientHeight >= elements.log.scrollHeight - 30;
    elements.log.textContent = run.log.join("\n");
    if (shouldFollow) elements.log.scrollTop = elements.log.scrollHeight;
  }
  if (run && ["completed", "failed", "cancelled"].includes(run.status)) {
    clearInterval(polling);
    polling = undefined;
    if (run.status === "completed") loadResults();
  }
}

async function pollRun() {
  try {
    const {run} = await request("/api/runs/current");
    renderRun(run);
  } catch (error) {
    showNotice(error.message);
  }
}

function beginPolling() {
  if (!polling) polling = setInterval(pollRun, 850);
  pollRun();
}

function renderResults(summary) {
  const best = summary.best;
  elements.emptyResult.hidden = true;
  elements.resultContent.hidden = false;
  elements.openReport.hidden = false;
  elements.bestAirfoil.textContent = best.airfoil;
  elements.resultBackend.textContent = summary.backend;
  elements.fallTime.textContent = Number(best.fall_time_s).toFixed(2);
  elements.impactSpeed.textContent = Number(best.impact_speed_m_s).toFixed(3);
  elements.totalMass.textContent = Number(best.total_mass_g).toFixed(1);
  elements.maxRpm.textContent = Math.round(best.max_rpm).toLocaleString();
  const generated = new Date(summary.generated_utc);
  elements.generatedAt.textContent = `Generated ${generated.toLocaleString()}`;
}

async function loadResults() {
  try {
    const result = await request("/api/results");
    if (result.available) renderResults(result.summary);
  } catch (error) {
    showNotice(error.message);
  }
}

elements.form.addEventListener("submit", async event => {
  event.preventDefault();
  showNotice("");
  try {
    const {run} = await request("/api/runs", {
      method: "POST",
      body: JSON.stringify(configuration()),
    });
    elements.log.textContent = "Starting optimization workflow…";
    renderRun(run);
    beginPolling();
  } catch (error) {
    showNotice(error.message);
  }
});

elements.form.addEventListener("invalid", event => {
  event.target.closest("details")?.setAttribute("open", "");
  showNotice("Review the highlighted configuration value before starting the run.");
}, true);

elements.cancel.addEventListener("click", async () => {
  try {
    const {run} = await request("/api/runs/current/cancel", {method: "POST", body: "{}"});
    renderRun(run);
  } catch (error) {
    showNotice(error.message);
  }
});

elements.reset.addEventListener("click", applyDefaults);
elements.jobs.addEventListener("input", () => { elements.jobsOutput.value = elements.jobs.value; });
elements.form.addEventListener("change", event => {
  if (event.target.name === "backend") updateBackendHelp();
});
elements.copyLog.addEventListener("click", async () => {
  await navigator.clipboard.writeText(elements.log.textContent);
  elements.copyLog.textContent = "Copied";
  setTimeout(() => { elements.copyLog.textContent = "Copy"; }, 1000);
});

document.querySelectorAll("[data-preset]").forEach(button => {
  button.addEventListener("click", () => {
    const preset = button.dataset.preset;
    elements.grid.querySelectorAll("input").forEach(input => {
      const digits = input.value.slice(4);
      input.checked = preset === "all" || (preset === "symmetric" && digits.startsWith("00")) ||
        (preset === "cambered" && !digits.startsWith("00"));
    });
    updateSelectionCount();
  });
});

async function initialize() {
  try {
    const config = await request("/api/config");
    defaults = config.defaults;
    elements.jobs.max = Math.min(config.maximum_jobs, 16);
    renderAirfoils(config.airfoils, defaults.airfoils);
    applyDefaults();
    await Promise.all([pollRun(), loadResults()]);
    const {run} = await request("/api/runs/current");
    if (run && ["queued", "running", "cancelling"].includes(run.status)) beginPolling();
  } catch (error) {
    showNotice(`Unable to initialize the local application: ${error.message}`);
  }
}

initialize();
