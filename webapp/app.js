const state = {
  municipalities: [],
  municipality: null,
  query: "",
  conceptId: null,
  searchTimer: null,
  suggestionVersion: 0,
};

const $ = (selector) => document.querySelector(selector);
const elements = {
  form: $("#waste-form"), input: $("#waste-input"), search: $("#search-button"),
  suggestions: $("#suggestions"), welcome: $("#welcome"), loading: $("#loading"),
  answer: $("#answer"), notFound: $("#not-found"), error: $("#error"),
  errorMessage: $("#error-message"), placeDialog: $("#place-dialog"),
  placeSearch: $("#place-search"), placeList: $("#place-list"),
  currentPlace: $("#current-place"), detailDialog: $("#detail-dialog"),
  detailTitle: $("#detail-title"), detailContent: $("#detail-content"),
};

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Richiesta non riuscita");
  return body;
}

function hideStates() {
  for (const element of [elements.welcome, elements.loading, elements.answer, elements.notFound, elements.error]) {
    element.hidden = true;
  }
}

function chooseMunicipality(item) {
  state.municipality = item;
  localStorage.setItem("comesibutta.municipality", item.istat_code);
  elements.currentPlace.textContent = item.name;
  elements.input.disabled = false;
  elements.search.disabled = false;
  elements.placeDialog.close();
  hideStates();
  elements.welcome.hidden = false;
  elements.welcome.querySelector("h2").textContent = `Cosa devi buttare a ${item.name}?`;
  elements.welcome.querySelector("p").textContent = "Cerca un oggetto o un materiale: controlleremo le indicazioni pubblicate per questo territorio.";
  elements.input.focus();
}

function renderPlaceList(filter = "") {
  const term = filter.trim().toLocaleLowerCase("it");
  const items = state.municipalities.filter((item) => item.name.toLocaleLowerCase("it").includes(term)).slice(0, 80);
  elements.placeList.innerHTML = items.map((item) => `
    <button type="button" role="option" data-istat="${item.istat_code}">
      <strong>${escapeHtml(item.name)}</strong>
      <small>${escapeHtml([item.province_code, item.operator].filter(Boolean).join(" · "))}</small>
    </button>`).join("") || "<p>Nessun comune trovato.</p>";
}

function openPlaceDialog() {
  elements.placeSearch.value = "";
  renderPlaceList();
  elements.placeDialog.showModal();
  setTimeout(() => elements.placeSearch.focus(), 0);
}

async function showSuggestions() {
  const version = ++state.suggestionVersion;
  const text = elements.input.value.trim();
  if (!state.municipality || text.length < 2) {
    elements.suggestions.hidden = true;
    return;
  }
  try {
    const body = await api(`/api/search?q=${encodeURIComponent(text)}&municipality=${state.municipality.istat_code}&limit=6`);
    if (version !== state.suggestionVersion || text !== elements.input.value.trim()) return;
    const close = body.results.filter((item) => item.score >= .55);
    elements.suggestions.innerHTML = close.map((item) => `
      <button type="button" data-concept="${escapeHtml(item.concept_id)}" data-label="${escapeHtml(item.label)}">
        <strong>${escapeHtml(item.label)}</strong>
        <small>${item.available_in_municipality ? "Indicazione disponibile nel comune" : "Voce del catalogo generale"}</small>
      </button>`).join("");
    elements.suggestions.hidden = close.length === 0;
  } catch (_) {
    elements.suggestions.hidden = true;
  }
}

async function resolveWaste(text, conceptId = null, zoneId = null) {
  if (!state.municipality || !text.trim()) return;
  state.query = text.trim();
  state.suggestionVersion += 1;
  clearTimeout(state.searchTimer);
  if (conceptId) state.conceptId = conceptId;
  if (!conceptId && !zoneId) state.conceptId = null;
  elements.input.value = state.query;
  elements.suggestions.hidden = true;
  hideStates();
  elements.loading.hidden = false;
  try {
    const body = await api("/api/answer", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text: state.query,
        municipality: state.municipality.istat_code,
        concept_id: conceptId || state.conceptId,
        zone_id: zoneId,
        user_type: "domestic",
      }),
    });
    hideStates();
    if (body.status === "resolved") renderAnswer(body);
    else if (body.status === "needs_question" || body.status === "conflict") renderQuestion(body);
    else elements.notFound.hidden = false;
  } catch (error) {
    hideStates();
    elements.errorMessage.textContent = error.message;
    elements.error.hidden = false;
  }
}

