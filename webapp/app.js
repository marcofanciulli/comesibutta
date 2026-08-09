const state = {
  municipalities: [],
  municipality: null,
  zoneId: null,
  zoneLabel: null,
  datasetRevision: null,
  location: null,
  query: "",
  conceptId: null,
  searchTimer: null,
  suggestionVersion: 0,
  view: "search",
  serviceView: "facilities",
  territory: null,
  territoryVersion: 0,
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
  notFoundEyebrow: $("#not-found-eyebrow"), notFoundTitle: $("#not-found-title"),
  notFoundMessage: $("#not-found-message"),
  zonePreference: $("#zone-preference"), currentZone: $("#current-zone"),
  clearZone: $("#clear-zone"),
  detectPlace: $("#detect-place"), locationStatus: $("#location-status"),
  positionPreference: $("#position-preference"), clearPosition: $("#clear-position"),
  searchView: $("#search-view"), rulesView: $("#rules-view"),
  centresView: $("#centres-view"), rulesContent: $("#rules-content"),
  centresContent: $("#centres-content"), rulesIntro: $("#rules-intro"),
  centresIntro: $("#centres-intro"), rulesFilters: $("#rules-filters"),
  rulesZone: $("#rules-zone"), rulesStream: $("#rules-stream"),
  rulesPreparation: $("#rules-preparation"),
  facilityCount: $("#facility-count"), pointCount: $("#point-count"),
  pickupCount: $("#pickup-count"),
  externalDialog: $("#external-dialog"), externalContent: $("#external-content"),
  externalTitle: $("#external-title"), externalOrigin: $("#external-origin"),
  externalFallback: $("#external-fallback"), closeExternal: $("#close-external"),
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

function chooseMunicipality(item, {preserveLocation = false} = {}) {
  if (!preserveLocation) state.location = null;
  state.municipality = item;
  localStorage.setItem("comesibutta.municipality", item.istat_code);
  const storedZone = localStorage.getItem(`comesibutta.zone.${item.istat_code}`);
  try {
    const preference = storedZone ? JSON.parse(storedZone) : null;
    const isCurrent = preference?.datasetRevision === state.datasetRevision;
    state.zoneId = isCurrent ? preference.id : null;
    state.zoneLabel = isCurrent ? preference.label : null;
  } catch (_) {
    state.zoneId = null;
    state.zoneLabel = null;
  }
  updatePlaceControls();
  elements.input.disabled = false;
  elements.search.disabled = false;
  elements.placeDialog.close();
  hideStates();
  elements.welcome.hidden = false;
  elements.welcome.querySelector("h2").textContent = `Cosa devi buttare a ${item.name}?`;
  elements.welcome.querySelector("p").textContent = "Cerca un oggetto o un materiale: controlleremo le indicazioni pubblicate per questo territorio.";
  if (state.view === "search") elements.input.focus();
  state.territory = null;
  if (state.view !== "search") loadTerritory();
}

function updatePlaceControls() {
  elements.currentPlace.textContent = [state.municipality?.name, state.zoneLabel].filter(Boolean).join(" · ") || "Scegli il comune";
  elements.zonePreference.hidden = !state.zoneId;
  elements.currentZone.textContent = state.zoneLabel ? `Zona attiva: ${state.zoneLabel}` : "";
  elements.positionPreference.hidden = !state.location;
}

function clearLocation() {
  state.location = null;
  elements.locationStatus.textContent = "";
  updatePlaceControls();
  state.territory = null;
  if (state.view !== "search") loadTerritory();
}

function locateMunicipality() {
  if (!navigator.geolocation) {
    elements.locationStatus.textContent = "La posizione non è disponibile su questo dispositivo.";
    return;
  }
  elements.detectPlace.disabled = true;
  elements.locationStatus.textContent = "Ricerca della posizione in corso…";
  navigator.geolocation.getCurrentPosition(async (position) => {
    const location = {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy: position.coords.accuracy,
    };
    try {
      const body = await api("/api/locate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(location),
      });
      if (body.status === "resolved") {
        state.location = location;
        const detected = state.municipalities.find(
          (item) => item.istat_code === body.municipalities[0].istat_code,
        );
        if (detected) {
          elements.locationStatus.textContent = `Posizione rilevata: ${detected.name}.`;
          chooseMunicipality(detected, {preserveLocation: true});
        }
      } else if (body.status === "boundary_ambiguous") {
        state.location = location;
        const codes = new Set(body.municipalities.map((item) => item.istat_code));
        elements.placeList.innerHTML = state.municipalities
          .filter((item) => codes.has(item.istat_code))
          .map((item) => `<button type="button" role="option" data-istat="${item.istat_code}" data-location-choice="true"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.province_code || "")}</small></button>`)
          .join("");
        elements.locationStatus.textContent = "La posizione è sul confine: scegli il comune corretto.";
        updatePlaceControls();
      } else {
        elements.locationStatus.textContent = "La posizione non ricade in un comune toscano supportato.";
      }
    } catch (error) {
      elements.locationStatus.textContent = error.message;
    } finally {
      elements.detectPlace.disabled = false;
    }
  }, (error) => {
    const messages = {
      1: "Permesso per la posizione non concesso.",
      2: "Posizione non disponibile.",
      3: "Tempo scaduto durante la ricerca della posizione.",
    };
    elements.locationStatus.textContent = messages[error.code] || "Non è stato possibile rilevare la posizione.";
    elements.detectPlace.disabled = false;
  }, {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
}

function rememberZone(id, label) {
  state.zoneId = id;
  state.zoneLabel = label;
  localStorage.setItem(`comesibutta.zone.${state.municipality.istat_code}`, JSON.stringify({
    id, label, datasetRevision: state.datasetRevision,
  }));
  state.territory = null;
  updatePlaceControls();
}

function clearRememberedZone() {
  if (state.municipality) localStorage.removeItem(`comesibutta.zone.${state.municipality.istat_code}`);
  state.zoneId = null;
  state.zoneLabel = null;
  updatePlaceControls();
  state.territory = null;
  if (state.view !== "search") loadTerritory();
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

function safeUrl(value) {
  if (typeof value !== "string" || !value) return null;
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:", "tel:", "mailto:"].includes(url.protocol) ? value : null;
  } catch (_) {
    return null;
  }
}

function sourceLink(url, label = "Fonte ufficiale") {
  const safe = safeUrl(url);
  return safe ? `<a class="source-link" href="${escapeHtml(safe)}" data-external-url="${escapeHtml(safe)}" data-external-title="${escapeHtml(label)}">${escapeHtml(label)}</a>` : "";
}

async function openExternalDialog(url, title = "Fonte ufficiale") {
  const safe = safeUrl(url);
  if (!safe) return;
  const parsed = new URL(safe, window.location.origin);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    window.location.href = safe;
    return;
  }
  elements.externalTitle.textContent = title;
  elements.externalOrigin.textContent = parsed.hostname.replace(/^www\./, "");
  elements.externalFallback.href = parsed.href;
  elements.externalContent.innerHTML = '<p class="external-loading">Caricamento delle evidenze conservate…</p>';
  elements.externalDialog.showModal();
  try {
    const preview = await api("/api/source-preview", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: parsed.href}),
    });
    if (!elements.externalDialog.open || elements.externalFallback.href !== parsed.href) return;
    renderExternalPreview(preview);
  } catch (error) {
    if (!elements.externalDialog.open) return;
    elements.externalContent.innerHTML = `<p class="external-empty">${escapeHtml(error.message)} La fonte originale resta disponibile dal collegamento sottostante.</p>`;
  }
}

