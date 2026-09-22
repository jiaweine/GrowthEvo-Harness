const $ = (selector) => document.querySelector(selector);

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderEvidence(items) {
  const grid = $("#evidence-grid");
  grid.replaceChildren();

  for (const item of items) {
    const card = node("article", "evidence-card");
    const top = node("div", "card-top");
    const titleWrap = node("div");
    titleWrap.append(node("span", "kicker", item.kind), node("h3", "", item.name));
    top.append(titleWrap, node("span", "badge", "LOCKED"));
    card.append(top);

    const winner = node("p", "winner");
    winner.append("Validation winner · ", node("strong", "", item.winner));
    card.append(winner);

    const metrics = node("div", "metric-grid");
    for (const metric of item.metrics) {
      const box = node("div", "metric");
      box.append(node("span", "", metric.label), node("strong", "", metric.value));
      metrics.append(box);
    }
    card.append(metrics);

    const footer = node("div", "card-footer");
    footer.append(node("code", "", item.commit.slice(0, 12)));
    const link = node("a", "", "Evidence bundle ↗");
    link.href = item.href;
    link.target = "_blank";
    link.rel = "noreferrer";
    footer.append(link);
    card.append(footer);
    grid.append(card);
  }
}

function renderCapabilities(items) {
  const grid = $("#capability-grid");
  grid.replaceChildren();

  items.forEach((item, index) => {
    const card = node("article", "capability-card");
    card.append(
      node("span", "cap-index", String(index + 1).padStart(2, "0")),
      node("h3", "", item.name),
      node("p", "", item.detail),
      node("div", "module", item.module),
    );
    grid.append(card);
  });
}

function renderArchitecture(items) {
  const stack = $("#architecture-stack");
  stack.replaceChildren();

  items.forEach((item, index) => {
    const card = node("article");
    card.append(
      node("span", "step", "0" + (index + 1)),
      node("h3", "", item.name),
      node("p", "", item.detail),
    );
    stack.append(card);
  });
}

async function boot() {
  try {
    const response = await fetch("/api/dashboard", {headers: {"Accept": "application/json"}});
    if (!response.ok) throw new Error("dashboard request failed: " + response.status);
    const data = await response.json();

    $("#service-status").textContent = "Healthy";
    $("#version").textContent = data.project.version;
    $("#api-version").textContent = data.summary.api_version;
    $("#tagline").textContent = data.project.tagline + ". The web layer stays read-only so evidence and execution governance remain explicit.";

    renderEvidence(data.evidence);
    renderCapabilities(data.capabilities);
    renderArchitecture(data.architecture);
  } catch (error) {
    $("#service-status").textContent = "Unavailable";
    const grid = $("#evidence-grid");
    const message = node("div", "error", "The dashboard API could not be loaded. Check the server logs and /api/health.");
    grid.replaceChildren(message);
    console.error(error);
  }
}

boot();
