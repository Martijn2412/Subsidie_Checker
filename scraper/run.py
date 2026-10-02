"""
Subsidie-scraper voor isolatieregelingen van ALLE Nederlandse gemeenten.

Per gemeente:
  1. Snel zoeken in het CVDR (lokaleregelgeving.overheid.nl).
  2. Gevonden? Het taalmodel leest de voorwaarden uit (bedrag, WOZ, bouwjaar, ...).
     Het gratis quotum is niet genoeg voor alles in één keer: wat niet lukt,
     volgt bij de volgende run. Al uitgelezen regelingen worden alleen opnieuw
     gelezen als de CVDR-versie verandert.
  3. Niets relevants in het CVDR? Dan zoekt het taalmodel op internet (Google),
     vooral op de gemeentesite. Zulke regelingen krijgen "bron": "web" en
     betrouwbaarheid "laag": altijd zelf controleren.

Schrijft regelingen.json (de checkpagina) en zoekstatus.json (per gemeente:
wat nog wacht op uitlezen en wanneer er op internet is gezocht).

Draait in GitHub Actions. Taalmodel kies je in scraper/config.json ("provider":
"gemini" of "claude"). Lokaal testen: pip install requests google-genai anthropic
  python scraper/run.py                       normale run
  python scraper/run.py --forceer             alles opnieuw extraheren
  python scraper/run.py --alleen Doesburg,Arnhem   alleen deze gemeenten
  python scraper/run.py --vergelijk tests/baseline_pilot.json
  python scraper/run.py --alleen-overzicht    alleen overzicht_voorwaarden.xlsx opnieuw maken
"""
import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import signal
import sys
import time
from urllib.parse import urljoin, urlparse

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from normaliseer import normaliseer  # noqa: E402  (getallen als getal, ja/nee als true/false)
import export_tios  # noqa: E402  (tios/subsidies.json en .csv voor de koppeling met TIOS)

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "scraper/config.json").read_text(encoding="utf-8"))
PROMPT = (ROOT / "scraper/prompt_extractie.md").read_text(encoding="utf-8")
OUT = ROOT / "regelingen.json"
DATA = ROOT / "data"
STATE = DATA / "state.json"
DEKKING = DATA / "dekking.json"
LOG_ALL = DATA / "wijzigingen.md"
LOG_LAST = DATA / "wijzigingen_laatste.md"
ALLE_GEMEENTEN = DATA / "alle_gemeenten.json"  # buffer voor als PDOK even niet reageert
ZOEKSTATUS = ROOT / "zoekstatus.json"  # per gemeente: wachtrij + laatste zoekactie op internet
WEB_STATE = DATA / "web_state.json"  # wanneer per gemeente op internet is gezocht
OVERZICHT = ROOT / "overzicht_voorwaarden.xlsx"  # alles in één sheet, om te lezen
VOORTGANG = DATA / "voortgang.json"  # bij welke gemeente de volgende run begint
SRU = "https://zoekservice.overheid.nl/sru/Search"
UA = {"User-Agent": "Takkenkamp-subsidiecheck/0.1 (interne tool)"}
VANDAAG = dt.date.today().isoformat()
DATA.mkdir(parents=True, exist_ok=True)  # map data/ aanmaken als die ontbreekt
FORCEER = "--forceer" in sys.argv
PROVIDER = CFG.get("provider", "gemini")
MODELLEN = CFG["modellen"][PROVIDER]
PAUZE = CFG.get("pauze_tussen_aanroepen_sec", 7)  # gratis Gemini: max. enkele verzoeken per minuut
START = time.monotonic()
MAX_AI_SEC = CFG.get("max_minuten_taalmodel", 100) * 60  # daarna: rest bij de volgende run
MAX_RUN_SEC = CFG.get("max_minuten_run", 300) * 60  # daarna netjes stoppen, ruim vóór de grens van GitHub
BEWAAR_ELKE_SEC = 300  # tussentijds opslaan, zodat een harde onderbreking weinig werk kost
ALLEEN = [n.strip().lower() for n in sys.argv[sys.argv.index("--alleen") + 1].split(",")] if "--alleen" in sys.argv else None

if "--alleen-overzicht" in sys.argv:
    client = None  # geen taalmodel nodig, dus ook geen sleutel
elif PROVIDER == "gemini":
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                          http_options=types.HttpOptions(timeout=180_000))  # max. 3 min per aanroep
else:
    from anthropic import Anthropic
    client = Anthropic()  # leest ANTHROPIC_API_KEY


# ---------- hulpfuncties ----------
def heeft_voorwaarden(r):
    """Staat er minstens één toetsbare voorwaarde in de regeling?"""
    return any(v not in (None, "", [], {}) for k, v in (r.get("criteria") or {}).items()
               if not re.search(r"opmerking|peildatum|regel$|uitzondering", k))


def schrijf_samenvatting(resultaten, stand, totaal):
    """Overzicht per gemeente: in de log en op de samenvattingspagina van de GitHub-run."""
    volgorde = {"❌": 0, "🛑": 1, "⚠️": 2, "➖": 3, "✅": 4}
    tel = {}
    for _, sym, _ in resultaten:
        tel[sym] = tel.get(sym, 0) + 1
    kop = (f"{len(resultaten)} van {totaal} gemeenten bekeken: "
           + ", ".join(f"{sym} {tel[sym]}" for sym in sorted(tel, key=lambda x: volgorde.get(x, 9))))
    print("\n== Samenvatting ==\n" + kop)
    print("✅ voorwaarden opgehaald · ⚠️ deels gelukt of zonder voorwaarden · ➖ geen (open) regeling · "
          "❌ mislukt · 🛑 gestopt (budget/tijd)")
    pad = os.environ.get("GITHUB_STEP_SUMMARY")
    if not pad:
        return
    regels = ["## Subsidie-update: resultaat per gemeente", "", kop, ""]
    if stand.get("volgende"):
        regels += [f"**Gestopt ({stand['reden']}).** De volgende run gaat verder bij **{stand['volgende']}**.", ""]
    regels += ["✅ voorwaarden opgehaald · ⚠️ deels gelukt of zonder voorwaarden · ➖ geen (open) regeling · "
               "❌ mislukt · 🛑 gestopt", "", "| | Gemeente | Resultaat |", "|---|---|---|"]
    for naam, sym, tekst in sorted(resultaten, key=lambda x: (volgorde.get(x[1], 9), x[0])):
        regels.append(f"| {sym} | {naam} | {tekst.replace('|', '/')} |")
    with open(pad, "a", encoding="utf-8") as f:
        f.write("\n".join(regels) + "\n")


def limiet_reden(fout):
    """Korte reden voor de PR-tekst waarom de run stopte."""
    return "AI-tijd van deze run op" if "tijdslimiet" in str(fout) else "AI-budget of daglimiet op"


def lees(p, standaard):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else standaard