function closeExternalDialog() {
  elements.externalDialog.close();
  elements.externalContent.replaceChildren();
}

function renderExternalPreview(preview) {
  const source = preview.source || {};
  const metadata = [
    source.publisher,
    source.retrieved_at ? `consultata il ${source.retrieved_at.slice(0, 10)}` : null,
    source.document_date ? `documento del ${source.document_date}` : null,
  ].filter(Boolean);
  const evidence = preview.evidence || [];
  elements.externalContent.innerHTML = `
    ${metadata.length ? `<p class="external-metadata">${metadata.map(escapeHtml).join(" · ")}</p>` : ""}
    ${evidence.length ? `<div class="evidence-list">${evidence.map((item) => `
      <blockquote>
        <p>${escapeHtml(item.quote)}</p>
        ${item.page ? `<cite>Pagina ${escapeHtml(item.page)}</cite>` : ""}
      </blockquote>`).join("")}</div>` : '<p class="external-empty">La fonte è registrata, ma non contiene un estratto testuale visualizzabile.</p>'}
    ${preview.evidence_total > evidence.length ? `<p class="external-count">Sono mostrati ${evidence.length} estratti su ${preview.evidence_total} conservati.</p>` : ""}`;
}

function setView(view, {updateHistory = true} = {}) {
  state.view = ["search", "rules", "centres"].includes(view) ? view : "search";
  elements.searchView.hidden = state.view !== "search";
  elements.rulesView.hidden = state.view !== "rules";
  elements.centresView.hidden = state.view !== "centres";
  for (const button of document.querySelectorAll("[data-view]")) {
    button.setAttribute("aria-selected", String(button.dataset.view === state.view));
  }
  if (updateHistory) history.replaceState(null, "", `#view=${state.view}`);
  if (state.view !== "search") loadTerritory();
}