function modeLabel(presentation) {
  if (!presentation) return "Non pubblicato";
  const modes = {
    loose: "Sfuso",
    loose_in_container: "Sfuso nel contenitore",
    bag: "In sacchetto",
    bag_unspecified: "In sacchetto",
    bag_in_container: "In sacchetto nel contenitore",
    biodegradable_bag: "In sacchetto biodegradabile",
    compostable_bag: "In sacchetto compostabile",
    closed_bag: "In sacchetto ben chiuso",
    paper_bag: "In sacchetto di carta",
    plastic_bag: "In sacchetto di plastica",
    container: "Nel contenitore",
    bundle: "Legato o in fascine",
    mixed: "Secondo le indicazioni locali",
    source_specific: "Vedi indicazioni",
    unspecified: "Vedi indicazioni",
  };
  return modes[presentation.mode] || presentation.mode;
}

function colorValue(color) {
  const colors = {verde: "#3c8a58", blu: "#3472a8", azzurro: "#55a7c6", giallo: "#e8c33f", marrone: "#805c42", grigio: "#7d8586", bianco: "#f5f5ef", rosso: "#b64c42"};
  return colors[String(color || "").toLowerCase()] || "#d9dfdb";
}

function statusLabel(status) {
  return ({open: "Aperto", closed: "Chiuso", temporarily_closed: "Temporaneamente chiuso", unknown: "Stato non pubblicato"})[status] || status;
}

function renderService(service, index, kind) {
  const title = service.name || service.preferred_label || (kind === "facility" ? "Centro di raccolta" : "Servizio");
  const subtitle = service.address || service.access_summary || service.status_raw || "Consulta i dettagli pubblicati";
  return `<article class="service-card">
    <h3>${escapeHtml(title)}</h3>
    <p>${escapeHtml(subtitle)}</p>
    ${service.operational_status ? `<strong>${escapeHtml(statusLabel(service.operational_status))}</strong>` : ""}
    ${service.distance_km != null ? `<p>${escapeHtml(service.distance_km)} km dalla posizione indicata</p>` : ""}
    <button type="button" data-detail-kind="${kind}" data-detail-index="${index}">Dettagli</button>
  </article>`;
}

function renderAnswer(body) {
  const result = body.result;
  const facilities = [result.facility, ...(result.facility_alternatives || [])].filter(Boolean);
  const services = result.channel_services || [];
  const presentationInstructions = result.presentation?.instructions || [];
  const sources = body.provenance.sources || [];
  elements.answer.innerHTML = `
    <div class="answer-head"><div class="answer-inner">
      <p class="eyebrow">Indicazione per ${escapeHtml(state.municipality.name)}</p>
      <h2>${escapeHtml(body.query.matched_label || state.query)}</h2>
      <div class="destination">
        <span class="destination-symbol" aria-hidden="true">↓</span>
        <div><span>Destinazione</span><strong>${escapeHtml(result.stream || result.source_destination || "Servizio dedicato")}</strong></div>
      </div>
    </div></div>
    <div class="answer-band"><div class="answer-inner">
      <div class="facts">
        <div class="fact"><span class="fact-label">Come conferirlo</span><strong>${escapeHtml(modeLabel(result.presentation))}</strong>${presentationInstructions.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</div>
        <div class="fact"><span class="fact-label">Contenitore</span><strong>${result.container?.color ? `<i class="swatch" style="background:${colorValue(result.container.color)}"></i>${escapeHtml(result.container.color)}` : "Non pubblicato"}</strong><p>${escapeHtml(result.container?.type || "")}</p></div>
        <div class="fact"><span class="fact-label">Codice EER</span><strong>${escapeHtml(result.eer?.code || "Non associato")}</strong><p>${escapeHtml(result.eer?.official_label || "")}</p>${result.eer?.hazardous ? "<p><strong>Rifiuto pericoloso</strong></p>" : ""}</div>
      </div>
      ${(result.warnings || []).length ? `<div class="warning-list">${result.warnings.map((item) => `<div class="warning">${escapeHtml(item)}</div>`).join("")}</div>` : ""}
    </div></div>
    ${(facilities.length || services.length) ? `<div class="answer-band"><div class="answer-inner"><h2>Servizi disponibili</h2><div class="service-list">${facilities.map((item, index) => renderService(item, index, "facility")).join("")}${services.map((item, index) => renderService(item, index, "service")).join("")}</div></div></div>` : ""}
    ${result.environmental_note ? `<div class="answer-band"><div class="answer-inner"><p class="eyebrow">Perché è importante</p><h2>Impatto ambientale</h2><p>${escapeHtml(result.environmental_note)}</p></div></div>` : ""}
    <div class="answer-band"><div class="answer-inner"><h2>Fonti</h2><ul class="source-list">${sources.map((source) => `<li><a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.label || "Fonte ufficiale")}</a> <small>consultata il ${escapeHtml(source.retrieved_at.slice(0, 10))}</small></li>`).join("") || "<li>Nessuna fonte allegata alla risposta.</li>"}</ul><p class="revision">Revisione dati ${escapeHtml(body.provenance.dataset_revision)} · risposta ${escapeHtml(body.provenance.review_status)}</p></div></div>`;
  elements.answer.hidden = false;
  elements.answer._data = {facilities, services};
}