def schrijf(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class LimietOp(Exception):
    """De (gratis) limiet van het taalmodel is bereikt; de rest volgt bij de volgende run."""


TOKENS = {"extractie": 16000, "zoeken": 4000, "filter": 1000}
UITGEPUT = set()  # modellen waarvan de daglimiet op is: deze run niet meer proberen


def is_limiet(fout):
    """429 = limiet, 402 = tegoed op. Beide: stoppen of reservemodel, niet blijven proberen."""
    return re.search(r"\b(429|402)\b|RESOURCE_EXHAUSTED|rate_limit|credits", fout) is not None


def is_daglimiet(fout):
    return re.search(r"\b402\b|credits|per ?day", fout, re.I) is not None


def llm(taak, tekst, json_uit=False, zoeken=False, tokens=None):
    """Stuurt tekst naar het taalmodel. Bij drukte of limiet: eerst even wachten,
    dan het reservemodel proberen, en anders LimietOp opgooien.
    zoeken=True: het model mag op internet zoeken (Google bij Gemini, web search bij Claude)."""
    if time.monotonic() - START > MAX_AI_SEC:
        raise LimietOp("tijdslimiet van deze run bereikt")
    modellen = [MODELLEN[taak]] + ([MODELLEN[taak + "_reserve"]] if MODELLEN.get(taak + "_reserve") else [])
    modellen = [m for m in modellen if m not in UITGEPUT]
    if not modellen:
        raise LimietOp(f"daglimiet bereikt voor {taak}")
    laatste_fout = None
    for model in modellen:
        for poging in range(3):
            try:
                time.sleep(PAUZE)
                if PROVIDER == "gemini":
                    cfg = types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=tokens or TOKENS[taak],
                        # JSON-modus gaat niet samen met Google zoeken; dan zelf de JSON uit de tekst halen
                        response_mime_type="application/json" if json_uit and not zoeken else "text/plain",
                        tools=[types.Tool(google_search=types.GoogleSearch())] if zoeken else None,
                    )
                    r = client.models.generate_content(model=model, contents=tekst, config=cfg)
                    if not r.text:
                        raise RuntimeError("leeg antwoord")
                    return r.text
                extra = {"tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]} if zoeken else {}
                r = client.messages.create(model=model, max_tokens=min(tokens or TOKENS[taak], 8000),
                                           messages=[{"role": "user", "content": tekst}], **extra)
                return "".join(b.text for b in r.content if b.type == "text")
            except Exception as e:
                fout = str(e)
                laatste_fout = fout
                limiet = is_limiet(fout)
                if limiet and is_daglimiet(fout):
                    UITGEPUT.add(model)
                    print(f"  {model}: daglimiet of tegoed op, deze run niet meer gebruiken")
                    break
                if limiet and poging >= 1:
                    print(f"  {model}: limiet bereikt, ander model proberen")
                    break
                wacht = 40 if limiet else 20 * (poging + 1)
                print(f"  {model}: fout ({fout[:110]}), wacht {wacht}s, poging {poging + 1}/3")
                time.sleep(wacht)
    if laatste_fout and is_limiet(laatste_fout):
        raise LimietOp(laatste_fout[:200])
    raise RuntimeError(f"Taalmodel faalt: {(laatste_fout or '')[:200]}")


def parse_json(tekst):
    tekst = re.sub(r"^```(?:json)?|```$", "", tekst.strip(), flags=re.M).strip()
    try:
        return json.loads(tekst)
    except json.JSONDecodeError:  # bijv. tekst rond de JSON na een zoekactie
        m = re.search(r"\{.*\}", tekst, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


# ---------- stap 1: zoeken in het CVDR ----------
def zoek_cvdr(gemeente, trefwoorden=None):
    """Geeft {cvdr_id: {versie, titel, xml_url, gewijzigd}} met alleen de hoogste versie."""
    gevonden = {}
    per_pagina = CFG["max_resultaten_per_zoekvraag"]
    for woord in trefwoorden or CFG["trefwoorden"]:
        for start in range(1, 4 * per_pagina, per_pagina):  # grote gemeenten: max. 4 pagina's
            params = {
                "version": "1.2", "operation": "searchRetrieve", "x-connection": "cvdr",
                "query": f'dcterms.creator="{gemeente}" AND keyword all "{woord}"',
                "startRecord": start, "maximumRecords": per_pagina,
                "x-info-1-accept": "any",
            }
            r = requests.get(SRU, params=params, headers=UA, timeout=60)
            r.raise_for_status()
            dbg = DATA / "debug_sru_voorbeeld.xml"  # bewaar één ruwe respons om veldnamen te checken
            if not dbg.exists():
                dbg.write_text(r.text, encoding="utf-8")
            for rec in re.findall(r"<(?:\w+:)?recordData>(.*?)</(?:\w+:)?recordData>", r.text, re.S):
                m = re.search(r">(CVDR\d+)_(\d+)<", rec)
                url = re.search(r"(https://repository\.officiele-overheidspublicaties\.nl/cvdr/CVDR\d+/\d+/xml/[^<\s\"]+\.xml)", rec, re.I)
                if not (m and url):
                    continue
                eind = re.search(r"uitwerkingtreding[^>]*>(\d{4}-\d{2}-\d{2})<", rec, re.I)
                if eind and eind.group(1) < VANDAAG:
                    continue  # regeling is al vervallen
                cid, versie = m.group(1), int(m.group(2))
                titel = re.search(r"<dcterms:title[^>]*>(.*?)</dcterms:title>", rec, re.S)
                gew = re.search(r"<dcterms:modified[^>]*>(\d{4}-\d{2}-\d{2})", rec)
                if cid not in gevonden or versie > gevonden[cid]["versie"]:
                    gevonden[cid] = {"versie": versie, "xml_url": url.group(1),
                                     "titel": html.unescape(titel.group(1).strip()) if titel else cid,
                                     "gewijzigd": gew.group(1) if gew else None}
            time.sleep(1)  # netjes blijven tegen de overheidsserver
            totaal = re.search(r"numberOfRecords>(\d+)<", r.text)
            if not totaal or int(totaal.group(1)) < start + per_pagina:
                break  # alle resultaten binnen
    return gevonden


def haal_alle_gemeenten():
    """Alle Nederlandse gemeenten via de PDOK Locatieserver. Lukt dat niet, dan de lijst van de vorige run."""
    url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
    gemeenten = {}
    try:
        for start in range(0, 500, 100):
            r = requests.get(url, params={"q": "*:*", "fq": "type:gemeente", "fl": "gemeentenaam,provincienaam",
                                          "rows": 100, "start": start}, headers=UA, timeout=60)
            r.raise_for_status()
            docs = r.json()["response"]["docs"]
            for d in docs:
                gemeenten[d["gemeentenaam"]] = d.get("provincienaam")
            if len(docs) < 100:
                break
    except Exception as e:
        print(f"Gemeentelijst ophalen bij PDOK mislukt ({e}); vorige lijst gebruiken")
        return lees(ALLE_GEMEENTEN, [])
    lijst = [{"naam": n, "provincie": p} for n, p in sorted(gemeenten.items())]
    if len(lijst) > 300:  # alleen bewaren als de lijst compleet lijkt
        schrijf(ALLE_GEMEENTEN, lijst)
        return lijst
    print(f"Gemeentelijst van PDOK lijkt onvolledig ({len(lijst)}); vorige lijst gebruiken")
    return lees(ALLE_GEMEENTEN, lijst)


def gemeentelijst():
    """Alle gemeenten (via PDOK), of alleen config.json als "alle_gemeenten" uit staat."""
    if not CFG.get("alle_gemeenten", True):
        lijst = CFG["gemeenten"]
    else:
        lijst = haal_alle_gemeenten() or CFG["gemeenten"]
    if ALLEEN:
        lijst = [g for g in lijst if g["naam"].lower() in ALLEEN]
    return lijst


# ---------- stap 5: niets in het CVDR? zoeken op internet ----------
WEB_PROMPT = """Zoek op internet of de gemeente {g} op dit moment een EIGEN subsidie, lening, voucher of
waardebon heeft voor ISOLATIE van BESTAANDE woningen van particulieren (dak, zolder, gevel, spouwmuur,
vloer/bodem, isolerend glas). Kijk vooral op de website van de gemeente {g} en op verbeterjehuis.nl.
Negeer: landelijke regelingen (ISDE, Warmtefonds), regelingen van andere gemeenten of de provincie,
regelingen voor bedrijven, verhuurders of monumenten, en regelingen die al gesloten zijn.

Antwoord met ALLEEN deze JSON, zonder uitleg:
{{"regelingen": [{{"naam": "...", "url": "directe link naar de pagina over deze regeling",
  "samenvatting": "1-3 zinnen: wat, voor wie, hoeveel, tot wanneer"}}]}}
Niets gevonden? Antwoord {{"regelingen": []}}. Verzin nooit een regeling of link."""


# Sommige gemeentesites (bijv. Groningen) weigeren onbekende programma's; doe je voor als gewone browser
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36", "Accept-Language": "nl-NL,nl;q=0.9"}


def html_naar_tekst(h):
    t = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", h)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def haal_webpagina(url):
    r = requests.get(url, headers=BROWSER, timeout=60)
    r.raise_for_status()
    return html_naar_tekst(r.text)[:60_000]


def haal_ruw(url):
    """Pagina of PDF ophalen. Geeft (tekst, html) terug; html is leeg bij een PDF."""
    r = requests.get(url, headers=BROWSER, timeout=60)
    r.raise_for_status()
    if "pdf" in r.headers.get("Content-Type", "").lower() or url.lower().split("?")[0].endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader
            tekst = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages[:30])
            return re.sub(r"\s+", " ", tekst).strip(), ""
        except ImportError:
            return "", ""
    return html_naar_tekst(r.text), r.text


LINK_WEL = re.compile(r"voorwaarde|subsidieregeling|regeling|aanvra|spelregel|reglement|\.pdf", re.I)


def vervolglinks(basis_url, h, max_links=2):
    """Links op dezelfde site die waarschijnlijk naar de voorwaarden of de regeling zelf gaan."""
    domein = urlparse(basis_url).netloc
    gezien, uit = {basis_url.split("#")[0]}, []
    for href, tekst in re.findall(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', h):
        url = urljoin(basis_url, html.unescape(href))
        if url in gezien or not url.startswith("http"):
            continue
        if urlparse(url).netloc != domein and "lokaleregelgeving" not in url:
            continue
        label = html_naar_tekst(tekst) + " " + url
        if LINK_WEL.search(label) and re.search(r"isol|subsidie|regeling|voorwaarde|duurza", label, re.I):
            gezien.add(url)
            uit.append(url)
        if len(uit) >= max_links:
            break
    return uit


def lees_pagina(url):
    """Tekst van de bronpagina plus maximaal 2 doorverwijzingen (voorwaarden, regeling, PDF)."""
    tekst, h = haal_ruw(url)
    delen = [tekst]
    for link in vervolglinks(url, h) if h else []:
        try:
            t, _ = haal_ruw(link)
            if len(t) > 200:
                delen.append(f"\n\n[Doorverwezen pagina: {link}]\n{t}")
        except Exception as e:
            print(f"  web: doorverwijzing {link} niet op te halen ({e})")
    return "".join(delen)[:80_000]


WEB_LEES = """

LET OP: de regelingstekst staat hier niet. Zoek zelf op internet de voorwaarden van de regeling
"{naam}" van de gemeente {g}. Begin bij {url} en kijk ook naar de pagina's en PDF's waar die pagina naar
verwijst (bijv. "voorwaarden", "spelregels" of de subsidieregeling zelf). Gebruik alleen de website van
de gemeente of een officiële bron. Vind je een voorwaarde niet, zet het veld dan op null."""


def lees_webregeling(naam, gemeente, url):
    """Voorwaarden van een via internet gevonden regeling uitlezen.
    Eerst de pagina zelf (en doorverwijzingen); lukt dat niet of staat er niets in, dan het taalmodel
    laten zoeken. Geeft (ext, methode) terug; ext is leeg als het niet lukte."""
    try:
        tekst = lees_pagina(url)
    except Exception as e:
        print(f"  web: {url} niet op te halen ({e}); taalmodel laten zoeken")
        tekst = ""
    if len(tekst) > 300:
        ext = extraheer(tekst)
        if ext and (not ext.get("relevant", True) or heeft_voorwaarden(ext)):
            return ext, "pagina"
        print(f"  web: geen voorwaarden op {url}; taalmodel laten zoeken")
    elif tekst:
        print(f"  web: {url} bevat te weinig tekst ({len(tekst)} tekens); taalmodel laten zoeken")
    try:
        ext = parse_json(llm("zoeken", PROMPT + WEB_LEES.format(naam=naam, g=gemeente, url=url),
                             json_uit=True, zoeken=True, tokens=TOKENS["extractie"]))
    except LimietOp:
        raise
    except Exception as e:
        print(f"  web: voorwaarden zoeken mislukt ({e})")
        return {}, None
    return ext, "zoeken"


def voeg_voorwaarden_toe(rec, ext, methode, samenvatting=""):
    """Uitgelezen voorwaarden in een web-record zetten. Naam, link en bron blijven staan."""
    titel = rec["naam"]
    ext = dict(ext)
    ext.pop("relevant", None)
    rec.update({k: v for k, v in ext.items() if v is not None and k not in ("bron_url", "id", "gemeente")})
    rec = normaliseer(rec)
    rec["naam"] = ext.get("naam") or titel
    hoe = {"pagina": "Voorwaarden uitgelezen van de bronpagina.",
           "zoeken": "Voorwaarden opgezocht door het taalmodel (niet van de pagina zelf gelezen)."}.get(methode, "")
    rec["opmerkingen"] = " ".join(x for x in ["Gevonden via AI-zoekactie op internet, niet in het CVDR. Controleer de bronpagina.",
                                              hoe, samenvatting, ext.get("opmerkingen") or ""] if x).strip()
    rec["voorwaarden_gelezen"] = VANDAAG
    rec["status"] = status(rec)
    rec["betrouwbaarheid"] = "laag"
    return rec


def web_zoek(g):
    """Laat het taalmodel op internet zoeken en leest gevonden pagina's uit. Geeft een lijst records."""
    naam = g["naam"]
    antw = parse_json(llm("zoeken", WEB_PROMPT.format(g=naam), json_uit=True, zoeken=True))
    recs = []
    for w in (antw.get("regelingen") or [])[:3]:
        url, titel = (w.get("url") or "").strip(), (w.get("naam") or "").strip()
        if not url.startswith("http") or not titel:
            continue
        if "lokaleregelgeving.overheid.nl" in url or "officiele-overheidspublicaties" in url:
            continue  # staat in het CVDR; die route heeft deze regeling al beoordeeld
        rec = {
            "id": f"{slug(naam)}-web-{slug(titel)[:50]}", "cvdr_id": None, "bron": "web",
            "handmatig": False, "gecontroleerd": False,
            "gemeente": naam, "provincie": g.get("provincie"), "naam": titel,
            "bron_url": url, "peildatum": VANDAAG,
        }
        ext, methode = lees_webregeling(titel, naam, url)
        if ext and not ext.get("relevant", True):
            continue
        rec = voeg_voorwaarden_toe(rec, ext, methode, w.get("samenvatting") or "")
        recs.append(rec)
    return recs


# ---------- stap 2: tekst ophalen ----------
def haal_tekst(xml_url, pagina_url=None):
    """Tekst van de regeling uit de XML. Geeft die een fout (bijv. 404), dan de gewone CVDR-pagina."""
    try:
        r = requests.get(xml_url, headers=UA, timeout=60)
        r.raise_for_status()
    except Exception as e:
        if not pagina_url:
            raise
        print(f"  XML niet bereikbaar ({e}); CVDR-pagina proberen")
        return haal_webpagina(pagina_url)[:150_000]
    t = re.sub(r"<[^>]+>", " ", r.text)
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    if "<illustratie" in r.text or ".jpg" in r.text or ".png" in r.text:
        t += "\n[LET OP: deze regeling bevat afbeeldingen (bijv. een bijlage) die niet als tekst zijn meegenomen.]"
    return t[:150_000]


# ---------- stap 3: trechter (eerst gratis, dan pas Gemini) ----------
TITEL_NIET = re.compile(
    r"algemene plaatselijke|\bapv\b|bouwverordening|leges|omgevingsplan|bestemmingsplan|mandaat|delegatie|"
    r"volmacht|welstand|monument|erfgoed|aardgasvrij|warmtepomp|zonne|warmtenet|groene? da|afval|precario|"
    r"tarie|belasting|huisvesting|parkeer|evenement|sport|cultuur|onderwijs|jeugd|wmo|bijstand|participatie|"
    r"inspraak|klacht|archief|begroting|reglement van orde|horeca|kinderopvang|verkeer|riool|water|"
    r"dienstverlening|aanwijzingsbesluit|restauratie|bedrijven|maatschappelijk vastgoed|subsidieplafond", re.I)
TITEL_WEL = re.compile(r"subsidie|regeling|lening|voucher|waardebon|tegoed|bijdrage|stimulering|isol|glas|fonds", re.I)


def titel_valt_af(titel, gemeente=""):
    """Stap 3a: alleen op de titel, zonder iets te downloaden.
    De gemeentenaam telt niet mee (anders valt bijv. alles van 'Waterland' af op 'water')."""
    if gemeente:
        titel = re.sub(re.escape(gemeente), " ", titel, flags=re.I)
    return bool(TITEL_NIET.search(titel)) or not TITEL_WEL.search(titel)


def is_vervallen(cid):
    """Stap 3b: de CVDR-pagina toont 'Geldend van ... t/m <datum>'. Ligt die datum in het verleden: overslaan."""
    try:
        r = requests.get(f"https://lokaleregelgeving.overheid.nl/{cid}", headers=UA, timeout=60)
        t = re.sub(r"<[^>]+>", " ", r.text)
        m = re.search(r"Geldend van\s+\d{2}-\d{2}-\d{4}\s+t/m\s+(heden|\d{2}-\d{2}-\d{4})", t)
        time.sleep(0.5)
        if not m or m.group(1) == "heden":
            return False
        d, mnd, j = m.group(1).split("-")
        return f"{j}-{mnd}-{d}" < VANDAAG
    except Exception:
        return False  # bij twijfel niet overslaan


def tekst_valt_af(tekst):
    """Stap 3c: moet echt over isolatie van woningen en geld gaan."""
    laag = tekst.lower()
    return not ("isol" in laag and ("woning" in laag or "eigenaar" in laag)
                and re.search(r"subsidie|lening|tegoed|voucher|waardebon|bijdrage", laag))


def is_relevant(titel, tekst):
    """Stap 3d: pas nu Gemini (Flash-Lite) vragen."""
    vraag = ("Beantwoord met alleen JA of NEE.\n"
             "JA alleen als het HOOFDDOEL van deze gemeentelijke regeling isolatie is van BESTAANDE woningen "
             "van particulieren: dak, zolder, gevel, spouwmuur, vloer/bodem of isolerend glas (HR++/triple).\n"
             "NEE als de regeling vooral gaat over aardgasvrij/aardgasvrij-klaar, warmtepompen, zonnepanelen, "
             "warmtenet, algemene verduurzaming of een brede duurzaamheidslening, ook als isolatie daar één van "
             "de opties is. Ook NEE bij monumenten-, bedrijven- of verhuurdersregelingen.\n\n"
             f"Titel: {titel}\n\nBegin van de tekst:\n{tekst[:6000]}")
    return llm("filter", vraag).strip().upper().startswith("JA")


# ---------- stap 4: voorwaarden extraheren ----------
def extraheer(tekst):
    antw = llm("extractie", PROMPT + "\n\n<regelingstekst>\n" + tekst + "\n</regelingstekst>", json_uit=True)
    return parse_json(antw)


TOETS = ["eigenaar_bewoner", "woz_max", "isolatiestaat", "bouwjaar_max", "woonoppervlak_max", "inkomen", "vve"]


def betrouwbaarheid(rec):
    if re.search(r"tegenstrijd|spreekt.*tegen", rec.get("opmerkingen") or "", re.I):
        return "middel"
    if not rec.get("bedrag") or not rec.get("looptijd_eind"):
        return "middel"
    return "hoog"


def status(rec):
    eind = rec.get("looptijd_eind")
    if eind and eind < VANDAAG:
        return "gesloten"
    return "open" if eind else "onbekend"


# ---------- wijzigingen ----------
VELDEN_LOG = ["bedrag", "looptijd_eind", "aanvragen", "inkomensgrens", "stapelbaar_isde", "status"]


def verschillen(oud, nieuw):
    uit = []
    for v in VELDEN_LOG:
        if (oud or {}).get(v) != nieuw.get(v):
            uit.append((v, (oud or {}).get(v), nieuw.get(v)))
    oc, nc = (oud or {}).get("criteria") or {}, nieuw.get("criteria") or {}
    for v in sorted(set(oc) | set(nc)):
        if oc.get(v) != nc.get(v):
            uit.append((f"criteria.{v}", oc.get(v), nc.get(v)))
    return uit


# ---------- hoofdprogramma ----------
def main():
    if "--alleen-overzicht" in sys.argv:  # alleen de sheet opnieuw maken uit de bestaande bestanden
        schrijf_overzicht(lees(OUT, []), lees(ZOEKSTATUS, {}).get("gemeenten", []), lees(DEKKING, {}))
        export_tios.schrijf(ROOT)
        return
    state = {} if FORCEER else lees(STATE, {})
    web_state = lees(WEB_STATE, {})
    oud = {r["id"]: r for r in lees(OUT, [])}
    oud_per_cvdr = {r["cvdr_id"]: r for r in oud.values() if r.get("cvdr_id")}
    dekking = lees(DEKKING, {})
    zoekstatus = {g["gemeente"]: g for g in lees(ZOEKSTATUS, {}).get("gemeenten", [])}
    nieuw, log = [], []
    limiet_op, uitgesteld, web_gedaan = False, 0, 0
    web_interval = CFG.get("web_zoeken_elke_dagen", 30)
    web_max = CFG.get("max_web_zoekacties_per_run", 25)
    nalees_max = CFG.get("max_web_nalezen_per_run", 20)       # web-regelingen zonder voorwaarden opnieuw lezen
    nalees_interval = CFG.get("web_nalezen_elke_dagen", 7)
    nalees_gedaan = 0
    gemeenten = gemeentelijst()
    namen = {g["naam"] for g in gemeenten}
    print(f"{len(gemeenten)} gemeenten")
    # Is de vorige run halverwege gestopt? Dan beginnen bij de gemeente waar hij bleef.
    volgende = None if ALLEEN else lees(VOORTGANG, {}).get("volgende")
    if volgende in namen:
        i = [g["naam"] for g in gemeenten].index(volgende)
        gemeenten = gemeenten[i:] + gemeenten[:i]
        print(f"Verder bij {volgende} (daar stopte de vorige run)")
    # PR-tekst van een openstaande Subsidie-update, voordat deze run hem overschrijft
    vorige_tekst = (LOG_LAST.read_text(encoding="utf-8")
                    if os.environ.get("VERDER_OP_OPEN_UPDATE") == "1" and LOG_LAST.exists() else "")
    gedaan = set()
    stand = {"volgende": None, "reden": None}
    resultaten = []   # (gemeente, symbool, tekst) voor de samenvatting

    def resultaat(naam, sym, tekst):
        print("::endgroup::")
        print(f"{sym} {naam}: {tekst}")
        resultaten.append((naam, sym, tekst))

    def pr_tekst():
        tekst = f"# Subsidie-update {VANDAAG}\n\n" + ("\n\n".join(log) if log else "Geen wijzigingen.") + "\n"
        wacht = sum(len(z["wacht_op_uitlezen"]) for z in zoekstatus.values())
        if wacht:
            tekst += (f"\n**Let op:** nog {wacht} regeling(en) in het CVDR wachten op uitlezen; "
                      "die volgen bij de volgende run(s).\n")
        if stand["volgende"]:
            tekst += (f"\n**Let op:** deze run is gestopt ({stand['reden']}) na {len(gedaan)} van {len(namen)} gemeenten. "
                      f"De volgende run gaat verder bij {stand['volgende']}.\n")
        # Gaat deze run verder op een openstaande Subsidie-update? Dan blijven de wijzigingen van de
        # eerdere runs in de PR-tekst staan (zonder hun oude "Let op"-regels).
        if vorige_tekst:
            eerder = re.sub(r"\n\*\*Let op:\*\*[^\n]*\n?", "\n", vorige_tekst)
            eerder = re.sub(r"^# Subsidie-update", "### Subsidie-update", eerder, flags=re.M)
            eerder = eerder.replace("## Eerdere runs in deze update (nog niet gemerged)", "")
            eerder = re.sub(r"\n{3,}", "\n\n", eerder).strip()
            tekst += "\n## Eerdere runs in deze update (nog niet gemerged)\n\n" + eerder + "\n"
            if len(tekst) > 60000:   # GitHub staat max. 65.536 tekens toe in een PR-tekst
                tekst = tekst[:60000] + "\n\n… (ingekort; alles staat in data/wijzigingen.md)\n"
        return tekst

    def opslaan(definitief=False):
        """Schrijft alles weg wat tot nu toe gedaan is. Gemeenten die nog niet aan bod kwamen
        houden hun vorige uitkomst. Kan op elk moment, dus ook tussentijds en bij een fout."""
        in_nieuw = {r["id"] for r in nieuw}
        lijst = nieuw + [r for r in oud.values() if r.get("handmatig")]
        lijst += [r for r in oud.values() if not r.get("handmatig") and r["gemeente"] not in gedaan
                  and r["id"] not in in_nieuw]
        lijst = [normaliseer(r) for r in {r["id"]: r for r in lijst}.values()]
        lijst.sort(key=lambda r: (r["gemeente"], r["naam"]))
        schrijf(OUT, lijst)
        schrijf(STATE, state)
        schrijf(WEB_STATE, web_state)
        schrijf(DEKKING, dekking)
        schrijf(ZOEKSTATUS, {"peildatum": VANDAAG,
                             "gemeenten": sorted(zoekstatus.values(), key=lambda x: x["gemeente"])})
        if not ALLEEN:
            schrijf(VOORTGANG, {"volgende": stand["volgende"], "datum": VANDAAG})
        tekst = pr_tekst()
        LOG_LAST.write_text(tekst, encoding="utf-8")
        if definitief:
            with LOG_ALL.open("a", encoding="utf-8") as f:
                f.write("\n" + tekst)
        return lijst

    def stop_signaal(signum, frame):
        raise KeyboardInterrupt(f"signaal {signum}")
    signal.signal(signal.SIGTERM, stop_signaal)
    laatst_bewaard = time.monotonic()

    try:
      for i_g, g in enumerate(gemeenten):
        if time.monotonic() - START > MAX_RUN_SEC:
            stand.update(volgende=g["naam"], reden="tijd van de run op")
            print(f"Tijd van de run op: stoppen. Volgende run begint bij {g['naam']}.")
            break
        naam = g["naam"]
        print(f"::group::{naam} (details)")
        try:
            treffers = zoek_cvdr(naam)
            if not treffers and "(" in naam:  # PDOK zegt "Hengelo (O)", het CVDR "Hengelo"
                treffers = zoek_cvdr(re.sub(r"\s*\(.*?\)", "", naam).strip())
        except Exception as e:
            print(f"  CVDR-zoekvraag mislukt ({e}); vorige uitkomst behouden")
            nieuw += [r for r in oud.values() if r["gemeente"] == naam and not r.get("handmatig")]
            resultaat(naam, "❌", "CVDR niet bereikbaar; vorige uitkomst blijft staan")
            continue
        print(f"  {len(treffers)} treffers in CVDR")
        relevant, wachtrij = 0, []
        tel = {"titel": 0, "vervallen": 0, "geen isolatie": 0, "gemini-filter": 0, "ongewijzigd": 0, "uitgelezen": 0}
        for cid, meta in treffers.items():
            st = state.get(cid, {})
            vorige = oud_per_cvdr.get(cid)
            zelfde_versie = not FORCEER and st.get("versie") == meta["versie"]

            # al eerder beoordeeld en niets veranderd: niets downloaden
            if zelfde_versie and st.get("skip"):
                tel[st["skip"]] = tel.get(st["skip"], 0) + 1
                continue
            if zelfde_versie and vorige:
                nieuw.append({**vorige, "peildatum": VANDAAG, "status": status(vorige)})
                relevant += 1
                tel["ongewijzigd"] += 1
                continue

            def overslaan(reden):
                state[cid] = {"versie": meta["versie"], "skip": reden}
                tel[reden] += 1

            def later():  # limiet bereikt: bewaren voor de volgende run
                nonlocal uitgesteld
                uitgesteld += 1
                wachtrij.append({"cvdr_id": cid, "titel": meta["titel"], "gewijzigd": meta["gewijzigd"],
                                 "bron_url": f"https://lokaleregelgeving.overheid.nl/{cid}/{meta['versie']}"})
                if vorige:
                    nieuw.append(vorige)

            if titel_valt_af(meta["titel"], naam):
                overslaan("titel"); continue
            if is_vervallen(cid):
                overslaan("vervallen"); continue
            try:
                tekst = haal_tekst(meta["xml_url"], f"https://lokaleregelgeving.overheid.nl/{cid}/{meta['versie']}")
            except Exception as e:
                print(f"  {cid}: tekst ophalen mislukt ({e})")
                later(); continue
            if tekst_valt_af(tekst):
                overslaan("geen isolatie"); continue
            tekst_hash = hashlib.sha256(tekst.encode()).hexdigest()
            if vorige and not FORCEER and st.get("hash") == tekst_hash:
                # alleen het versienummer is veranderd, de tekst niet: vorige uitkomst houden
                state[cid] = {"versie": meta["versie"], "hash": tekst_hash}
                nieuw.append({**vorige, "versie": meta["versie"], "peildatum": VANDAAG, "status": status(vorige),
                              "bron_url": f"https://lokaleregelgeving.overheid.nl/{cid}/{meta['versie']}"})
                relevant += 1
                tel["ongewijzigd"] += 1
                continue
            try:
                print(f"  {cid}: filter ({meta['titel'][:60]})")
                if not is_relevant(meta["titel"], tekst):
                    overslaan("gemini-filter"); continue
                print(f"  {cid} v{meta['versie']}: uitlezen")
                ext = extraheer(tekst)
            except LimietOp as e:
                print(f"  AI-BUDGET OF LIMIET OP ({e}). Run stopt; de volgende gaat hier verder.")
                limiet_op = limiet_reden(e)
                break
            except Exception as e:
                print(f"  {cid}: mislukt ({e})")
                later(); continue
            if not ext.get("relevant", True):
                overslaan("gemini-filter"); continue
            ext.pop("relevant", None)
            rec = {
                "id": vorige["id"] if vorige else f"{slug(naam)}-{cid.lower()}", "cvdr_id": cid, "versie": meta["versie"],
                "bron": "cvdr", "handmatig": False, "gecontroleerd": False,
                "gemeente": naam, "provincie": g.get("provincie"),
                **ext,
                "bron_url": f"https://lokaleregelgeving.overheid.nl/{cid}/{meta['versie']}",
                "datum_regelingstekst": meta.get("gewijzigd"), "peildatum": VANDAAG,
            }
            rec = normaliseer(rec)
            rec["naam"] = rec.get("naam") or meta["titel"]
            rec["status"] = status(rec)
            rec["betrouwbaarheid"] = betrouwbaarheid(rec)
            state[cid] = {"versie": meta["versie"], "hash": tekst_hash}
            relevant += 1
            tel["uitgelezen"] += 1
            nieuw.append(rec)
            diff = verschillen(vorige, rec)
            kop = f"**{naam} – {rec['naam']}** ({'nieuw' if not vorige else 'gewijzigd'}, {rec['bron_url']})"
            log.append(kop + "".join(f"\n  - {v}: {json.dumps(a, ensure_ascii=False)} → {json.dumps(b, ensure_ascii=False)}" for v, a, b in diff))

        print("  trechter: " + ", ".join(f"{k} {v}" for k, v in tel.items() if v))
        if limiet_op:  # budget/limiet op: deze gemeente is niet af, de volgende run begint hier
            stand.update(volgende=naam, reden=limiet_op)
            resultaat(naam, "🛑", f"{limiet_op}; de volgende run gaat hier verder")
            break

        # regelingen die niet meer gevonden worden: niet weggooien, wel markeren
        gezien = {r["cvdr_id"] for r in nieuw if r.get("cvdr_id")}
        for r in oud.values():
            if r["gemeente"] == naam and r.get("cvdr_id") and r["cvdr_id"] not in gezien and not r.get("handmatig"):
                r = {**r, "status": "onbekend", "gecontroleerd": False,
                     "opmerkingen": f"Niet meer gevonden in CVDR op {VANDAAG}: mogelijk ingetrokken of vervangen. " + (r.get("opmerkingen") or "")}
                nieuw.append(r)
                log.append(f"**{naam} – {r['naam']}**: niet meer gevonden in CVDR")

        # stap 5: CVDR helemaal afgehandeld en niets relevants? Dan op internet zoeken
        oud_web = [r for r in oud.values() if r["gemeente"] == naam and r.get("bron") == "web"]
        ws = web_state.get(naam, {})
        heeft_handmatig = any(r["gemeente"] == naam and r.get("handmatig") for r in oud.values())
        web_nodig = relevant == 0 and not wachtrij and not heeft_handmatig
        web_te_oud = not ws.get("datum") or (dt.date.fromisoformat(VANDAAG) - dt.date.fromisoformat(ws["datum"])).days >= web_interval
        web_uitkomst = None   # wat het zoeken op internet deze run opleverde
        if web_nodig and web_te_oud and not limiet_op and web_gedaan < web_max:
            try:
                print("  niets in CVDR: zoeken op internet")
                web = web_zoek(g)
                web_gedaan += 1
                web_state[naam] = {"datum": VANDAAG, "gevonden": len(web)}
                oude_ids = {r["id"] for r in oud_web}
                for r in web:
                    if r["id"] not in oude_ids:
                        log.append(f"**{naam} – {r['naam']}** (nieuw via AI-zoekactie op internet, {r['bron_url']})")
                nieuw += web
                print(f"  internet: {len(web)} regeling(en)")
                web_uitkomst = "gezocht"
            except LimietOp as e:
                print(f"  AI-BUDGET OF LIMIET OP bij zoeken op internet ({e}). Run stopt.")
                limiet_op = limiet_reden(e)
                nieuw += oud_web
                stand.update(volgende=naam, reden=limiet_op)
                resultaat(naam, "🛑", f"{limiet_op} bij zoeken op internet; de volgende run gaat hier verder")
                break
            except Exception as e:
                print(f"  zoeken op internet mislukt ({e})")
                nieuw += oud_web
                web_uitkomst = "mislukt"
        elif web_nodig:
            # vorige internetuitkomst blijft staan tot de volgende zoekactie; zonder voorwaarden? opnieuw lezen
            for r in oud_web:
                gelezen = r.get("voorwaarden_gelezen")
                te_lang = not gelezen or (dt.date.fromisoformat(VANDAAG) - dt.date.fromisoformat(gelezen)).days >= nalees_interval
                if heeft_voorwaarden(r) or not te_lang or limiet_op or nalees_gedaan >= nalees_max:
                    nieuw.append(r)
                    continue
                try:
                    print(f"  web: voorwaarden opnieuw lezen voor {r['naam'][:60]}")
                    nalees_gedaan += 1
                    ext, methode = lees_webregeling(r["naam"], naam, r["bron_url"])
                except LimietOp as e:
                    print(f"  AI-BUDGET OF LIMIET OP bij opnieuw lezen ({e}). Run stopt.")
                    limiet_op = limiet_reden(e)
                    nieuw.append(r)
                    continue
                if ext and not ext.get("relevant", True):
                    log.append(f"**{naam} – {r['naam']}**: bij opnieuw lezen geen isolatieregeling; verwijderd ({r['bron_url']})")
                    continue
                if heeft_voorwaarden(ext):
                    r = voeg_voorwaarden_toe(dict(r), ext, methode)
                    log.append(f"**{naam} – {r['naam']}**: voorwaarden uitgelezen "
                               f"({'van de bronpagina' if methode == 'pagina' else 'opgezocht door het taalmodel'}, {r['bron_url']})")
                else:
                    r = {**r, "voorwaarden_gelezen": VANDAAG}
                    print("  web: nog steeds geen voorwaarden gevonden")
                nieuw.append(r)
            if limiet_op:
                stand.update(volgende=naam, reden=limiet_op)
                resultaat(naam, "🛑", f"{limiet_op} bij opnieuw lezen; de volgende run gaat hier verder")
                break
        # heeft de gemeente inmiddels een CVDR-regeling, dan vervallen de internetresultaten

        webtreffers = sum(1 for r in nieuw if r["gemeente"] == naam and r.get("bron") == "web")
        dekking[naam] = {"datum": VANDAAG,
                         "bronnen_gecheckt": ["CVDR"] + (["internet (AI)"] if web_state.get(naam) and web_nodig else []),
                         "treffers": len(treffers), "relevante_regelingen": relevant + webtreffers,
                         "wacht_op_uitlezen": len(wachtrij)}
        zoekstatus[naam] = {"gemeente": naam, "provincie": g.get("provincie"), "cvdr_gecheckt": VANDAAG,
                            "wacht_op_uitlezen": wachtrij,
                            "internet_gezocht": web_state.get(naam, {}).get("datum") if web_nodig else None}
        regs = [r for r in nieuw if r["gemeente"] == naam and r.get("status") != "gesloten"]
        zonder = [r for r in regs if not heeft_voorwaarden(r)]
        web_regs = [r for r in regs if r.get("bron") == "web"]
        delen = []
        if tel["uitgelezen"]:
            delen.append(f"{tel['uitgelezen']} nieuw/gewijzigd uitgelezen")
        if tel["ongewijzigd"]:
            delen.append(f"{tel['ongewijzigd']} ongewijzigd")
        if web_regs:
            delen.append(f"{len(web_regs)} via internet (controleren)")
        uitleg = f" ({', '.join(delen)})" if delen else ""
        if web_uitkomst == "mislukt":
            resultaat(naam, "❌", "niets in CVDR en zoeken op internet mislukt")
        elif wachtrij:
            resultaat(naam, "⚠️", f"{len(wachtrij)} regeling(en) niet uitgelezen (fout bij ophalen of uitlezen), "
                                  f"volgt bij de volgende run" + (f"; wel gelukt: {len(regs)}" if regs else ""))
        elif regs and zonder:
            resultaat(naam, "⚠️", f"{len(regs)} open regeling(en), waarvan {len(zonder)} zonder voorwaarden{uitleg}")
        elif regs:
            resultaat(naam, "✅", f"voorwaarden opgehaald voor {len(regs)} open regeling(en){uitleg}")
        elif any(r["gemeente"] == naam for r in nieuw):
            resultaat(naam, "➖", "alleen gesloten regelingen")
        elif web_uitkomst == "gezocht":
            resultaat(naam, "➖", "geen regeling in CVDR, en op internet niets gevonden")
        else:
            resultaat(naam, "➖", "geen isolatieregeling gevonden")
        gedaan.add(naam)
        stand["volgende"] = gemeenten[i_g + 1]["naam"] if i_g + 1 < len(gemeenten) else None
        stand["reden"] = "onderbroken"
        if time.monotonic() - laatst_bewaard > BEWAAR_ELKE_SEC:
            opslaan()
            laatst_bewaard = time.monotonic()
            print(f"  (tussentijds opgeslagen: {len(gedaan)} gemeenten gedaan)")
      else:
        stand.update(volgende=None, reden=None)   # alle gemeenten gedaan: volgende keer weer vooraan
    except BaseException as e:
        # Crash, annuleren of signaal: bewaren wat er is, zodat de volgende run verder kan.
        print("::endgroup::")
        print(f"Run onderbroken ({type(e).__name__}: {e}). Opslaan wat er is.")
        if stand["volgende"] is None or stand["reden"] == "onderbroken":
            huidig = [g["naam"] for g in gemeenten if g["naam"] not in gedaan]
            stand.update(volgende=huidig[0] if huidig else None, reden=f"onderbroken: {type(e).__name__}")
        lijst = opslaan(definitief=True)
        try:
            schrijf_overzicht(lijst, lees(ZOEKSTATUS, {}).get("gemeenten", []), dekking)
            export_tios.schrijf(ROOT)
        except Exception as e2:
            print(f"Overzicht/export na onderbreking mislukt ({e2})")
        schrijf_samenvatting(resultaten, stand, len(namen))
        raise

    nieuw = opslaan(definitief=True)
    schrijf_samenvatting(resultaten, stand, len(namen))
    wacht = sum(len(z["wacht_op_uitlezen"]) for z in zoekstatus.values())
    print(f"Klaar: {len(nieuw)} regelingen, {len(log)} wijzigingen, {web_gedaan} zoekacties op internet, {wacht} wachten nog")
    schrijf_overzicht(nieuw, lees(ZOEKSTATUS, {}).get("gemeenten", []), dekking)
    export_tios.schrijf(ROOT)

    if "--vergelijk" in sys.argv:
        vergelijk(pathlib.Path(sys.argv[sys.argv.index("--vergelijk") + 1]), nieuw)


# ---------- overzicht in Excel ----------
def _eur(x):
    try:
        return f"€ {float(x):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(x)


def _tekst(v):
    if v is None or v == "" or v == [] or v == {}:
        return ""
    if isinstance(v, bool):
        return "ja" if v else "nee"
    if isinstance(v, list):
        return ", ".join(_tekst(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_tekst(x)}" for k, x in v.items() if _tekst(x))
    return str(v)


def _datum(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else _tekst(s)


def _bedrag(b):
    """Bedrag als tekst; het model geeft soms {max, eenheid, type} in plaats van een zin."""
    if isinstance(b, dict):
        delen = [f"max. {_eur(b['max'])}" if b.get("max") is not None else "",
                 f"min. {_eur(b['min'])}" if b.get("min") is not None else "",
                 f"{b['percentage']}%" if b.get("percentage") is not None else "",
                 _tekst({k: v for k, v in b.items() if k not in ("max", "min", "percentage", "eenheid", "type")})]
        return ", ".join(x for x in delen if x) or _tekst(b)
    return _tekst(b)


def rij_voor(r):
    """Eén regeling als leesbare rij (voorwaarden in gewone taal)."""
    c = r.get("criteria") or {}
    woz = ""
    if c.get("woz_max") is not None:
        woz = ("≤ " if c.get("woz_regel") == "lte" else "< ") + _eur(c["woz_max"])
        woz += f" (peildatum {c['woz_peildatum']})" if c.get("woz_peildatum") else ""
        woz += f". Uitzondering: {c['woz_uitzondering']}" if c.get("woz_uitzondering") else ""
    iso = c.get("isolatiestaat") or {}
    bouwjaar = " ".join(x for x in [f"vanaf {c['bouwjaar_min']}" if c.get("bouwjaar_min") else "",
                                    f"t/m {c['bouwjaar_max']}" if c.get("bouwjaar_max") else "",
                                    _tekst(c.get("bouwjaar_opmerking"))] if x)
    bron = "handmatig" if r.get("handmatig") else {"web": "internet (AI)", "wacht": "CVDR (wacht)"}.get(r.get("bron"), "CVDR")
    return {
        "Gemeente": r.get("gemeente"), "Provincie": r.get("provincie"), "Regeling": r.get("naam"),
        "Bron": bron, "Status": r.get("status"), "Gecontroleerd": "" if r.get("bron") == "wacht" else ("ja" if r.get("gecontroleerd") else "nee"),
        "Betrouwbaarheid": r.get("betrouwbaarheid"), "Bedrag": _bedrag(r.get("bedrag")),
        "Aanvragen t/m": _datum(r.get("looptijd_eind")), "Eigenaar-bewoner": _tekst(c.get("eigenaar_bewoner")),
        "WOZ": woz, "Isolatiestaat / energielabel": _tekst(iso.get("omschrijving")) if isinstance(iso, dict) else _tekst(iso),
        "Bouwjaar": bouwjaar, "Max. woonoppervlak": _tekst(c.get("woonoppervlak_max")),
        "Inkomen": {"vereist": "laag inkomen verplicht", "bonus": "hoger bedrag bij laag inkomen"}.get(c.get("inkomen"), _tekst(c.get("inkomen"))),
        "Inkomensgrens": _tekst(r.get("inkomensgrens")),
        "VvE / appartement": " ".join(x for x in [_tekst(c.get("vve")), _tekst(c.get("vve_opmerking"))] if x),
        "Maatregelen": _tekst(r.get("maatregelen")), "Technische eisen": _tekst(r.get("technische_eisen")),
        "Eisen uitvoerder": _tekst(r.get("uitvoerder_eisen")), "Aanvragen": _tekst(r.get("aanvragen")),
        "Stapelbaar met ISDE": _tekst(r.get("stapelbaar_isde")), "Budget": _tekst(r.get("budgetstatus")),
        "Opmerkingen": _tekst(r.get("opmerkingen")), "Peildatum": _datum(r.get("peildatum")),
        "Link": r.get("bron_url") or "",
    }


def schrijf_overzicht(regelingen, zoekstatus, dekking):
    """overzicht_voorwaarden.xlsx: blad Regelingen (één rij per regeling) en blad Gemeenten (alle gemeenten).
    Alleen om te lezen: wijzigingen in dit bestand worden niet teruggelezen (dat gaat via regelingen.json)."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl ontbreekt: overzicht_voorwaarden.xlsx niet gemaakt (pip install openpyxl)")
        return
    kop_stijl, kop_vul = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F5D50")
    geel = PatternFill("solid", fgColor="FFF2CC")

    def blad(ws, rijen, breedtes, link_kolom=None):
        koppen = list(rijen[0].keys()) if rijen else []
        ws.append(koppen)
        for cel in ws[1]:
            cel.font, cel.fill = kop_stijl, kop_vul
        for rij in rijen:
            ws.append([rij[k] for k in koppen])
        for i, k in enumerate(koppen, 1):
            ws.column_dimensions[get_column_letter(i)].width = breedtes.get(k, 18)
        for regel in ws.iter_rows(min_row=2):
            for cel in regel:
                cel.alignment = Alignment(wrap_text=True, vertical="top")
            if link_kolom and regel[koppen.index(link_kolom)].value:
                cel = regel[koppen.index(link_kolom)]
                cel.hyperlink, cel.font = cel.value, Font(color="0563C1", underline="single")
        ws.freeze_panes = "B2"
        if rijen:
            ws.auto_filter.ref = ws.dimensions

    wb = Workbook()
    ws = wb.active
    ws.title = "Regelingen"
    wachtend = [{"gemeente": z["gemeente"], "provincie": z.get("provincie"), "naam": w["titel"], "bron": "wacht",
                 "status": "nog niet uitgelezen", "bron_url": w["bron_url"],
                 "opmerkingen": "Gevonden in het CVDR, voorwaarden nog niet uitgelezen (volgt bij een volgende run)."}
                for z in zoekstatus for w in (z.get("wacht_op_uitlezen") or [])
                if not titel_valt_af(w["titel"], z["gemeente"])]
    rijen = [rij_voor(r) for r in sorted(regelingen + wachtend, key=lambda r: (r.get("gemeente") or "", r.get("naam") or ""))]
    blad(ws, rijen, {"Gemeente": 16, "Regeling": 40, "Bedrag": 35, "WOZ": 24, "Isolatiestaat / energielabel": 35,
                     "Maatregelen": 35, "Technische eisen": 35, "Eisen uitvoerder": 30, "Aanvragen": 30,
                     "Opmerkingen": 50, "Link": 45, "Inkomensgrens": 25, "VvE / appartement": 25}, "Link")
    grijs = PatternFill("solid", fgColor="EDEDED")
    for regel, r in zip(ws.iter_rows(min_row=2), rijen):
        vul = {"internet (AI)": geel, "CVDR (wacht)": grijs}.get(r["Bron"])
        for cel in regel if vul else []:
            cel.fill = vul

    per_gemeente = {}
    for r in regelingen:
        per_gemeente.setdefault(r.get("gemeente"), []).append(r)
    status = {z["gemeente"]: z for z in zoekstatus}
    gemeenten = sorted(set(per_gemeente) | set(status) | set(dekking))
    g_rijen = []
    for g in gemeenten:
        regs, z, d = per_gemeente.get(g, []), status.get(g, {}), dekking.get(g, {})
        open_ = [r for r in regs if r.get("status") != "gesloten"]
        wacht = len(z.get("wacht_op_uitlezen") or [])
        if open_:
            conclusie = "regeling gevonden"
        elif regs:
            conclusie = "alleen gesloten regeling(en)"
        elif wacht:
            conclusie = "wacht op uitlezen"
        else:
            conclusie = "geen regeling gevonden"
        g_rijen.append({
            "Gemeente": g, "Provincie": z.get("provincie") or (regs[0].get("provincie") if regs else ""),
            "Conclusie": conclusie, "Regelingen (open)": len(open_), "Regelingen (totaal)": len(regs),
            "Waarvan via internet (AI)": sum(1 for r in regs if r.get("bron") == "web"),
            "Wacht op uitlezen": wacht, "Treffers in CVDR": d.get("treffers", ""),
            "CVDR gecheckt": _datum(z.get("cvdr_gecheckt") or d.get("datum")),
            "Internet gezocht": _datum(z.get("internet_gezocht")),
            "Namen regelingen": ", ".join([r.get("naam") or "" for r in regs]
                                          + [f"{w['titel']} (nog niet uitgelezen)" for w in z.get("wacht_op_uitlezen") or []]),
        })
    blad(wb.create_sheet("Gemeenten"), g_rijen, {"Gemeente": 20, "Conclusie": 26, "Namen regelingen": 80})

    uitleg = wb.create_sheet("Uitleg")
    for regel in [
        ["Overzicht isolatieregelingen", f"bijgewerkt {_datum(VANDAAG)}"],
        ["Regelingen", "Eén rij per regeling met de voorwaarden. Geel = gevonden via AI op internet: altijd de link controleren. "
                       "Grijs = gevonden in het CVDR maar nog niet uitgelezen."],
        ["Gemeenten", "Alle gemeenten met de conclusie, ook als er niets is gevonden."],
        ["Let op", "Dit bestand wordt bij elke run opnieuw gemaakt. Aanpassingen hierin gaan verloren; "
                   "'gecontroleerd' zet je in regelingen.json."],
    ]:
        uitleg.append(regel)
    uitleg.column_dimensions["A"].width, uitleg.column_dimensions["B"].width = 18, 110
    uitleg["A1"].font = Font(bold=True, size=13)
    wb.save(OVERZICHT)
    print(f"Overzicht geschreven: {OVERZICHT.name} ({len(rijen)} regelingen, {len(g_rijen)} gemeenten)")


def vergelijk(baseline_pad, resultaat):
    """Zet de modeluitkomst naast de handmatige controle (pilot)."""
    base = {r["cvdr_id"]: r for r in lees(ROOT / baseline_pad, []) if r.get("cvdr_id")}
    res = {r["cvdr_id"]: r for r in resultaat if r.get("cvdr_id")}
    regels = [f"# Vergelijking model vs. handmatig ({VANDAAG})\n"]
    for cid, b in base.items():
        r = res.get(cid)
        if not r or (r.get("opmerkingen") or "").startswith("Niet meer gevonden"):
            regels.append(f"## {b['gemeente']} – {cid}\nNIET GEVONDEN door de scraper.\n")
            continue
        d = verschillen(b, r)
        regels.append(f"## {b['gemeente']} – {cid}\n" + ("Alles gelijk.\n" if not d else
                      "".join(f"- {v}: handmatig {json.dumps(a, ensure_ascii=False)} | model {json.dumps(m, ensure_ascii=False)}\n" for v, a, m in d)))
    extra = [c for c in res if c not in base]
    if extra:
        regels.append("## Extra gevonden door de scraper\n" + "".join(f"- {res[c]['gemeente']}: {res[c]['naam']} ({c})\n" for c in extra))
    (DATA / "vergelijking.md").write_text("\n".join(regels), encoding="utf-8")
    print("Vergelijking geschreven naar data/vergelijking.md")


if __name__ == "__main__":
    main()