function territoryRequest() {
  return api("/api/territory", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      municipality: state.municipality.istat_code,
      user_type: "domestic",
      zone_id: state.zoneId,
      latitude: state.location?.latitude,
      longitude: state.location?.longitude,
    }),
  });
}

function territoryLoading(target) {
  target.innerHTML = '<p class="territory-loading">Caricamento delle informazioni pubblicate…</p>';
}

function preparationLabel(mode) {
  const labels = {
    loose: "Sfuso", loose_in_container: "Sfuso nel contenitore",
    bag: "In sacchetto", bag_unspecified: "In sacchetto",
    bag_in_container: "In sacchetto nel contenitore",
    biodegradable_bag: "Sacchetto biodegradabile",
    compostable_bag: "Sacchetto compostabile", closed_bag: "Sacchetto chiuso",
    paper_bag: "Sacchetto di carta", plastic_bag: "Sacchetto di plastica",
    container: "Nel contenitore", mixed: "Indicazioni diverse",
    source_specific: "Istruzioni del gestore", unspecified: "Non pubblicato",
  };
  return labels[mode] || "Non pubblicato";
}

function methodLabel(method) {
  const labels = {
    door_to_door: "Porta a porta", roadside: "Raccolta stradale", street: "Raccolta stradale",
    collection_centre: "Centro di raccolta", collection_point: "Punto di raccolta",
    other: "Modalità del gestore",
  };
  return labels[method] || method || "Modalità non pubblicata";
}

function accessCredentialLabel(value) {
  const labels = {
    not_currently_required: "Nessuna credenziale richiesta",
    "6Card": "6Card",
    "RFID tag": "Chiave o tessera RFID",
  };
  return labels[value] || value;
}