function renderQuestion(body) {
  const question = body.question || {text: "Quale rifiuto intendi?", options: []};
  elements.answer.innerHTML = `<div class="answer-band"><div class="answer-inner">
    <p class="eyebrow">Serve una precisazione</p><h2>${escapeHtml(question.text)}</h2>
    <div class="question-options">${question.options.map((option) => `<button type="button" data-choice="${escapeHtml(option.id)}">${escapeHtml(option.label)}</button>`).join("")}</div>
  </div></div>`;
  elements.answer.hidden = false;
  elements.answer._questionKind = question.text.toLocaleLowerCase("it").includes("zona") ? "zone" : "concept";
}

function detailRows(service) {
  const rows = [];
  const add = (label, value) => { if (value !== null && value !== undefined && value !== "") rows.push(`<div class="detail-row"><span>${escapeHtml(label)}</span>${escapeHtml(value)}</div>`); };
  add("Indirizzo", service.address);
  add("Stato", service.operational_status ? statusLabel(service.operational_status) : service.status);
  add("Accesso", service.access_summary || service.access_notes_raw);
  add("Prenotazione", service.booking_required === true ? "Obbligatoria" : service.booking_required === false ? "Non richiesta" : null);
  add("Telefono", service.phone);
  add("Email", service.email);
  for (const method of service.booking_methods || []) {
    const labels = {phone: "Prenota per telefono", web: "Prenota online", email: "Prenota via email"};
    add(labels[method.method] || "Prenotazione", [method.value, method.hours_raw].filter(Boolean).join(" · "));
  }
  add("Limite", service.quantity_limit || (service.max_items ? `${service.max_items} pezzi` : null));
  add("Istruzioni", service.instructions);
  if (service.acceptance) add("Accettazione", service.acceptance.status.replaceAll("_", " "));
  for (const period of service.opening_periods || []) {
    const intervals = (period.weekly_intervals || []).map((item) => `${["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"][item.weekday - 1] || item.weekday} ${item.opens}–${item.closes}`).join(", ");
    add(period.period_label || "Orari", intervals || period.exceptions);
  }
  const urls = service.information_urls || [];
  if (urls.length) rows.push(`<div class="detail-row"><span>Informazioni ufficiali</span>${urls.map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">Apri la pagina</a>`).join(" · ")}</div>`);
  return rows.join("") || "<p>Nessun altro dettaglio pubblicato.</p>";
}

elements.form.addEventListener("submit", (event) => { event.preventDefault(); resolveWaste(elements.input.value); });
elements.input.addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(showSuggestions, 180); });
elements.suggestions.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-concept]");
  if (button) resolveWaste(button.dataset.label, button.dataset.concept);
});
elements.answer.addEventListener("click", (event) => {
  const choice = event.target.closest("button[data-choice]");
  if (choice) {
    const isZone = elements.answer._questionKind === "zone";
    resolveWaste(state.query, isZone ? null : choice.dataset.choice, isZone ? choice.dataset.choice : null);
    return;
  }
  const detail = event.target.closest("button[data-detail-kind]");
  if (detail) {
    const list = detail.dataset.detailKind === "facility" ? elements.answer._data.facilities : elements.answer._data.services;
    const service = list[Number(detail.dataset.detailIndex)];
    elements.detailTitle.textContent = service.name || service.preferred_label || "Dettagli del servizio";
    elements.detailContent.innerHTML = detailRows(service);
    elements.detailDialog.showModal();
  }
});
elements.placeSearch.addEventListener("input", () => renderPlaceList(elements.placeSearch.value));
elements.placeList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-istat]");
  if (button) chooseMunicipality(state.municipalities.find((item) => item.istat_code === button.dataset.istat));
});
for (const button of document.querySelectorAll("#change-place, #choose-place")) button.addEventListener("click", openPlaceDialog);
for (const button of document.querySelectorAll("[data-query]")) button.addEventListener("click", () => {
  if (!state.municipality) return openPlaceDialog();
  elements.input.value = button.dataset.query;
  resolveWaste(button.dataset.query);
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".waste-form")) elements.suggestions.hidden = true;
});

async function initialize() {
  try {
    const body = await api("/api/municipalities");
    state.municipalities = body.municipalities;
    const remembered = localStorage.getItem("comesibutta.municipality");
    const municipality = state.municipalities.find((item) => item.istat_code === remembered);
    if (municipality) chooseMunicipality(municipality);
  } catch (error) {
    hideStates();
    elements.errorMessage.textContent = error.message;
    elements.error.hidden = false;
  }
}

initialize();
