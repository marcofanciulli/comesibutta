(() => {
  "use strict";

  const data = window.COMESIBUTTA_DATA;
  if (!data) {
    document.body.innerHTML = "<p>Dati dell'esploratore non disponibili.</p>";
    return;
  }

  const views = [
    ["overview", "Panoramica"],
    ["facilities", "Centri"],
    ["rules", "Regole"],
    ["points", "Punti"],
    ["pickup", "Ritiro"],
    ["records", "Record"],
  ];
  const typeLabels = {
    collection_point: "Punti di raccolta",
    collection_rule: "Regole di raccolta",
    collection_schedule: "Calendari",
    facility: "Centri di raccolta",
    facility_acceptance: "Voci EER accettate",
    facility_access: "Regole di accesso",
    opening_period: "Periodi di apertura",
    pickup_service: "Servizi di ritiro",
    service_zone: "Zone di servizio",
  };
  const weekdayLabels = ["", "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"];
  const methodLabels = { street: "Stradale", door_to_door: "Porta a porta", controlled_access: "Accesso controllato" };
  const presentationLabels = {
    loose: "Sfuso",
    paper_bag: "Sacco di carta",
    biodegradable_bag: "Sacco biodegradabile",
    non_compostable_bag: "Sacco non compostabile",
    container: "Nel contenitore",
    mixed: "Modalità multiple",
    unspecified: "Non specificato",
  };
  const defaultMunicipality = data.municipalities.find(item => item.slug === "grosseto") || data.municipalities[0];
  const state = { municipality: defaultMunicipality?.istat_code, view: "overview", query: "" };
  const elements = {
    municipalityList: document.querySelector("#municipality-list"),
    municipalitySearch: document.querySelector("#municipality-search"),
    batchStatus: document.querySelector("#batch-status"),
    pageTitle: document.querySelector("#page-title"),
    globalSearch: document.querySelector("#global-search"),
    searchCount: document.querySelector("#search-count"),
    tabs: document.querySelector("#view-tabs"),
    content: document.querySelector("#content"),
    dialog: document.querySelector("#record-dialog"),
    dialogTitle: document.querySelector("#dialog-title"),
    dialogContent: document.querySelector("#dialog-content"),
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
  }

  function municipality() {
    return data.municipalities.find(item => item.istat_code === state.municipality);
  }

  function records(type = null) {
    return data.records.filter(record => record.municipality_istat === state.municipality && (!type || record.record_type === type));
  }

  function matches(record, query = state.query) {
    return !query || JSON.stringify(record).toLocaleLowerCase("it").includes(query.toLocaleLowerCase("it"));
  }

  function filtered(type = null) {
    return records(type).filter(record => matches(record));
  }

  function countForView(view) {
    const mapping = {
      facilities: ["facility"],
      rules: ["collection_rule", "collection_schedule", "service_zone"],
      points: ["collection_point"],
      pickup: ["pickup_service"],
    };
    if (view === "records") return records().length;
    if (view === "overview") return null;
    return records().filter(record => mapping[view].includes(record.record_type)).length;
  }

  function renderMunicipalities(filter = "") {
    const needle = filter.toLocaleLowerCase("it");
    elements.municipalityList.innerHTML = data.municipalities
      .filter(item => item.name.toLocaleLowerCase("it").includes(needle))
      .map(item => `<button class="municipality-button ${item.istat_code === state.municipality ? "active" : ""}" data-municipality="${item.istat_code}" type="button"><span>${escapeHtml(item.name)}</span><small>${item.records} record · ${item.warnings.length} avvisi</small></button>`)
      .join("");
  }

  function renderTabs() {
    elements.tabs.innerHTML = views.map(([key, label]) => {
      const count = countForView(key);
      return `<button class="tab-button ${state.view === key ? "active" : ""}" data-view="${key}" type="button">${label}${count === null ? "" : `<span class="tab-count">${count}</span>`}</button>`;
    }).join("");
  }

  function sectionHeading(title, description) {
    return `<div class="section-heading"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div></div>`;
  }

  function warningNotice(warning) {
    const labels = {
      invalid_eer_code: "Codice EER da revisionare",
      acceptance_table_missing: "Tabella dei conferimenti non pubblicata",
    };
    return `<div class="notice"><strong>${escapeHtml(labels[warning.code] || warning.code)}</strong><span>${escapeHtml(warning.detail)}</span><br><a href="${escapeHtml(warning.url)}" target="_blank" rel="noreferrer">Apri la fonte</a></div>`;
  }

  function renderOverview() {
    const current = municipality();
    const facilityCount = records("facility").length;
    const eerCount = records("facility_acceptance").length;
    const ruleCount = records("collection_rule").length;
    const pointCount = records("collection_point").length;
    const coverage = Object.entries(current.records_by_type).sort((a, b) => (typeLabels[a[0]] || a[0]).localeCompare(typeLabels[b[0]] || b[0], "it"));
    return `${sectionHeading("Quadro del comune", "Copertura dell'acquisizione SEI Toscana e segnalazioni che richiedono controllo umano.")}
      <div class="metric-strip">
        <div class="metric"><strong>${facilityCount}</strong><span>centri o strutture</span></div>
        <div class="metric"><strong>${eerCount}</strong><span>righe EER accettate</span></div>
        <div class="metric"><strong>${ruleCount}</strong><span>regole territoriali</span></div>
        <div class="metric"><strong>${pointCount}</strong><span>punti speciali</span></div>
      </div>
      <div class="overview-grid">
        <div>
          <section class="subsection"><h3 class="subsection-title">Contenuti acquisiti</h3><div class="coverage-list">${coverage.map(([type, count]) => `<div class="coverage-row"><span>${escapeHtml(typeLabels[type] || type)}</span><strong>${count}</strong></div>`).join("")}</div></section>
          <section class="subsection"><h3 class="subsection-title">Pagine equivalenti</h3>${current.equivalent_pages.length ? current.equivalent_pages.map(item => `<div class="notice info"><strong>Contenuto estratto una sola volta</strong><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.url)}</a><br><span class="muted">equivale a ${escapeHtml(item.equivalent_to)}</span></div>`).join("") : `<div class="notice ok"><strong>Nessun duplicato semantico</strong>Le pagine disponibili hanno contenuti distinti.</div>`}</section>
        </div>
        <div>
          <section class="subsection"><h3 class="subsection-title">Qualità e provenienza</h3>
            <div class="coverage-row"><span>Pagine disponibili</span><strong>${current.pages_available}</strong></div>
            <div class="coverage-row"><span>Pagine materializzate</span><strong>${current.pages_materialized}</strong></div>
            <div class="coverage-row"><span>Record</span><strong>${current.records}</strong></div>
            <div class="coverage-row"><span>Avvisi</span><strong>${current.warnings.length}</strong></div>
          </section>
          <section class="subsection"><h3 class="subsection-title">Segnalazioni</h3>${current.warnings.length ? current.warnings.map(warningNotice).join("") : `<div class="notice ok"><strong>Nessuna segnalazione</strong>L'estrazione non ha rilevato anomalie note.</div>`}</section>
        </div>
      </div>`;
  }

  function openingHtml(periods) {
    if (!periods.length) return `<p class="muted">Orari non pubblicati nella pagina.</p>`;
    return periods.map(period => `<div><span class="chip">${escapeHtml(period.payload.period_label || "Periodo")}</span><ul class="opening-list">${period.payload.weekly_intervals.map(interval => `<li><strong>${weekdayLabels[interval.weekday]}</strong><span>${interval.opens}–${interval.closes}</span></li>`).join("")}</ul></div>`).join("");
  }

  function renderFacilities() {
    const facilities = records("facility").filter(facility => {
      if (!state.query) return true;
      return matches(facility) || records().some(record => record.payload.facility_ref === facility.natural_key && matches(record));
    });
    if (!facilities.length) return `${sectionHeading("Centri di raccolta", "Strutture, orari, accesso e rifiuti accettati secondo le pagine SEI Toscana.")}<div class="empty">Nessun centro corrisponde alla ricerca.</div>`;
    return `${sectionHeading("Centri di raccolta", "Strutture, orari, accesso e rifiuti accettati secondo le pagine SEI Toscana.")}${facilities.map(facility => {
      const ref = facility.natural_key;
      const periods = records("opening_period").filter(record => record.payload.facility_ref === ref);
      const access = records("facility_access").filter(record => record.payload.facility_ref === ref);
      const acceptances = records("facility_acceptance").filter(record => record.payload.facility_ref === ref && matches(record));
      const location = facility.payload.location;
      const mapUrl = location ? `https://www.openstreetmap.org/?mlat=${location.latitude}&mlon=${location.longitude}#map=17/${location.latitude}/${location.longitude}` : null;
      return `<article class="facility-block">
        <div class="facility-header"><div><h2>${escapeHtml(facility.payload.name)}</h2><p class="facility-address">${escapeHtml(facility.payload.address_raw || "Indirizzo non pubblicato")}</p><div class="facility-meta"><span>${facility.payload.phone ? `Telefono ${escapeHtml(facility.payload.phone)}` : "Telefono non pubblicato"}</span><span>${location ? `${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}` : "Coordinate non disponibili"}</span></div></div>${mapUrl ? `<a class="link-button" href="${mapUrl}" target="_blank" rel="noreferrer">Apri mappa</a>` : ""}</div>
        <div class="facility-columns"><div><h3>Orari</h3>${openingHtml(periods)}${access.map(item => `<details class="access-block"><summary>Accesso ${item.payload.user_type === "non_domestic" ? "utenze non domestiche" : "utenze domestiche"}</summary><p>${escapeHtml(item.payload.requirements_raw || "Consulta i documenti collegati alla fonte.")}</p>${item.payload.information_urls.map(url => `<p><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">Documento informativo</a></p>`).join("")}</details>`).join("")}</div>
        <div><h3>Rifiuti accettati <span class="muted">(${acceptances.length})</span></h3>${acceptances.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>EER</th><th>Descrizione della fonte</th><th>Stato</th><th></th></tr></thead><tbody>${acceptances.map(item => `<tr><td><span class="eer-code">${escapeHtml(item.payload.eer_code_raw)}</span></td><td>${escapeHtml(item.payload.description_raw)}${item.payload.operational_group ? `<span class="row-subtitle">${escapeHtml(item.payload.operational_group)}</span>` : ""}</td><td>${item.payload.hazardous ? `<span class="chip hazard">Pericoloso</span>` : ""}${item.payload.eer_code_status !== "exact" ? `<span class="chip review">Da revisionare</span>` : `<span class="chip">Esatto</span>`}</td><td><button class="detail-button" data-record="${item.record_id}" type="button">Dettagli</button></td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">Nessuna riga EER corrisponde alla ricerca o la tabella non è pubblicata.</p>`}</div></div>
      </article>`;
    }).join("")}`;
  }

  function scheduleText(rule, schedules) {
    const schedule = schedules.find(item => item.payload.collection_rule_ref === rule.natural_key);
    if (!schedule) return rule.payload.schedule_raw || "Non specificato";
    const events = schedule.payload.events.map(event => event.weekday ? weekdayLabels[event.weekday] : event.raw).filter(Boolean);
    return [events.join(", "), schedule.payload.expose_by ? `entro le ${schedule.payload.expose_by}` : ""].filter(Boolean).join(" · ");
  }

  function renderRules() {
    const rules = filtered("collection_rule");
    const zones = new Map(records("service_zone").map(record => [record.natural_key, record.payload.name]));
    const schedules = records("collection_schedule");
    return `${sectionHeading("Regole di raccolta", "Destinazione, contenitore, presentazione e calendario distinti per zona e utenza.")}${rules.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Frazione</th><th>Zona</th><th>Metodo</th><th>Contenitore</th><th>Come conferirla</th><th>Calendario</th><th></th></tr></thead><tbody>${rules.map(rule => `<tr><td><span class="row-title">${escapeHtml(rule.payload.stream_name)}</span><span class="row-subtitle">${escapeHtml(rule.payload.user_type)}</span></td><td>${escapeHtml(zones.get(rule.payload.zone_ref) || rule.payload.zone_ref)}</td><td><span class="chip method">${escapeHtml(methodLabels[rule.payload.collection_method] || rule.payload.collection_method)}</span></td><td>${escapeHtml([rule.payload.container_type, rule.payload.container_color].filter(Boolean).join(" · ") || "Non specificato")}</td><td>${escapeHtml(rule.payload.presentation.instructions_raw || presentationLabels[rule.payload.presentation.mode] || rule.payload.presentation.mode)}</td><td>${escapeHtml(scheduleText(rule, schedules))}</td><td><button class="detail-button" data-record="${rule.record_id}" type="button">Dettagli</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Nessuna regola corrisponde alla ricerca.</div>`}`;
  }

  function renderPoints() {
    const points = filtered("collection_point");
    return `${sectionHeading("Punti di raccolta", "Postazioni speciali, ecositi e aree temporanee descritte nelle pagine comunali.")}${points.length ? `<div class="point-grid">${points.map(point => `<article class="point-row"><h3>${escapeHtml(point.payload.name || point.payload.accepted_streams.join(", "))}</h3><p>${escapeHtml(point.payload.address_raw || "Ubicazione non specificata")}</p><div class="facility-meta">${point.payload.accepted_streams.map(stream => `<span class="chip">${escapeHtml(stream)}</span>`).join("")}${point.payload.opening_hours_raw ? `<span>${escapeHtml(point.payload.opening_hours_raw)}</span>` : ""}</div><p><button class="detail-button" data-record="${point.record_id}" type="button">Fonte e dettagli</button></p></article>`).join("")}</div>` : `<div class="empty">Nessun punto corrisponde alla ricerca.</div>`}`;
  }

  function renderPickup() {
    const services = filtered("pickup_service");
    return `${sectionHeading("Ritiro a domicilio", "Modalità di prenotazione, limiti e istruzioni pubblicate da SEI Toscana.")}${services.length ? services.map(service => `<div class="pickup-layout"><div><h3>${escapeHtml(service.payload.accepted_waste_raw)}</h3><div class="coverage-row"><span>Prenotazione</span><strong>${service.payload.booking_required ? "Obbligatoria" : "Non indicata"}</strong></div><div class="coverage-row"><span>Numero massimo</span><strong>${service.payload.max_items ?? "Non indicato"}</strong></div>${service.payload.booking_methods.map(method => `<div class="booking-method"><strong>${method.method === "web" ? "Prenotazione online" : "Prenotazione telefonica"}</strong><span>${escapeHtml(method.value)}</span>${method.method === "web" ? `<p><a class="link-button" href="${escapeHtml(method.value)}" target="_blank" rel="noreferrer">Apri prenotazione</a></p>` : ""}</div>`).join("")}</div><div><h3>Istruzioni</h3><p class="raw-text">${escapeHtml(service.payload.placement_instructions_raw)}</p><button class="detail-button" data-record="${service.record_id}" type="button">Fonte e record</button></div></div>`).join("") : `<div class="empty">Nessun servizio di ritiro corrisponde alla ricerca.</div>`}`;
  }

  function recordSummary(record) {
    const payload = record.payload;
    return payload.name || payload.stream_name || payload.description_raw || payload.accepted_waste_raw || payload.address_raw || record.natural_key;
  }

  function renderRecords() {
    const items = filtered();
    return `${sectionHeading("Tutti i record", "Vista tecnica completa dei fatti estratti e della loro provenienza.")}${items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Tipo</th><th>Contenuto</th><th>Affidabilità</th><th>Fonte</th><th></th></tr></thead><tbody>${items.map(record => `<tr><td><span class="chip">${escapeHtml(typeLabels[record.record_type] || record.record_type)}</span></td><td><span class="row-title">${escapeHtml(recordSummary(record))}</span><span class="row-subtitle">${escapeHtml(record.natural_key)}</span></td><td>${escapeHtml(record.confidence)}</td><td><a href="${escapeHtml(record.source.url)}" target="_blank" rel="noreferrer">SEI Toscana</a></td><td><button class="detail-button" data-record="${record.record_id}" type="button">Apri</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Nessun record corrisponde alla ricerca.</div>`}`;
  }

  function render() {
    const current = municipality();
    elements.pageTitle.textContent = current.name;
    renderMunicipalities(elements.municipalitySearch.value);
    renderTabs();
    const renderers = { overview: renderOverview, facilities: renderFacilities, rules: renderRules, points: renderPoints, pickup: renderPickup, records: renderRecords };
    elements.content.innerHTML = renderers[state.view]();
    const matching = filtered().length;
    elements.searchCount.textContent = state.query ? `${matching} record totali` : `${current.records} record`;
    history.replaceState(null, "", `#comune=${current.slug}&vista=${state.view}${state.query ? `&q=${encodeURIComponent(state.query)}` : ""}`);
  }

  function showRecord(recordId) {
    const record = data.records.find(item => item.record_id === recordId);
    if (!record) return;
    elements.dialogTitle.textContent = typeLabels[record.record_type] || record.record_type;
    elements.dialogContent.innerHTML = `<div class="coverage-row"><span>Affidabilità</span><strong>${escapeHtml(record.confidence)}</strong></div><div class="coverage-row"><span>Osservato il</span><strong>${escapeHtml(new Date(record.observed_at).toLocaleString("it-IT"))}</strong></div><div class="coverage-row"><span>Fonte</span><strong><a href="${escapeHtml(record.source.url)}" target="_blank" rel="noreferrer">Apri pagina SEI</a></strong></div><section class="subsection"><h3 class="subsection-title">Evidenza</h3><p class="evidence">${escapeHtml(record.source.evidence.quote || "Citazione non disponibile")}</p></section><section class="subsection"><h3 class="subsection-title">Dati originali</h3><pre class="json-view">${escapeHtml(JSON.stringify(record, null, 2))}</pre></section>`;
    elements.dialog.showModal();
  }

  elements.municipalityList.addEventListener("click", event => {
    const button = event.target.closest("[data-municipality]");
    if (!button) return;
    state.municipality = button.dataset.municipality;
    state.query = "";
    elements.globalSearch.value = "";
    render();
  });
  elements.tabs.addEventListener("click", event => {
    const button = event.target.closest("[data-view]");
    if (!button) return;
    state.view = button.dataset.view;
    render();
  });
  elements.content.addEventListener("click", event => {
    const button = event.target.closest("[data-record]");
    if (button) showRecord(button.dataset.record);
  });
  elements.municipalitySearch.addEventListener("input", event => renderMunicipalities(event.target.value));
  elements.globalSearch.addEventListener("input", event => {
    state.query = event.target.value.trim();
    render();
  });
  document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
  elements.dialog.addEventListener("click", event => {
    if (event.target === elements.dialog) elements.dialog.close();
  });

  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const initialMunicipality = data.municipalities.find(item => item.slug === params.get("comune"));
  if (initialMunicipality) state.municipality = initialMunicipality.istat_code;
  if (views.some(([key]) => key === params.get("vista"))) state.view = params.get("vista");
  state.query = params.get("q") || "";
  elements.globalSearch.value = state.query;
  elements.batchStatus.innerHTML = `<strong>${data.batch.records} record verificati</strong><br>${data.municipalities.length} comuni · ${data.batch.pages_checked} pagine<br>Aggiornati ${new Date(data.batch.observed_at).toLocaleDateString("it-IT")}`;
  render();
})();