function renderRules(data) {
  elements.rulesIntro.textContent = `Indicazioni pubblicate per ${data.municipality.name}${data.municipality.operator ? ` da ${data.municipality.operator}` : ""}.`;
  const zoneValue = state.zoneId || "";
  elements.rulesZone.innerHTML = [
    '<option value="">Tutte le zone</option>',
    ...data.zones.map((zone) => `<option value="${escapeHtml(zone.id)}">${escapeHtml(zone.name)}</option>`),
  ].join("");
  elements.rulesZone.value = zoneValue;
  const streams = [...new Set(data.rules.map((rule) => rule.stream).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right, "it"));
  const previousStream = elements.rulesStream.value;
  elements.rulesStream.innerHTML = [
    '<option value="">Tutte le frazioni</option>',
    ...streams.map((stream) => `<option value="${escapeHtml(stream)}">${escapeHtml(stream)}</option>`),
  ].join("");
  if (streams.includes(previousStream)) elements.rulesStream.value = previousStream;
  const modes = [...new Set(data.rules.map((rule) => rule.presentation_mode).filter(Boolean))]
    .sort((left, right) => preparationLabel(left).localeCompare(preparationLabel(right), "it"));
  const previousMode = elements.rulesPreparation.value;
  elements.rulesPreparation.innerHTML = [
    '<option value="">Tutte le preparazioni</option>',
    ...modes.map((mode) => `<option value="${escapeHtml(mode)}">${escapeHtml(preparationLabel(mode))}</option>`),
  ].join("");
  if (modes.includes(previousMode)) elements.rulesPreparation.value = previousMode;
  elements.rulesFilters.hidden = data.zones.length === 0 && streams.length < 2 && modes.length < 2;
  renderRuleRows(data);
}

function renderRuleRows(data) {
  const streamFilter = elements.rulesStream.value;
  const preparationFilter = elements.rulesPreparation.value;
  const rules = data.rules.filter((rule) => (
    (!streamFilter || rule.stream === streamFilter)
    && (!preparationFilter || rule.presentation_mode === preparationFilter)
  ));
  if (!rules.length) {
    elements.rulesContent.innerHTML = '<p class="territory-empty">La fonte non pubblica regole compatibili con i filtri selezionati.</p>';
    return;
  }
  const groups = new Map();
  for (const rule of rules) {
    const group = rule.zone_name || (data.zones.length > 1 ? "Regole comuni a tutte le zone" : "Raccolte disponibili");
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(rule);
  }
  elements.rulesContent.innerHTML = [...groups.entries()].map(([group, items]) => `
    <section class="rule-group">
      <h2>${escapeHtml(group)}</h2>
      ${items.map((rule) => {
        const container = [rule.container_type, rule.container_color].filter(Boolean).join(" · ");
        const source = rule.source_urls?.[0];
        return `<article class="rule-row">
          <div>
            <h3>${escapeHtml(rule.stream || "Frazione non specificata")}</h3>
            <div class="rule-meta">
              <span>${escapeHtml(methodLabel(rule.collection_method))}</span>
              ${container ? `<span>${escapeHtml(container)}</span>` : ""}
              <span>${escapeHtml(preparationLabel(rule.presentation_mode))}</span>
            </div>
          </div>
          <div class="rule-details">
            ${rule.instructions ? `<p><strong>Come conferirlo</strong><br>${escapeHtml(rule.instructions)}</p>` : ""}
            ${rule.schedule ? `<p><strong>Quando</strong><br>${escapeHtml(rule.schedule)}</p>` : ""}
            ${rule.access_credential ? `<p><strong>Accesso</strong><br>${escapeHtml(accessCredentialLabel(rule.access_credential))}</p>` : ""}
            ${sourceLink(source)}
          </div>
        </article>`;
      }).join("")}
    </section>`).join("");
}

function statusLabelCompact(status) {
  const labels = {
    open: "Aperto", active: "Attivo", closed: "Chiuso",
    temporarily_closed: "Chiuso temporaneamente", unknown: "Stato non pubblicato",
  };
  return labels[status] || "Stato non pubblicato";
}

