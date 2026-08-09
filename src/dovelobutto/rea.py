from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable
from urllib import robotparser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .ato_costa import MunicipalityContext, extract_rea_waste_lookup
from .html import Element, clean_text, parse_html
from .records import SourceDocument, make_record


REA_ROOT = "https://www.reaspa.it"
REA_CENTRES = f"{REA_ROOT}/centri-di-raccolta/"
REA_SHARED_PAGES = (
    f"{REA_ROOT}/ritiro-e-rifornimenti-kit/",
    f"{REA_ROOT}/ritiro-ingombranti/",
    f"{REA_ROOT}/ritiro-potature/",
    f"{REA_ROOT}/ritiro-raee/",
    f"{REA_ROOT}/attivazione-servizio-pannolini-e-pannoloni/",
)
_STREAMS = (
    ("organico", "Rifiuti organici"),
    ("carta e cartone", "Carta e cartone"),
    ("multimateriale", "Imballaggi in multimateriale"),
    ("vetro", "Vetro"),
    ("secco residuo", "Rifiuto residuo"),
    ("indifferenziato", "Rifiuto residuo"),
)
_MONTHS = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4,
    "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7, "AGOSTO": 8,
    "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
}
_RUR_CALENDAR_PATTERNS = (
    (re.compile(r"calendario-casale-2026(?:-1)?\.pdf$"), "domestic"),
    (re.compile(r"calendario-guardistallo-2026\.pdf$"), "domestic"),
    (re.compile(r"calendario_casale_und_tarip_rur\.pdf$"), "non_domestic"),
    (re.compile(r"calendario_guardistallo_und_tarip_rur\.pdf$"), "non_domestic"),
)
_ECOMOBILE_MATERIALS = (
    "Piccoli elettrodomestici",
    "Lampadine e tubi al neon",
    "Pile e batterie",
    "Toner e cartucce",
    "Farmaci scaduti",
    "Olio vegetale in contenitori",
)