function directoryCard(item, kind, index) {
  const status = kind === "facility" ? item.operational_status : null;
  const acceptedCount = kind === "facility"
    ? item.accepted_waste.length
    : kind === "point" ? (item.accepted_waste || []).length : 0;
  const subtitle = item.address || item.zone_name || (kind === "pickup" ? item.accepted_waste : "") || "";
  return `<article class="directory-card">
    <div class="directory-card-head">
      <h2>${escapeHtml(item.name || (kind === "pickup" ? "Ritiro a domicilio" : "Punto di raccolta"))}</h2>
      ${status ? `<span class="status-badge ${escapeHtml(status)}">${escapeHtml(statusLabelCompact(status))}</span>` : ""}
    </div>
    ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
    <div class="service-facts">
      ${item.distance_km !== null && item.distance_km !== undefined ? `<span>${escapeHtml(item.distance_km)} km</span>` : ""}
      ${acceptedCount ? `<span>${acceptedCount} ${acceptedCount === 1 ? "materiale" : "materiali"}</span>` : ""}
      ${item.schedule ? `<span>${escapeHtml(item.schedule)}</span>` : ""}
      ${kind === "pickup" && item.booking_required ? "<span>Prenotazione richiesta</span>" : ""}
    </div>
    <button class="text-button" type="button" data-territory-kind="${kind}" data-territory-index="${index}">Dettagli</button>
  </article>`;
}

function renderCentres(data) {
  elements.centresIntro.textContent = `Servizi accessibili alle utenze domestiche di ${data.municipality.name}.`;
  elements.facilityCount.textContent = data.facilities.length;
  elements.pointCount.textContent = data.collection_points.length;
  elements.pickupCount.textContent = data.pickup_services.length;
  elements.centresView._data = data;
  renderServiceDirectory();
}

function renderServiceDirectory() {
  const data = elements.centresView._data;
  if (!data) return;
  const views = {
    facilities: [data.facilities, "facility", "La fonte non pubblica centri accessibili per questo comune."],
    points: [data.collection_points, "point", "La fonte non pubblica punti di raccolta per questo comune."],
    pickups: [data.pickup_services, "pickup", "La fonte non pubblica servizi di ritiro per questo comune."],
  };
  const [items, kind, empty] = views[state.serviceView];
  elements.centresContent.innerHTML = items.length
    ? `<div class="directory-list">${items.map((item, index) => directoryCard(item, kind, index)).join("")}</div>`
    : `<p class="territory-empty">${escapeHtml(empty)}</p>`;
}

async function loadTerritory() {
  if (!state.municipality) {
    const target = state.view === "rules" ? elements.rulesContent : elements.centresContent;
    target.innerHTML = '<p class="territory-empty">Seleziona un comune per consultarne le informazioni.</p>';
    return;
  }
  if (state.territory) {
    renderRules(state.territory);
    renderCentres(state.territory);
    return;
  }
  const version = ++state.territoryVersion;
  const target = state.view === "rules" ? elements.rulesContent : elements.centresContent;
  territoryLoading(target);
  try {
    const data = await territoryRequest();
    if (version !== state.territoryVersion) return;
    state.territory = data;
    renderRules(data);
    renderCentres(data);
  } catch (error) {
    if (version !== state.territoryVersion) return;
    target.innerHTML = `<p class="territory-empty">${escapeHtml(error.message)}</p>`;
  }
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

async function resolveWaste(text, conceptId = null, zoneId = undefined) {
  if (!state.municipality || !text.trim()) return;
  state.query = text.trim();
  state.suggestionVersion += 1;
  clearTimeout(state.searchTimer);
  if (conceptId) state.conceptId = conceptId;
  if (!conceptId && zoneId === undefined) state.conceptId = null;
  const effectiveZoneId = zoneId === undefined ? state.zoneId : zoneId;
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
        zone_id: effectiveZoneId,
        user_type: "domestic",
        latitude: state.location?.latitude,
        longitude: state.location?.longitude,
      }),
    });
    hideStates();
    if (body.status === "resolved") renderAnswer(body);
    else if (body.status === "needs_question" || body.status === "conflict") renderQuestion(body);
    else renderNotFound(body);
  } catch (error) {
    hideStates();
    elements.errorMessage.textContent = error.message;
    elements.error.hidden = false;
  }
}

function renderNotFound(body) {
  if (body.query?.matched_concept_id) {
    elements.notFoundEyebrow.textContent = "Rifiuto riconosciuto";
    elements.notFoundTitle.textContent = `Manca una destinazione verificata per ${state.municipality.name}`;
    elements.notFoundMessage.textContent = `Abbiamo riconosciuto “${body.query.matched_label}”, ma le fonti disponibili non permettono ancora di collegarlo a una raccolta o a un centro accessibile in questo comune.`;
  } else {
    elements.notFoundEyebrow.textContent = "Nessuna risposta certa";
    elements.notFoundTitle.textContent = "Prova a descriverlo in un altro modo";
    elements.notFoundMessage.textContent = body.feedback?.recorded
      ? "La ricerca è stata registrata per ampliare il vocabolario. Nel frattempo prova a indicare l’oggetto e, se puoi, il materiale."
      : "Indica l’oggetto e, se puoi, il materiale. Non suggeriamo una destinazione quando i dati non bastano.";
  }
  elements.notFound.hidden = false;
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

function acceptanceLabel(status) {
  return ({
    verified_eer: "Accettazione verificata tramite codice EER",
    verified_description: "Accettazione verificata dalla descrizione pubblicata",
    acceptance_not_published: "Elenco dei rifiuti accettati non pubblicato",
    not_listed: "Rifiuto non presente nell’elenco pubblicato",
  })[status] || "Stato dell’accettazione non disponibile";
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
        <div class="fact"><span class="fact-label">Codice EER</span><strong>${escapeHtml(result.eer?.code || "Non associato")}</strong><p>${escapeHtml(result.eer?.official_label || "")}</p>${result.eer?.condition ? `<p>${escapeHtml(result.eer.condition)}</p>` : ""}${result.eer?.hazardous ? "<p><strong>Rifiuto pericoloso</strong></p>" : ""}${(result.eer_alternatives || []).length ? `<p><strong>Altri codici possibili secondo l'origine:</strong> ${result.eer_alternatives.map((item) => `${escapeHtml(item.code)} - ${escapeHtml(item.official_label)}${item.condition ? ` (${escapeHtml(item.condition)})` : ""}`).join("; ")}</p>` : ""}</div>
      </div>
      ${(result.warnings || []).length ? `<div class="warning-list">${result.warnings.map((item) => `<div class="warning">${escapeHtml(item)}</div>`).join("")}</div>` : ""}
    </div></div>
    ${(facilities.length || services.length) ? `<div class="answer-band"><div class="answer-inner"><h2>Servizi disponibili</h2><div class="service-list">${facilities.map((item, index) => renderService(item, index, "facility")).join("")}${services.map((item, index) => renderService(item, index, "service")).join("")}</div></div></div>` : ""}
    ${result.environmental_note ? `<div class="answer-band"><div class="answer-inner"><p class="eyebrow">Perché è importante</p><h2>Impatto ambientale</h2><p>${escapeHtml(result.environmental_note)}</p></div></div>` : ""}
    <div class="answer-band"><div class="answer-inner"><h2>Fonti</h2><ul class="source-list">${sources.map((source) => `<li>${sourceLink(source.url, source.label || "Fonte ufficiale")} <small>consultata il ${escapeHtml(source.retrieved_at.slice(0, 10))}</small></li>`).join("") || "<li>Nessuna fonte allegata alla risposta.</li>"}</ul><p class="revision">Revisione dati ${escapeHtml(body.provenance.dataset_revision)} · risposta ${escapeHtml(body.provenance.review_status)}</p></div></div>`;
  elements.answer.hidden = false;
  elements.answer._data = {facilities, services};
}

function renderQuestion(body) {
  const question = body.question || {text: "Quale rifiuto intendi?", options: []};
  elements.answer.innerHTML = `<div class="answer-band"><div class="answer-inner">
    <p class="eyebrow">Serve una precisazione</p><h2>${escapeHtml(question.text)}</h2>
    <div class="question-options">${question.options.map((option) => `<button type="button" data-choice="${escapeHtml(option.id)}" data-choice-label="${escapeHtml(option.label)}"><strong>${escapeHtml(option.label)}</strong>${option.hint ? `<span>${escapeHtml(option.hint)}</span>` : ""}</button>`).join("")}</div>
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
  add("Distanza", service.distance_km !== null && service.distance_km !== undefined ? `${service.distance_km} km` : null);
  for (const method of service.booking_methods || []) {
    const labels = {phone: "Prenota per telefono", web: "Prenota online", email: "Prenota via email"};
    const value = [method.value, method.hours_raw].filter(Boolean).join(" · ");
    const url = method.method === "web" ? safeUrl(method.value) : null;
    if (url) rows.push(`<div class="detail-row"><span>${escapeHtml(labels[method.method] || "Prenotazione")}</span>${sourceLink(url, "Apri la prenotazione")}</div>`);
    else add(labels[method.method] || "Prenotazione", value);
  }
  add("Limite", service.quantity_limit || (service.max_items ? `${service.max_items} pezzi` : null));
  add("Istruzioni", service.instructions);
  add("Orari", service.schedule);
  add("Materiali accettati", typeof service.accepted_waste === "string" ? service.accepted_waste : null);
  if (service.acceptance) add("Accettazione", acceptanceLabel(service.acceptance.status));
  for (const period of service.opening_periods || []) {
    const intervals = (period.weekly_intervals || []).map((item) => `${["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"][item.weekday - 1] || item.weekday} ${item.opens}–${item.closes}`).join(", ");
    add(period.period_label || "Orari", intervals || period.exceptions);
  }
  if (Array.isArray(service.accepted_waste) && service.accepted_waste.length && !service.acceptance_status) {
    rows.push(`<div class="detail-row"><span>Materiali accettati</span>${service.accepted_waste.map((item) => escapeHtml(item)).join(" · ")}</div>`);
  }
  if (Array.isArray(service.accepted_waste) && service.acceptance_status === "published") {
    rows.push(`<div class="detail-row"><span>Materiali ed EER pubblicati</span><div class="acceptance-list">${service.accepted_waste.map((item) => {
      const label = item.official_label || item.label || item.eer_code || "Materiale non specificato";
      const metadata = [item.eer_code ? `EER ${item.eer_code}` : null, item.hazardous ? "Pericoloso" : null, item.quantity_limit, item.notes].filter(Boolean).join(" · ");
      const sourceLabel = item.official_label && item.label && item.official_label.toLocaleLowerCase("it") !== item.label.toLocaleLowerCase("it")
        ? `Descrizione del centro: ${item.label}` : null;
      return `<div class="acceptance-item"><strong>${escapeHtml(label)}</strong>${metadata ? `<span>${escapeHtml(metadata)}</span>` : ""}${sourceLabel ? `<span>${escapeHtml(sourceLabel)}</span>` : ""}</div>`;
    }).join("")}</div></div>`);
  }
  if (service.acceptance_status === "not_published") add("Materiali accettati", "Elenco non pubblicato");
  const urls = [...new Set([...(service.information_urls || []), ...(service.source_urls || [])])];
  if (urls.length) rows.push(`<div class="detail-row"><span>Informazioni ufficiali</span>${urls.map((url) => sourceLink(url, "Apri la fonte")).filter(Boolean).join(" · ")}</div>`);
  return rows.join("") || "<p>Nessun altro dettaglio pubblicato.</p>";
}

function openTerritoryDetail(kind, index) {
  const data = elements.centresView._data;
  if (!data) return;
  const collections = {
    facility: data.facilities,
    point: data.collection_points,
    pickup: data.pickup_services,
  };
  const service = collections[kind]?.[index];
  if (!service) return;
  elements.detailTitle.textContent = service.name || (kind === "pickup" ? "Ritiro a domicilio" : "Dettagli del servizio");
  elements.detailContent.innerHTML = detailRows(service);
  elements.detailDialog.showModal();
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
    if (isZone) {
      rememberZone(choice.dataset.choice, choice.dataset.choiceLabel);
      resolveWaste(state.query, null, choice.dataset.choice);
    } else {
      resolveWaste(state.query, choice.dataset.choice);
    }
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
elements.clearZone.addEventListener("click", clearRememberedZone);
elements.detectPlace.addEventListener("click", locateMunicipality);
elements.clearPosition.addEventListener("click", clearLocation);
for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => setView(button.dataset.view));
}
elements.rulesZone.addEventListener("change", () => {
  const zone = state.territory?.zones.find((item) => item.id === elements.rulesZone.value);
  if (zone) {
    rememberZone(zone.id, zone.name);
    state.territory = null;
    loadTerritory();
  } else {
    clearRememberedZone();
  }
});
elements.rulesStream.addEventListener("change", () => {
  if (state.territory) renderRuleRows(state.territory);
});
elements.rulesPreparation.addEventListener("change", () => {
  if (state.territory) renderRuleRows(state.territory);
});
for (const button of document.querySelectorAll("[data-service-view]")) {
  button.addEventListener("click", () => {
    state.serviceView = button.dataset.serviceView;
    for (const candidate of document.querySelectorAll("[data-service-view]")) {
      candidate.setAttribute("aria-selected", String(candidate === button));
    }
    renderServiceDirectory();
  });
}
elements.centresContent.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-territory-kind]");
  if (button) openTerritoryDetail(
    button.dataset.territoryKind, Number(button.dataset.territoryIndex),
  );
});
elements.closeExternal.addEventListener("click", closeExternalDialog);
elements.externalDialog.addEventListener("close", () => elements.externalContent.replaceChildren());
elements.externalDialog.addEventListener("click", (event) => {
  if (event.target === elements.externalDialog) closeExternalDialog();
});
elements.placeList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-istat]");
  if (button) chooseMunicipality(
    state.municipalities.find((item) => item.istat_code === button.dataset.istat),
    {preserveLocation: button.dataset.locationChoice === "true"},
  );
});
for (const button of document.querySelectorAll("#change-place, #choose-place, [data-change-place]")) button.addEventListener("click", openPlaceDialog);
for (const button of document.querySelectorAll("[data-query]")) button.addEventListener("click", () => {
  if (!state.municipality) return openPlaceDialog();
  elements.input.value = button.dataset.query;
  resolveWaste(button.dataset.query);
});
document.addEventListener("click", (event) => {
  const external = event.target.closest("a[data-external-url]");
  if (external) {
    event.preventDefault();
    openExternalDialog(
      external.dataset.externalUrl,
      external.dataset.externalTitle || external.textContent.trim(),
    );
    return;
  }
  if (!event.target.closest(".waste-form")) elements.suggestions.hidden = true;
});

async function initialize() {
  try {
    const body = await api("/api/municipalities");
    state.municipalities = body.municipalities;
    state.datasetRevision = body.dataset_revision;
    const remembered = localStorage.getItem("comesibutta.municipality");
    const municipality = state.municipalities.find((item) => item.istat_code === remembered);
    if (municipality) chooseMunicipality(municipality);
    const requestedView = new URLSearchParams(location.hash.slice(1)).get("view");
    setView(requestedView || "search", {updateHistory: false});
  } catch (error) {
    hideStates();
    elements.errorMessage.textContent = error.message;
    elements.error.hidden = false;
  }
}

initialize();