# These icon tables were verified page by page against the exact acquired PDF.
# A changed PDF hash deliberately falls out of the allow-list and returns to review.
_WEEKLY_CALENDAR_CONFIGS: dict[str, dict[str, Any]] = {
    "8cec649b038b49f30d0d1d1f697caf143da4c8c10f5e28f07ee7c630d02a34a9": {
        "istat": "049001", "label": "Bibbona - Via delle Siepi Bruciate, Via delle Tane e Via del Paratino",
        "valid_from": "2023-06-05", "expose_from": None, "expose_by": "06:00",
        "zones": {"siepi": ("Via delle Siepi Bruciate, Via delle Tane e Via del Paratino", "Via delle Siepi Bruciate; Via delle Tane; Via del Paratino")},
        "rows": (
            ("siepi", "domestic", "Rifiuti organici", ((1, None, None), (5, None, None))),
            ("siepi", "domestic", "Carta e cartone", ((1, None, None),)),
            ("siepi", "domestic", "Imballaggi in multimateriale", ((4, None, None),)),
            ("siepi", "domestic", "Rifiuto residuo", ((2, None, None),)),
        ),
    },
    "5c7c7f2b755ae1938d65a4d2f531121b9934188ec5fa0711423b700fbc709c5f": {
        "istat": "049001", "label": "Bibbona - utenze non domestiche",
        "valid_from": "2025-07-07", "expose_from": None, "expose_by": "07:00", "zones": {},
        "rows": (
            ("default", "non_domestic", "Rifiuti organici", ((1, None, None), (2, None, None), (3, None, None), (4, None, None), (5, None, None), (6, None, None), (7, "06-15", "09-15"))),
            ("default", "non_domestic", "Carta e cartone", ((2, None, None), (4, None, None))),
            ("default", "non_domestic", "Imballaggi in multimateriale", ((1, None, None), (3, None, None))),
            ("default", "non_domestic", "Vetro", ((3, None, None),)),
            ("default", "non_domestic", "Rifiuto residuo", ((2, None, None), (5, None, None))),
        ),
    },
    "d120928d3c9e4fe0e4a09a5f47870e19ac94adaf11fec82a6ec2e1bbba4a7e2c": {
        "istat": "049001", "label": "Bibbona - centro storico",
        "valid_from": "2025-07-07", "expose_from": None, "expose_by": "07:00",
        "zones": {"centro-storico": ("Centro storico", "Centro storico di Bibbona")},
        "rows": (
            ("centro-storico", "domestic", "Rifiuti organici", ((2, None, None), (4, None, None), (6, None, None))),
            ("centro-storico", "domestic", "Carta e cartone", ((4, None, None),)),
            ("centro-storico", "domestic", "Imballaggi in multimateriale", ((1, None, None),)),
            ("centro-storico", "domestic", "Vetro", ((3, None, None),)),
            ("centro-storico", "domestic", "Rifiuto residuo", ((5, None, None),)),
        ),
    },
    "5f366145b33e0eace4aeaa61f11af80658c18d329a1639c3e4ec9212474ce52a": {
        "istat": "049008", "label": "Collesalvetti, Vicarello e Nugola - utenze domestiche",
        "valid_from": "2023-11-30", "expose_from": None, "expose_by": "06:00",
        "zones": {
            "collesalvetti-vicarello-nugola": ("Collesalvetti, Vicarello e Nugola", "Collesalvetti; Vicarello; Nugola"),
            "rurale": ("Zone rurali", "Zone rurali di Collesalvetti, Vicarello e Nugola"),
        },
        "rows": (
            ("collesalvetti-vicarello-nugola", "domestic", "Rifiuti organici", ((2, None, None), (4, "06-15", "09-15"), (6, None, None))),
            ("collesalvetti-vicarello-nugola", "domestic", "Carta e cartone", ((5, None, None),)),
            ("rurale", "all", "Carta e cartone", ((5, None, None),)),
            ("collesalvetti-vicarello-nugola", "domestic", "Imballaggi in multimateriale", ((3, None, None),)),
            ("rurale", "all", "Imballaggi in multimateriale", ((3, None, None),)),
            ("collesalvetti-vicarello-nugola", "domestic", "Vetro", ()),
            ("rurale", "all", "Vetro", ()),
            ("collesalvetti-vicarello-nugola", "domestic", "Rifiuto residuo", ((1, None, None),)),
            ("rurale", "all", "Rifiuto residuo", ((1, None, None),)),
            ("collesalvetti-vicarello-nugola", "domestic", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
            ("rurale", "all", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
        ),
    },
    "a00ba804064e90c274721360d5a7a5bfb49b032a131050401a3d2dc60ad9f7ec": {
        "istat": "049008", "label": "Collesalvetti, Vicarello e Nugola - utenze non domestiche",
        "valid_from": "2023-11-30", "expose_from": None, "expose_by": "06:00",
        "zones": {"collesalvetti-vicarello-nugola": ("Collesalvetti, Vicarello e Nugola", "Collesalvetti; Vicarello; Nugola")},
        "rows": (
            ("collesalvetti-vicarello-nugola", "non_domestic", "Rifiuti organici", ((2, None, None), (4, "06-15", "09-15"), (6, None, None))),
            ("collesalvetti-vicarello-nugola", "non_domestic", "Carta e cartone", ((5, None, None),)),
            ("collesalvetti-vicarello-nugola", "non_domestic", "Imballaggi in cartone", ((2, None, None), (4, None, None), (6, None, None))),
            ("collesalvetti-vicarello-nugola", "non_domestic", "Imballaggi in multimateriale", ((3, None, None), (6, "06-15", "09-15"))),
            ("collesalvetti-vicarello-nugola", "non_domestic", "Vetro", ((1, "06-15", "09-15"), (4, None, None))),
            ("collesalvetti-vicarello-nugola", "non_domestic", "Rifiuto residuo", ((1, None, None),)),
            ("collesalvetti-vicarello-nugola", "non_domestic", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
        ),
    },
    "b051c30be269f5f4efede5a2d3508d8906442fbccc07856a97410fc05bce4c94": {
        "istat": "049008", "label": "Stagno e Guasticce - utenze domestiche",
        "valid_from": "2023-11-30", "expose_from": None, "expose_by": "12:00",
        "zones": {"stagno-guasticce": ("Stagno e Guasticce", "Stagno; Guasticce"), "rurale-stagno": ("Zone rurali di Stagno e Guasticce", "Zone rurali di Stagno e Guasticce")},
        "rows": (
            ("stagno-guasticce", "domestic", "Rifiuti organici", ((2, None, None), (4, "06-15", "09-15"), (6, None, None))),
            ("stagno-guasticce", "domestic", "Carta e cartone", ((5, None, None),)),
            ("rurale-stagno", "all", "Carta e cartone", ((5, None, None),)),
            ("stagno-guasticce", "domestic", "Imballaggi in multimateriale", ((3, None, None),)),
            ("rurale-stagno", "all", "Imballaggi in multimateriale", ((3, None, None),)),
            ("stagno-guasticce", "domestic", "Vetro", ()), ("rurale-stagno", "all", "Vetro", ()),
            ("stagno-guasticce", "domestic", "Rifiuto residuo", ((1, None, None),)),
            ("rurale-stagno", "all", "Rifiuto residuo", ((1, None, None),)),
            ("stagno-guasticce", "domestic", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
            ("rurale-stagno", "all", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
        ),
    },
    "abb988b24a1889865f4c8b22f8ba570030a645dbbf4d523486e290f6a502cd6b": {
        "istat": "050010", "label": "Castellina Marittima", "valid_from": "2023-05-03",
        "expose_from": None, "expose_by": "12:00", "zones": {},
        "rows": (
            ("default", "all", "Rifiuti organici", ((3, None, None), (6, None, None))),
            ("default", "non_domestic", "Rifiuti organici", ((1, "06-15", "09-15"),)),
            ("default", "all", "Carta e cartone", ((5, None, None),)),
            ("default", "all", "Imballaggi in multimateriale", ((2, None, None),)),
            ("default", "all", "Vetro", ((1, None, None),)),
            ("default", "all", "Rifiuto residuo", ((4, None, None),)),
            ("default", "domestic", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
            ("default", "non_domestic", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
        ),
    },
    "ea0f3969fa19354241d683ba5b8c0e064fdbdf70775276431133dd42699fb9f8": {
        "istat": "050019", "label": "Montecatini Val di Cecina", "valid_from": "2026-02-18",
        "expose_from": None, "expose_by": "06:00", "zones": {},
        "rows": (
            ("default", "all", "Rifiuti organici", ((1, None, None), (5, None, None))),
            ("default", "all", "Carta e cartone", ((6, None, None),)),
            ("default", "all", "Imballaggi in multimateriale", ((2, None, None),)),
            ("default", "all", "Vetro", ((3, None, None),)),
            ("default", "all", "Rifiuto residuo", ((4, None, None),)),
            ("default", "all", "Pannolini e pannoloni", ((1, None, None), (4, None, None))),
        ),
    },
    "13e7fb6afbe2048350d8d0b3562ec1f7803adc2589e056fc70b85549ac4d51bb": {
        "istat": "050020", "label": "Montescudaio", "valid_from": "2025-09-25",
        "expose_from": None, "expose_by": "06:00",
        "zones": {"non-rurale": ("Zone non rurali", "Territorio escluso dalle zone rurali")},
        "rows": (
            ("non-rurale", "all", "Rifiuti organici", ((2, None, None), (4, "06-15", "09-15"), (6, "06-15", "09-15"))),
            ("non-rurale", "all", "Carta e cartone", ((6, None, None),)),
            ("default", "all", "Imballaggi in multimateriale", ((1, None, None),)),
            ("default", "all", "Vetro", ((4, None, None),)),
            ("default", "all", "Rifiuto residuo", ((5, None, None),)),
        ),
    },
    "57239e2644f27397ce9644d4630f19792a814ba893f5fb9bb2d5342f239a9a39": {
        "istat": "050030", "label": "Riparbella", "valid_from": "2022-01-11",
        "expose_from": None, "expose_by": "06:00",
        "zones": {"non-rurale": ("Zone non rurali", "Territorio escluso dalle zone rurali")},
        "rows": (
            ("non-rurale", "all", "Rifiuti organici", ((1, None, None), (4, "06-01", "09-30"), (6, "06-01", "09-30"))),
            ("default", "all", "Carta e cartone", ((6, None, None),)),
            ("default", "all", "Imballaggi in multimateriale", ((3, None, None),)),
            ("default", "all", "Vetro", ((5, None, None),)),
            ("default", "all", "Rifiuto residuo", ((2, None, None),)),
        ),
    },
    "a6c3f2f2a5d053b925301958ce81ff34a6129ebee250a4934b15b4760be8edad": {
        "istat": "050034", "label": "Santa Luce", "valid_from": "2022-01-11",
        "expose_from": "20:00", "expose_by": "06:00", "zones": {},
        "rows": (
            ("default", "all", "Rifiuti organici", ((2, None, None), (5, None, None))),
            ("default", "all", "Carta e cartone", ((6, None, None),)),
            ("default", "all", "Imballaggi in multimateriale", ((1, None, None),)),
            ("default", "all", "Vetro", ((3, None, None),)),
            ("default", "all", "Rifiuto residuo", ((4, None, None),)),
        ),
    },
    "12be8640daa16da86ea4564504f7aafa783e800408b7aa779955328b644d15a9": {
        "istat": "050039", "label": "Volterra - utenze domestiche", "valid_from": "2025-07-09",
        "zones": {
            "centro-storico": ("Centro storico entro la cinta muraria", "Centro storico entro la cinta muraria"),
            "extra-centro": ("Extra centro storico", "Volterra area urbana; Saline; Villamagna"),
        },
        "zone_exposure": {"centro-storico": ("06:00", "08:00"), "extra-centro": ("23:00", "06:00")},
        "rows": tuple(
            (zone, "domestic", stream, events)
            for zone in ("centro-storico", "extra-centro")
            for stream, events in (
                ("Rifiuti organici", ((1, None, None), (3, None, None), (6, None, None))),
                ("Carta e cartone", ((2, None, None),)),
                ("Imballaggi in multimateriale", ((1, None, None), (4, None, None))),
                ("Vetro", ((4, None, None),)), ("Rifiuto residuo", ((5, None, None),)),
                ("Pannolini e pannoloni", ((1, None, None), (3, None, None), (5, None, None))),
            )
        ),
    },
}
_ECOMOBILE_CONFIGS = (
    {
        "pattern": re.compile(r"ecomobile-rosignano-frazioni-collinari_2026\.pdf\.pdf$"),
        "weekday": 4, "strict_year": True,
        "stops": (
            ("Castelnuovo della Misericordia", r"CASTELNUOVO M\.DIA", "Piazza Gramsci", "13:00-14:00", 12),
            ("Gabbro", r"GABBRO", "Piazza della Chiesa", "14:30-15:30", 12),
            ("Nibbiaia", r"NIBBIAIA", "Piazza Mazzini", "16:00-17:00", 12),
        ),
    },
    {
        "pattern": re.compile(r"ecomobile-orciano-pisano2026\.pdf\.pdf$"),
        "weekday": 4, "strict_year": True,
        "stops": (
            ("Orciano Pisano", r"ORCIANO PISANO", "Piazza dei Bersaglieri", "13:00-15:30", 20),
        ),
    },
    {
        "pattern": re.compile(r"ecomobile-santa-luce-2026pdf\.pdf$"),
        "weekday": 4, "strict_year": True,
        "stops": (
            ("Santa Luce", r"[•·]\s*SANTA LUCE(?:\s|$)", "Area pedonale presso il Palazzo Civico", "16:00-17:30", 18),
            ("Pieve di Santa Luce", r"PIEVE DI SANTA LUCE", "Via Europa angolo Via delle Colline", "13:00-14:00", 18),
            ("Pastina", r"PASTINA", "Parcheggio di Via Querciagrossa", "14:30-15:45", 18),
            ("Pomaia", r"POMAIA", "Piazza Giovanni Paolo II", "16:15-17:30", 18),
        ),
    },
    {
        "pattern": re.compile(r"calendario-ecomobile-2025_2026\.pdf$"),
        "weekday": 3, "strict_year": False,
        "stops": (
            ("Montecatini Val di Cecina", r"MONTECATINI VC", "Piazza Schneider (Piazza del mercato)", "13:45-15:00", 13),
            ("Ponteginori", r"PONTEGINORI", "Piazza S. Pertini, vicino alla farmacia comunale", "15:30-16:45", 13),
            ("Querceto", r"QUERCETO", "Piazza San Giovanni Battista", "13:45-15:00", 13),
            ("La Sassa", r"LA SASSA", "Piazza 2 Giugno", "15:30-16:45", 13),
        ),
    },
    {
        "pattern": re.compile(r"castelnuovo-val-di-cecina_ecomobile\.pdf$"),
        "weekday": 3, "strict_year": False,
        "stops": (
            ("Sasso Pisano", r"SASSO PISANO", "Piazza Martiri Strage di Bologna", "14:00-15:00", 13),
            ("Montecastelli Pisano", r"MONTECASTELLI PISANO", "Piazza del Muro Nuovo", "14:00-15:00", 13),
            ("Castelnuovo Val di Cecina", r"CASTELNUOVO VC", "Parcheggio sotto Piazza Matteotti", "15:30-16:30", 26),
        ),
    },
)
_CENTRE_ACCESS = {
    "casale-marittimo": {"guardistallo", "montescudaio"},
    "castellina-marittima": {"rosignano-solvay"},
    "castelnuovo-di-val-di-cecina": {"pomarance"},
    "guardistallo": {"guardistallo", "montescudaio"},
    "montecatini-val-di-cecina": {"guardistallo", "montescudaio"},
    "montescudaio": {"guardistallo", "montescudaio"},
    "collesalvetti": {"collesalvetti", "stagno"},
}
_CENTRE_OWNER = {
    "rosignano-solvay": "rosignano-marittimo",
    "stagno": "collesalvetti",
}


def _slug(value: str) -> str:
    value = value.casefold().translate(str.maketrans("àèéìòù", "aeeiou"))
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "unknown"


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    path = re.sub(r"/{2,}", "/", parsed.path)
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", query, ""))


def _links(html: str, base_url: str) -> list[tuple[str, str]]:
    root = parse_html(html)
    result = []
    for link in root.find_all(lambda item: item.tag == "a" and bool(item.attrs.get("href"))):
        url = _canonical_url(urljoin(base_url, link.attrs["href"]))
        if urlparse(url).netloc == "www.reaspa.it":
            result.append((url, clean_text(link.text)))
    return result


def crawl_rea_services(
    municipalities: list[dict[str, Any]],
    snapshot_root: Path,
    observed_at: datetime,
    user_agent: str,
    delay: float = 1.0,
    previous_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crawl public GET pages linked by REA's municipality and centre indexes."""
    robots_url = f"{REA_ROOT}/robots.txt"
    with urlopen(Request(robots_url, headers={"User-Agent": user_agent}), timeout=30) as response:
        robots_lines = response.read().decode("utf-8", errors="replace").splitlines()
    robots = robotparser.RobotFileParser(robots_url)
    robots.parse(robots_lines)
    effective_delay = max(delay, robots.crawl_delay(user_agent) or robots.crawl_delay("*") or 1.0)

    queue: deque[dict[str, Any]] = deque()
    for municipality in municipalities:
        queue.append({"url": municipality["homepage_url"], "category": "municipality", "municipality_istats": [municipality["istat_code"]]})
    queue.append({"url": REA_CENTRES, "category": "centre_index", "municipality_istats": []})
    for url in REA_SHARED_PAGES:
        queue.append({"url": url, "category": "shared_service", "municipality_istats": []})

    valid_homepages = {_canonical_url(item["homepage_url"]) for item in municipalities}
    completed: dict[str, dict[str, Any]] = {
        page["url"]: page
        for page in (previous_manifest or {}).get("pages", [])
        if page["status"] == "snapshot"
        or page["category"] != "municipality"
        or page["url"] in valid_homepages
    }
    queued: dict[str, dict[str, Any]] = {}

    def enqueue(job: dict[str, Any]) -> None:
        url = _canonical_url(job["url"])
        job = {**job, "url": url}
        if url in completed:
            completed[url]["municipality_istats"] = sorted(set(completed[url]["municipality_istats"] + job["municipality_istats"]))
        elif url in queued:
            queued[url]["municipality_istats"] = sorted(set(queued[url]["municipality_istats"] + job["municipality_istats"]))
        else:
            queued[url] = job
            queue.append(job)

    initial = list(queue)
    queue.clear()
    for job in initial:
        enqueue(job)

    while queue:
        queued_job = queue.popleft()
        url = queued_job["url"]
        job = queued.pop(url)
        if not robots.can_fetch(user_agent, url):
            completed[url] = {**job, "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None}
            continue
        try:
            request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/pdf"})
            with urlopen(request, timeout=45) as response:
                body = response.read()
                final_url = _canonical_url(response.geturl())
                content_type = response.headers.get_content_type()
            digest = hashlib.sha256(body).hexdigest()
            extension = ".pdf" if content_type == "application/pdf" or final_url.lower().endswith(".pdf") else ".html"
            snapshot = snapshot_root / f"{digest}{extension}"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not snapshot.exists():
                snapshot.write_bytes(body)
            entry = {**job, "status": "snapshot", "final_url": final_url, "content_type": content_type, "snapshot": snapshot.name, "sha256": digest}
            completed[url] = entry
            if extension == ".html":
                html = body.decode("utf-8", errors="replace")
                for discovered, label in _links(html, final_url):
                    path = urlparse(discovered).path
                    category = None
                    istats = entry["municipality_istats"]
                    if entry["category"] in {"municipality", "municipality_service"}:
                        if path.lower().endswith(".pdf"):
                            category = "municipality_document"
                        elif entry["category"] == "municipality" and path.startswith(urlparse(final_url).path.rstrip("/") + "/"):
                            category = "municipality_service"
                        elif path.startswith("/servizi/") and "comune=" in urlparse(discovered).query:
                            category = "municipality_service"
                    elif entry["category"] == "centre_index":
                        if re.fullmatch(r"/centri-di-raccolta/page/\d+/", path):
                            category = "centre_index"
                        elif path.startswith("/centri-di-raccolta/") and path != "/centri-di-raccolta/":
                            category = "centre_detail"
                    if category:
                        enqueue({"url": discovered, "category": category, "municipality_istats": istats, "link_text": label})
            time.sleep(effective_delay)
        except Exception as error:
            completed[url] = {**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"{type(error).__name__}: {error}"}
            time.sleep(effective_delay)

    pages = sorted(completed.values(), key=lambda item: (item["category"], item["url"]))
    categories = sorted({page["category"] for page in pages})
    return {
        "observed_at": observed_at.isoformat(), "publisher": "REA S.p.A.",
        "robots_url": robots_url, "crawl_delay_seconds": effective_delay, "pages": pages,
        "summary": {
            "checked": len(pages), "snapshots": sum(page["status"] == "snapshot" for page in pages),
            "blocked_by_robots": sum(page["status"] == "blocked_by_robots" for page in pages),
            "errors": sum(page["status"] == "error" for page in pages),
            "by_category": {category: sum(page["category"] == category for page in pages) for category in categories},
        },
    }


def _source(url: str, retrieved_at: datetime, html: str, parser: str) -> SourceDocument:
    return SourceDocument(
        url, retrieved_at, html, publisher="REA S.p.A.", parser=parser,
        parser_version="0.4.0",
    )


def _pdf_bbox_words(path: Path) -> tuple[list[dict[str, Any]], str]:
    result = subprocess.run(
        ["pdftotext", "-bbox-layout", str(path), "-"],
        check=True, capture_output=True,
    )
    bbox = result.stdout.decode("utf-8", errors="replace")
    root = ET.fromstring(bbox)
    pages = []
    for page_number, page in enumerate(root.findall(".//{*}page"), 1):
        words = []
        for word in page.findall(".//{*}word"):
            words.append({
                "text": "".join(word.itertext()).strip(),
                "x0": float(word.attrib["xMin"]),
                "x1": float(word.attrib["xMax"]),
                "top": float(word.attrib["yMin"]),
                "bottom": float(word.attrib["yMax"]),
            })
        pages.append({
            "number": page_number,
            "width": float(page.attrib.get("width", 0)),
            "height": float(page.attrib.get("height", 0)),
            "words": words,
        })
    return pages, bbox


def _cluster_month_rows(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(
        (item for item in words if item["text"].upper() in _MONTHS),
        key=lambda item: (item["top"], item["x0"]),
    ):
        row = next((candidate for candidate in rows if abs(candidate[0]["top"] - word["top"]) <= 3), None)
        if row is None:
            rows.append([word])
        else:
            row.append(word)
    return [
        sorted(row, key=lambda item: item["x0"])
        for row in rows if len({item["text"].upper() for item in row}) >= 6
    ]


def _reconcile_calendar_day(
    year: int, month: int, raw_day: str, allowed_weekdays: set[int],
) -> tuple[int | None, str | None]:
    day = int(raw_day)
    try:
        if date(year, month, day).isoweekday() in allowed_weekdays:
            return day, None
    except ValueError:
        pass
    if len(raw_day) == 2 and raw_day[1] != "0":
        candidate = int(raw_day[1])
        try:
            if date(year, month, candidate).isoweekday() in allowed_weekdays:
                return candidate, f"{raw_day}->{candidate}"
        except ValueError:
            pass
    return None, raw_day


def _extract_calendar_dates(
    pages: list[dict[str, Any]], year: int, weekday: int, user_type: str,
) -> tuple[list[str], list[str], list[str]]:
    dates = []
    reconciled = []
    rejected = []
    for page in pages:
        rows = _cluster_month_rows(page["words"])
        for row in rows:
            if [item["text"].upper() for item in row] not in (
                list(_MONTHS)[:6], list(_MONTHS)[6:],
            ):
                continue
            centers = [(item["x0"] + item["x1"]) / 2 for item in row]
            boundaries = [float("-inf"), *[
                (left + right) / 2 for left, right in zip(centers, centers[1:])
            ], float("inf")]
            lower = max(item["bottom"] for item in row)
            later_rows = [
                candidate for candidate in rows
                if candidate[0]["top"] > row[0]["top"] + 3
            ]
            upper = min((candidate[0]["top"] for candidate in later_rows), default=lower + 40)
            for word in page["words"]:
                raw_day = word["text"]
                if not raw_day.isdigit() or not lower < word["top"] < upper:
                    continue
                center = (word["x0"] + word["x1"]) / 2
                column = next((index for index in range(6) if boundaries[index] <= center < boundaries[index + 1]), None)
                if column is None:
                    continue
                month = _MONTHS[row[column]["text"].upper()]
                allowed = {weekday}
                if user_type == "non_domestic" and month in {7, 8}:
                    allowed.add(7)
                day, correction = _reconcile_calendar_day(year, month, raw_day, allowed)
                if day is None:
                    rejected.append(f"{month:02d}:{raw_day}")
                    continue
                value = date(year, month, day).isoformat()
                if value not in dates:
                    dates.append(value)
                if correction:
                    reconciled.append(f"{month:02d}:{correction}")
    return sorted(dates), reconciled, rejected


def extract_rea_rur_calendar(
    context: MunicipalityContext, retrieved_at: datetime, url: str,
    pdf_path: Path, user_type: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    pages, bbox = _pdf_bbox_words(pdf_path)
    text = " ".join(
        word["text"] for page in pages for word in page["words"]
    )
    year_match = re.search(r"GENNAIO\s+(20\d{2})", text, re.IGNORECASE)
    weekday_match = re.search(
        r"(LUNED[IÌ]|MARTED[IÌ]|MERCOLED[IÌ]|GIOVED[IÌ]|VENERD[IÌ]|SABATO|DOMENICA)\s+ALTERNI"
        r"|QUINDICINALE\)?,?\s+IL\s+(LUNED[IÌ]|MARTED[IÌ]|MERCOLED[IÌ]|GIOVED[IÌ]|VENERD[IÌ]|SABATO|DOMENICA)",
        text, re.IGNORECASE,
    )
    if not year_match or not weekday_match:
        return [], [{"code": "calendar_pdf_structure_unrecognized", "detail": "Anno o giorno alterno non riconosciuto nel calendario RUR", "url": url}]
    weekday_key = _slug(weekday_match.group(1) or weekday_match.group(2))
    weekdays = {
        "lunedi": 1, "martedi": 2, "mercoledi": 3, "giovedi": 4,
        "venerdi": 5, "sabato": 6, "domenica": 7,
    }
    year = int(year_match.group(1))
    weekday = weekdays[weekday_key]
    dates, reconciled, rejected = _extract_calendar_dates(
        pages, year, weekday, user_type,
    )
    if user_type == "domestic" and dates:
        first = date.fromisoformat(dates[0])
        expected = []
        current = first
        while current.year == year:
            expected.append(current.isoformat())
            current += timedelta(days=14)
        dates = [value for value in expected if value in dates]
    minimum = 24 if user_type == "domestic" else 45
    if len(dates) < minimum:
        return [], [{
            "code": "calendar_pdf_dates_incomplete",
            "detail": f"Estratte soltanto {len(dates)} date RUR; calendario non materializzato",
            "url": url,
        }]
    source = SourceDocument(
        url, retrieved_at, bbox, publisher="REA S.p.A.",
        parser="rea_rur_calendar_pdf_bbox", parser_version="0.1.0",
    )
    rule_ref = (
        f"collection-rule:{context.istat_code}:default:door_to_door:"
        f"{user_type}:rifiuto-residuo"
    )
    validity = {
        "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "inferred": False,
    }
    records = []
    if user_type == "non_domestic":
        exposure_instructions = (
            "Esposizione entro le ore 06:00."
            if "entro le 6:00" in text.casefold() else None
        )
        records.append(make_record(
            record_type="collection_rule", natural_key=rule_ref,
            payload={
                "municipality_ref": context.municipality_ref,
                "zone_ref": f"service-zone:{context.istat_code}:default",
                "user_type": user_type, "collection_method": "door_to_door",
                "stream_name": "Rifiuto residuo", "included_materials_raw": None,
                "container_type": None, "container_color": None,
                "access_credential": None,
                "presentation": {
                    "mode": "unspecified", "max_volume_l": None,
                    "instructions_raw": exposure_instructions,
                },
                "schedule_raw": f"Date RUR {year} pubblicate nel calendario REA",
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-grid",
            evidence_quote=f"Calendario RUR {year}: {len(dates)} date",
            validity=validity,
        ))
    records.append(make_record(
        record_type="collection_schedule",
        natural_key=f"{rule_ref}:schedule:{year}",
        payload={
            "collection_rule_ref": rule_ref,
            "expose_from": None,
            "expose_by": "06:00" if "entro le 6:00" in text.casefold() else None,
            "events": [{
                "kind": "date_list", "weekday": None, "dates": dates,
                "raw": f"Calendario RUR REA {year}; giorno ordinario {weekday}",
            }],
        },
        source=source, evidence_kind="pdf", evidence_selector="calendar-grid",
        evidence_quote=f"Calendario RUR {year}: " + ", ".join(dates),
        validity=validity,
    ))
    warnings = []
    if reconciled:
        warnings.append({
            "code": "calendar_pdf_text_layer_reconciled",
            "detail": "Date riconciliate col giorno settimanale dichiarato: " + ", ".join(reconciled),
            "url": url,
        })
    if rejected:
        warnings.append({
            "code": "calendar_pdf_dates_rejected",
            "detail": "Valori del livello testuale incompatibili col calendario: " + ", ".join(rejected),
            "url": url,
        })
    return records, warnings


def _rur_calendar_type(page: dict[str, Any]) -> str | None:
    filename = urlparse(page.get("final_url") or page["url"]).path.rsplit("/", 1)[-1].casefold()
    for pattern, user_type in _RUR_CALENDAR_PATTERNS:
        if pattern.fullmatch(filename):
            return user_type
    return None


def _ecomobile_config(page: dict[str, Any]) -> dict[str, Any] | None:
    filename = urlparse(page.get("final_url") or page["url"]).path.rsplit("/", 1)[-1].casefold()
    return next((config for config in _ECOMOBILE_CONFIGS if config["pattern"].fullmatch(filename)), None)


def _column_lines(page: dict[str, Any]) -> list[list[str]]:
    midpoint = page.get("width") or max((word["x1"] for word in page["words"]), default=0)
    midpoint /= 2
    columns: list[list[dict[str, Any]]] = [[], []]
    for word in page["words"]:
        center = (word["x0"] + word["x1"]) / 2
        columns[0 if center < midpoint else 1].append(word)
    result = []
    for words in columns:
        rows: list[list[dict[str, Any]]] = []
        for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
            row = next((candidate for candidate in rows if abs(candidate[0]["top"] - word["top"]) <= 2.5), None)
            if row is None:
                rows.append([word])
            else:
                row.append(word)
        result.append([
            clean_text(" ".join(item["text"] for item in sorted(row, key=lambda item: item["x0"])))
            for row in rows
        ])
    return result


def _ecomobile_date_blocks(pages: list[dict[str, Any]]) -> list[tuple[date, str]]:
    month_pattern = "|".join(_MONTHS)
    date_pattern = re.compile(rf"\b(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})\b", re.IGNORECASE)
    blocks: list[tuple[date, str]] = []
    for page in pages:
        for lines in _column_lines(page):
            current_date = None
            current_lines: list[str] = []
            for line in lines:
                match = date_pattern.search(line)
                if match:
                    if current_date is not None:
                        blocks.append((current_date, " ".join(current_lines)))
                    try:
                        current_date = date(
                            int(match.group(3)), _MONTHS[match.group(2).upper()], int(match.group(1)),
                        )
                    except ValueError:
                        current_date = None
                    current_lines = [line]
                elif current_date is not None:
                    current_lines.append(line)
            if current_date is not None:
                blocks.append((current_date, " ".join(current_lines)))
    return blocks


def extract_rea_ecomobile_calendar(
    context: MunicipalityContext, retrieved_at: datetime, url: str,
    pdf_path: Path, config: dict[str, Any], year: int = 2026,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    pages, bbox = _pdf_bbox_words(pdf_path)
    blocks = _ecomobile_date_blocks(pages)
    warnings: list[dict[str, str]] = []
    outside = sorted({value.isoformat() for value, _ in blocks if value.year != year})
    if config["strict_year"] and outside:
        warnings.append({
            "code": "ecomobile_date_outside_calendar_year",
            "detail": f"Date fuori dal 2026 conservate come anomalia della fonte: {', '.join(outside)}",
            "url": url,
        })
    invalid_weekdays = sorted({
        value.isoformat() for value, _ in blocks
        if value.year == year and value.isoweekday() != config["weekday"]
    })
    if invalid_weekdays:
        warnings.append({
            "code": "ecomobile_weekday_mismatch",
            "detail": "Date incompatibili col giorno settimanale dichiarato: " + ", ".join(invalid_weekdays),
            "url": url,
        })
    source = SourceDocument(
        url, retrieved_at, bbox, publisher="REA S.p.A.",
        parser="rea_ecomobile_pdf_bbox", parser_version="0.1.0",
    )
    validity = {
        "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "inferred": False,
    }
    records = []
    for name, stop_pattern, address, hours, minimum in config["stops"]:
        dates = sorted({
            value.isoformat() for value, block in blocks
            if value.year == year
            and value.isoweekday() == config["weekday"]
            and re.search(stop_pattern, block, re.IGNORECASE)
        })
        if len(dates) < minimum:
            warnings.append({
                "code": "ecomobile_stop_dates_incomplete",
                "detail": f"{name}: estratte {len(dates)} date su almeno {minimum} attese; fermata non materializzata",
                "url": url,
            })
            continue
        point_ref = f"rea:ecomobile:{context.istat_code}:{_slug(name)}"
        records.append(make_record(
            record_type="collection_point", natural_key=point_ref,
            payload={
                "municipality_ref": context.municipality_ref,
                "zone_ref": f"service-zone:{context.istat_code}:default",
                "name": f"Ecomobile REA - {name}", "point_type": "mobile",
                "accepted_streams": list(_ECOMOBILE_MATERIALS),
                "address_raw": address, "location": None,
                "access_notes_raw": (
                    "Servizio rivolto alle utenze domestiche; tessera sanitaria necessaria. "
                    "Lampadine, tubi al neon, pile, batterie, toner e cartucce sono "
                    "ammessi anche per le utenze non domestiche."
                ),
                "access_credential": "health_card", "information_urls": [url],
                "opening_hours_raw": hours,
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-stop",
            evidence_quote=f"{name}, {address}, {hours}; {len(dates)} date nel {year}",
            validity=validity,
        ))
        records.append(make_record(
            record_type="collection_schedule", natural_key=f"{point_ref}:schedule:{year}",
            payload={
                "collection_point_ref": point_ref, "expose_from": None, "expose_by": None,
                "events": [{
                    "kind": "date_list", "weekday": config["weekday"], "dates": dates,
                    "raw": f"Calendario Ecomobile REA {year}: {len(dates)} date",
                }],
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-stop",
            evidence_quote=f"{name}: " + ", ".join(dates), validity=validity,
        ))
    return records, warnings


def _weekly_calendar_config(page: dict[str, Any]) -> dict[str, Any] | None:
    digest = Path(page.get("snapshot", "")).stem
    return _WEEKLY_CALENDAR_CONFIGS.get(digest)


def _weekly_presentation(stream: str, on_request: bool) -> tuple[str | None, dict[str, Any]]:
    if stream == "Rifiuti organici":
        return "mastello", {
            "mode": "compostable_bag", "max_volume_l": None,
            "instructions_raw": "Usare un sacchetto compostabile nel mastello; non usare sacchi neri.",
        }
    if stream in {"Carta e cartone", "Imballaggi in cartone"}:
        return "mastello o materiale piegato", {
            "mode": "loose", "max_volume_l": None,
            "instructions_raw": "Conferire sfuso, senza sacchi; piegare il cartone per ridurne il volume.",
        }
    if stream == "Imballaggi in multimateriale":
        return "sacco", {
            "mode": "plastic_bag", "max_volume_l": None,
            "instructions_raw": "Usare il sacco trasparente o semitrasparente previsto dal servizio; non usare sacchi neri.",
        }
    if stream == "Vetro":
        return "mastello o campana stradale", {
            "mode": "container", "max_volume_l": None,
            "instructions_raw": "Conferire sfuso nel contenitore previsto, senza sacchi.",
        }
    if stream == "Rifiuto residuo":
        return "mastello", {
            "mode": "bag_unspecified", "max_volume_l": None,
            "instructions_raw": "Usare il sacco previsto dal servizio dentro il mastello; non usare sacchi neri.",
        }
    return "sacco dedicato", {
        "mode": "bag_unspecified", "max_volume_l": None,
        "instructions_raw": "Servizio su richiesta; usare la fornitura dedicata." if on_request else None,
    }


def extract_rea_weekly_calendar(
    context: MunicipalityContext, retrieved_at: datetime, url: str,
    pdf_path: Path, config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if config["istat"] != context.istat_code:
        return [], [{
            "code": "weekly_calendar_municipality_mismatch",
            "detail": f"Il calendario verificato per {config['istat']} e collegato anche a {context.istat_code}",
            "url": url,
        }]
    pages, bbox = _pdf_bbox_words(pdf_path)
    text_content = " ".join(word["text"] for page in pages for word in page["words"])
    source = SourceDocument(
        url, retrieved_at, bbox, publisher="REA S.p.A.",
        parser="rea_weekly_icon_calendar_verified", parser_version="0.1.0",
    )
    validity = {
        "valid_from": config["valid_from"], "valid_to": None, "inferred": True,
    }
    records: list[dict[str, Any]] = []
    zone_keys = {row[0] for row in config["rows"]}
    if "default" in zone_keys:
        zone_ref = f"service-zone:{context.istat_code}:default"
        records.append(make_record(
            record_type="service_zone", natural_key=zone_ref,
            payload={
                "municipality_ref": context.municipality_ref,
                "name": "Intero territorio comunale", "scope_type": "municipality_default",
                "included_places_raw": None, "excluded_places_raw": None,
                "geometry_geojson": None,
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-grid",
            evidence_quote=config["label"], validity=validity,
        ))
    for zone_key, (name, places) in config.get("zones", {}).items():
        zone_ref = f"service-zone:{context.istat_code}:{zone_key}"
        records.append(make_record(
            record_type="service_zone", natural_key=zone_ref,
            payload={
                "municipality_ref": context.municipality_ref, "name": name,
                "scope_type": "custom", "included_places_raw": places,
                "excluded_places_raw": None, "geometry_geojson": None,
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-grid",
            evidence_quote=f"{config['label']}: {name}", validity=validity,
        ))
    for zone_key, user_type, stream, event_rows in config["rows"]:
        zone_ref = f"service-zone:{context.istat_code}:{zone_key}"
        method = "street" if stream == "Vetro" and not event_rows else "door_to_door"
        on_request = stream == "Pannolini e pannoloni"
        container, presentation = _weekly_presentation(stream, on_request)
        rule_ref = (
            f"collection-rule:{context.istat_code}:{zone_key}:{method}:"
            f"{user_type}:{_slug(stream)}"
        )
        raw_events = []
        for weekday, start_month_day, end_month_day in event_rows:
            seasonal = (
                f"dal {start_month_day[3:]}/{start_month_day[:2]} "
                f"al {end_month_day[3:]}/{end_month_day[:2]}"
                if start_month_day and end_month_day else None
            )
            raw_events.append({
                "kind": "weekly", "weekday": weekday, "dates": [],
                "start_month_day": start_month_day,
                "end_month_day": end_month_day,
                "raw": seasonal or ("Servizio su richiesta" if on_request else None),
            })
        schedule_raw = (
            "Raccolta con campane stradali"
            if method == "street"
            else "Calendario settimanale verificato dalla tabella grafica REA"
        )
        records.append(make_record(
            record_type="collection_rule", natural_key=rule_ref,
            payload={
                "municipality_ref": context.municipality_ref, "zone_ref": zone_ref,
                "user_type": user_type, "collection_method": method,
                "stream_name": stream, "included_materials_raw": None,
                "container_type": container, "container_color": None,
                "access_credential": None, "presentation": presentation,
                "schedule_raw": schedule_raw,
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-grid",
            evidence_quote=f"{config['label']}: {stream} - {schedule_raw}",
            validity=validity,
        ))
        if not raw_events:
            continue
        expose_from, expose_by = config.get("zone_exposure", {}).get(
            zone_key, (config.get("expose_from"), config.get("expose_by")),
        )
        records.append(make_record(
            record_type="collection_schedule",
            natural_key=f"{rule_ref}:schedule:weekly",
            payload={
                "collection_rule_ref": rule_ref, "expose_from": expose_from,
                "expose_by": expose_by, "events": raw_events,
            },
            source=source, evidence_kind="pdf", evidence_selector="calendar-grid",
            evidence_quote=(
                f"{config['label']}: {stream}; giorni "
                + ", ".join(str(event[0]) for event in event_rows)
            ),
            validity=validity,
        ))
    warnings = []
    required_labels = {"ORGANICO", "CARTA"}
    if not all(label in text_content.upper() for label in required_labels):
        warnings.append({
            "code": "weekly_calendar_text_layer_incomplete",
            "detail": "La tabella e stata verificata visivamente, ma il livello testuale PDF e incompleto",
            "url": url,
        })
    return records, warnings


def _is_calendar_document(page: dict[str, Any]) -> bool:
    filename = urlparse(page.get("final_url") or page["url"]).path.rsplit("/", 1)[-1].casefold()
    return any(token in filename for token in (
        "calendar", "ecomobile", "informativa_ud", "pap-", "raccolta-vetro",
    ))


def _main(root: Element) -> Element:
    return root.find_first(lambda item: "zui-content" in item.classes) or root.find_first(lambda item: item.tag == "main") or root


def _following_list(heading: Element | None) -> Element | None:
    if not heading or not heading.parent:
        return None
    siblings = heading.parent.children
    try:
        start = siblings.index(heading) + 1
    except ValueError:
        return None
    for sibling in siblings[start:]:
        if isinstance(sibling, Element) and sibling.tag == "ul":
            return sibling
        if isinstance(sibling, Element) and sibling.tag in {"h2", "h3", "h4"}:
            return None
    return heading.parent.find_first(lambda item: item.tag == "ul")


def _accepted_descriptions(content: Element) -> list[str]:
    elements = list(content.descendants())
    heading_index = next((
        index for index, item in enumerate(elements)
        if clean_text(item.text).casefold() == "cosa conferire"
    ), None)
    if heading_index is None:
        return []
    descriptions = []
    for item in elements[heading_index + 1:]:
        if clean_text(item.text).casefold().startswith("cosa non conferire"):
            break
        if item.tag == "li" and clean_text(item.text):
            descriptions.append(clean_text(item.text))
    return descriptions


def _stream_from_heading(value: str) -> tuple[str, str] | None:
    normalized = clean_text(value).casefold()
    headings = (
        ("secco residuo", "Rifiuto residuo"),
        ("indifferenziato", "Rifiuto residuo"),
        ("carta e cartone", "Carta e cartone"),
        ("multimateriale", "Imballaggi in multimateriale"),
        ("organico", "Rifiuti organici"),
        ("vetro", "Vetro"),
    )
    return next(
        ((token, stream) for token, stream in headings if token in normalized),
        None,
    )


def _section_after_heading(heading: Element) -> str:
    anchor = heading.parent if heading.tag == "strong" and heading.parent else heading
    if anchor.parent is None:
        return clean_text(anchor.text)
    siblings = anchor.parent.children
    start = next(
        (index for index, sibling in enumerate(siblings) if sibling is anchor),
        None,
    )
    if start is None:
        return clean_text(anchor.text)
    parts = [anchor.text]
    for sibling in siblings[start + 1:]:
        if isinstance(sibling, str):
            if clean_text(sibling):
                parts.append(sibling)
            continue
        is_heading = sibling.tag in {"h2", "h3", "h4", "h5"} or bool(
            sibling.find_first(lambda item: item.tag == "strong")
        )
        if is_heading:
            break
        parts.append(sibling.text)
    return clean_text(" ".join(parts))


def _collection_sections(content: Element) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    for heading in content.find_all(
        lambda item: item.tag in {"h2", "h3", "h4", "h5", "strong"}
    ):
        matched = _stream_from_heading(heading.text)
        if matched is None:
            continue
        _, stream = matched
        section = _section_after_heading(heading)
        sections.append((stream, clean_text(heading.text), section))
    return sections


def _collection_container(section: str) -> tuple[str | None, str | None]:
    lowered = section.casefold()
    container = next((
        value for marker, value in (
            ("cassonett", "cassonetto"),
            ("campana", "campana"),
            ("bidone", "bidone"),
            ("contenitor", "contenitore"),
        ) if marker in lowered
    ), None)
    color_markers = (
        ("giall", "giallo"),
        ("grigi", "grigio"),
        ("marron", "marrone"),
        ("blu", "blu"),
        ("verd", "verde"),
        ("bianc", "bianco"),
    )
    color_context = ""
    context_match = re.search(
        r"(?:cassonett\w*|campan\w*|bidon\w*|contenitor\w*|colore)"
        r".{0,80}",
        lowered,
    )
    if context_match:
        color_context = context_match.group(0)
    color = next((
        value for marker, value in color_markers if marker in color_context
    ), None)
    return container, color


def extract_rea_collection_pages(
    context: MunicipalityContext,
    retrieved_at: datetime,
    pages: Iterable[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    zone_ref = f"service-zone:{context.istat_code}:default"
    zone_added = False
    seen: set[str] = set()
    for url, html in pages:
        path = urlparse(url).path
        if not path.startswith("/servizi/"):
            continue
        root = parse_html(html)
        text = _main(root).text
        lowered = text.casefold()
        if "raccolta" not in lowered:
            continue
        source = _source(url, retrieved_at, html, "rea_services_html")
        if not zone_added:
            records.append(make_record(record_type="service_zone", natural_key=zone_ref, payload={"municipality_ref": context.municipality_ref, "name": "Intero territorio comunale", "scope_type": "municipality_default", "included_places_raw": None, "excluded_places_raw": None, "geometry_geojson": None}, source=source, evidence_selector="main", evidence_quote=text[:500]))
            zone_added = True
        if any(token in path for token in ("ingombranti", "potature", "raee")):
            accepted = "Rifiuti ingombranti" if "ingombranti" in path else "Sfalci e potature" if "potature" in path else "RAEE"
            natural_key = f"rea:pickup:{context.istat_code}:{_slug(accepted)}"
            if natural_key in seen:
                continue
            seen.add(natural_key)
            phone = root.find_first(lambda item: item.tag == "a" and item.attrs.get("href", "").startswith("tel:"))
            methods = [{"method": "web", "value": url, "hours_raw": None}]
            if phone:
                methods.append({"method": "phone", "value": phone.attrs["href"].removeprefix("tel:"), "hours_raw": None})
            records.append(make_record(record_type="pickup_service", natural_key=natural_key, payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": accepted, "booking_methods": methods, "max_items": None, "quantity_limit_raw": None, "placement_instructions_raw": text[:4000], "booking_required": True}, source=source, evidence_selector="main", evidence_quote=text[:1000]))
            continue
        if not any(marker in path for marker in ("raccolta-stradale", "porta-a-porta")):
            continue
        page_method = "street" if "stradale" in path else "door_to_door"
        query = dict(parse_qsl(urlparse(url).query))
        user_type = {
            "domestica": "domestic",
            "non-domestica": "non_domestic",
        }.get(query.get("utenza", ""), "all")
        general_bag_rule = bool(re.search(
            r"collocazione dei rifiuti in sacchetti chiusi.{0,120}cassonetti",
            lowered,
        ))
        for stream, heading, section in _collection_sections(_main(root)):
            section_lowered = section.casefold()
            method = (
                "door_to_door" if "porta a porta" in section_lowered
                else page_method
            )
            generic_heading = clean_text(heading).casefold().startswith(
                ("imballaggi", "secco residuo")
            ) or "solo dove attiva" in section_lowered
            section_user_type = (
                "non_domestic" if "utenze non domestiche" in section_lowered
                else "domestic" if "utenze domestiche" in section_lowered
                else "all" if generic_heading
                else user_type
            )
            key = f"{method}:{section_user_type}:{_slug(stream)}"
            if key in seen:
                continue
            seen.add(key)
            container, color = _collection_container(section)
            if "compostabil" in section_lowered:
                mode = "compostable_bag"
            elif "sacco" in section_lowered or "sacchet" in section_lowered or general_bag_rule:
                mode = "bag_unspecified"
            else:
                mode = "unspecified"
            materials_match = re.search(r"\(([^()]*(?:imballagg|plastic|accia|allumin|vetr|poliacc)[^()]*)\)", heading, re.IGNORECASE)
            instructions = re.sub(
                r"^.*?raccolta\s+(?:stradale|porta\s+a\s+porta)\s*",
                "Raccolta ", section, count=1, flags=re.IGNORECASE,
            )
            records.append(make_record(
                record_type="collection_rule",
                natural_key=f"collection-rule:{context.istat_code}:default:{key}",
                payload={
                    "municipality_ref": context.municipality_ref,
                    "zone_ref": zone_ref,
                    "user_type": section_user_type,
                    "collection_method": method,
                    "stream_name": stream,
                    "included_materials_raw": (
                        clean_text(materials_match.group(1))
                        if materials_match else None
                    ),
                    "container_type": container,
                    "container_color": color,
                    "access_credential": None,
                    "presentation": {
                        "mode": mode,
                        "max_volume_l": None,
                        "instructions_raw": clean_text(instructions),
                    },
                    "schedule_raw": None,
                },
                source=source,
                evidence_selector="main",
                evidence_quote=section[:1000],
                confidence="medium",
            ))
    if not zone_added:
        warnings.append({"code": "collection_rules_missing", "detail": "Nessuna regola di raccolta estraibile dalle pagine REA acquisite", "url": ""})
    return records, warnings


def extract_rea_centre(
    context: MunicipalityContext, retrieved_at: datetime, url: str, html: str,
    owner_context: MunicipalityContext | None = None,
) -> list[dict[str, Any]]:
    root = parse_html(html)
    content = _main(root)
    heading = content.find_first(lambda item: item.tag == "h1") or content.find_first(lambda item: item.tag == "h2")
    title = clean_text(heading.text if heading else urlparse(url).path.rstrip("/").split("/")[-1].replace("-", " ").title())
    text = content.text_with_breaks
    facility_ref = f"rea:facility:{_slug(title)}"
    address_match = re.search(r"Dove siamo:\s*(.+?)(?:\n|Cosa conferire|Modalità di accesso|$)", text, re.IGNORECASE)
    address = clean_text(address_match.group(1)) if address_match else None
    source = _source(url, retrieved_at, html, "rea_centre_html")
    owner_context = owner_context or context
    records = [make_record(record_type="facility", natural_key=facility_ref, payload={"name": title, "municipality_ref": owner_context.municipality_ref, "facility_type": "collection_centre", "address_raw": address, "location": None, "phone": None, "email": None, "operational_status": "open", "status_raw": None}, source=source, evidence_selector="main", evidence_quote=text[:1000])]
    records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{context.istat_code}:all", payload={"facility_ref": facility_ref, "municipality_ref": context.municipality_ref, "user_type": "all", "allowed": True, "requirements_raw": text[:5000], "booking_required": None, "information_urls": [url], "contact_phone": None, "contact_email": None}, source=source, evidence_selector="main", evidence_quote=text[:1000]))
    descriptions = _accepted_descriptions(content)
    if descriptions:
        for index, description in enumerate(descriptions):
            if description:
                normalized_description = clean_text(description).casefold()
                domestic_only = bool(re.search(
                    r"\bsolo (?:da |per )?(?:le )?utenze domestiche\b",
                    normalized_description,
                ))
                records.append(make_record(record_type="facility_acceptance", natural_key=f"{facility_ref}:description:{index}:{_slug(description[:60])}", payload={"facility_ref": facility_ref, "eer_code_raw": None, "eer_code_normalized": None, "eer_code_status": "unmapped_description", "reconciliation_basis": None, "hazardous": None, "description_raw": description, "operational_group": None, "user_type": "domestic" if domestic_only else "unspecified", "quantity_limit_raw": None, "notes_raw": "La fonte REA non pubblica il codice EER per questa voce; pericolosità non determinabile dal solo elenco"}, source=source, evidence_selector="main", evidence_quote=description))
    when_match = re.search(r"Quando:\s*(.+?)\s*(?:Dove siamo:|Cosa conferire|$)", text, re.IGNORECASE | re.DOTALL)
    if when_match:
        raw = clean_text(when_match.group(1))
        records.append(make_record(record_type="opening_period", natural_key=f"{facility_ref}:opening:published", payload={"facility_ref": facility_ref, "period_label": "Orari pubblicati", "start_month_day": None, "end_month_day": None, "weekly_intervals": [], "exceptions_raw": raw}, source=source, evidence_selector="main", evidence_quote=raw))
    return records


def materialize_rea_services(
    municipalities: list[dict[str, Any]], manifest: dict[str, Any], snapshot_root: Path,
    rifiutario_json: str, retrieved_at: datetime,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    html_pages = []
    for page in manifest["pages"]:
        if page["status"] == "snapshot" and page["content_type"] != "application/pdf" and page["snapshot"].endswith(".html"):
            html_pages.append((page, (snapshot_root / page["snapshot"]).read_text(encoding="utf-8", errors="replace")))
    centre_pages = [(page, html) for page, html in html_pages if page["category"] == "centre_detail"]
    pdf_pages = [
        page for page in manifest["pages"]
        if page["status"] == "snapshot" and page.get("snapshot", "").endswith(".pdf")
    ]
    rifiutario = json.loads(rifiutario_json)
    unresolved = sum(not item.get("destination") for item in rifiutario["items"])
    results: dict[str, list[dict[str, Any]]] = {}
    reports = []
    contexts = {
        item["source_slug"]: MunicipalityContext(item["name"], item["istat_code"], item["source_slug"])
        for item in municipalities
    }
    for municipality in municipalities:
        context = MunicipalityContext(municipality["name"], municipality["istat_code"], municipality["source_slug"])
        records = extract_rea_waste_lookup(context, retrieved_at, rifiutario["source_url"], rifiutario_json)
        relevant = [(page["final_url"] or page["url"], html) for page, html in html_pages if municipality["istat_code"] in page.get("municipality_istats", [])]
        service_records, warnings = extract_rea_collection_pages(context, retrieved_at, relevant)
        records.extend(service_records)
        relevant_pdfs = [
            page for page in pdf_pages
            if municipality["istat_code"] in page.get("municipality_istats", [])
        ]
        selected_calendars: dict[tuple[str, str], dict[str, Any]] = {}
        for page in relevant_pdfs:
            user_type = _rur_calendar_type(page)
            if user_type:
                key = (page["snapshot"], user_type)
                current = selected_calendars.get(key)
                candidate_url = page.get("final_url") or page["url"]
                current_url = (current.get("final_url") or current["url"]) if current else ""
                if current is None or (
                    current_url.startswith("http://") and candidate_url.startswith("https://")
                ):
                    selected_calendars[key] = page
        materialized_pdf_snapshots = set()
        for (snapshot, user_type), page in selected_calendars.items():
            url = page.get("final_url") or page["url"]
            try:
                calendar_records, calendar_warnings = extract_rea_rur_calendar(
                    context, retrieved_at, url, snapshot_root / snapshot, user_type,
                )
            except (OSError, subprocess.CalledProcessError, ET.ParseError) as error:
                calendar_records = []
                calendar_warnings = [{
                    "code": "calendar_pdf_extraction_failed",
                    "detail": f"Impossibile leggere il calendario PDF: {error}",
                    "url": url,
                }]
            if calendar_records:
                records.extend(calendar_records)
                materialized_pdf_snapshots.add(snapshot)
            warnings.extend(calendar_warnings)
        selected_ecomobile = {
            page["snapshot"]: page for page in relevant_pdfs if _ecomobile_config(page)
        }
        for snapshot, page in selected_ecomobile.items():
            url = page.get("final_url") or page["url"]
            try:
                calendar_records, calendar_warnings = extract_rea_ecomobile_calendar(
                    context, retrieved_at, url, snapshot_root / snapshot,
                    _ecomobile_config(page),
                )
            except (OSError, subprocess.CalledProcessError, ET.ParseError) as error:
                calendar_records = []
                calendar_warnings = [{
                    "code": "calendar_pdf_extraction_failed",
                    "detail": f"Impossibile leggere il calendario PDF: {error}",
                    "url": url,
                }]
            if calendar_records:
                records.extend(calendar_records)
                materialized_pdf_snapshots.add(snapshot)
            warnings.extend(calendar_warnings)
        selected_weekly = {
            page["snapshot"]: page
            for page in relevant_pdfs if _weekly_calendar_config(page)
        }
        for snapshot, page in selected_weekly.items():
            url = page.get("final_url") or page["url"]
            try:
                calendar_records, calendar_warnings = extract_rea_weekly_calendar(
                    context, retrieved_at, url, snapshot_root / snapshot,
                    _weekly_calendar_config(page),
                )
            except (OSError, subprocess.CalledProcessError, ET.ParseError) as error:
                calendar_records = []
                calendar_warnings = [{
                    "code": "calendar_pdf_extraction_failed",
                    "detail": f"Impossibile leggere il calendario PDF: {error}",
                    "url": url,
                }]
            if calendar_records:
                records.extend(calendar_records)
                materialized_pdf_snapshots.add(snapshot)
            warnings.extend(calendar_warnings)
        linked_centres = {_canonical_url(link) for page_url, html in relevant for link, _ in _links(html, page_url) if urlparse(link).path.startswith("/centri-di-raccolta/") and not re.fullmatch(r"/centri-di-raccolta/(?:page/\d+/)?", urlparse(link).path)}
        municipal_slug = municipality["source_slug"]
        permitted_centres = _CENTRE_ACCESS.get(municipal_slug, {municipal_slug})
        for page, html in centre_pages:
            centre_url = _canonical_url(page["final_url"] or page["url"])
            centre_slug = urlparse(centre_url).path.rstrip("/").split("/")[-1]
            if centre_url in linked_centres or centre_slug in permitted_centres:
                owner_slug = _CENTRE_OWNER.get(centre_slug, centre_slug)
                records.extend(extract_rea_centre(context, retrieved_at, centre_url, html, contexts.get(owner_slug, context)))
        pdf_count = len({page["snapshot"] for page in relevant_pdfs})
        calendar_pdf_count = len({
            page["snapshot"] for page in relevant_pdfs if _is_calendar_document(page)
        })
        if pdf_count:
            warnings.append({
                "code": "calendar_pdf_coverage",
                "detail": (
                    f"{pdf_count} PDF comunali unici acquisiti; {calendar_pdf_count} "
                    f"classificati come calendari o guide operative; "
                    f"{len(materialized_pdf_snapshots)} calendari materializzati"
                ),
                "url": municipality["homepage_url"],
            })
        if unresolved:
            warnings.append({"code": "waste_lookup_destinations_missing", "detail": f"{unresolved} voci REA non hanno una destinazione pubblicata", "url": rifiutario["source_url"]})
        results[municipality["source_slug"]] = records
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        available = sum(municipality["istat_code"] in page.get("municipality_istats", []) and page["status"] == "snapshot" for page in manifest["pages"])
        reports.append({"municipality": municipality["name"], "istat_code": municipality["istat_code"], "pages_available": available, "pages_materialized": available - pdf_count + len(materialized_pdf_snapshots), "equivalent_pages": [], "records": len(records), "records_by_type": counts, "warnings": warnings})
    return results, reports
