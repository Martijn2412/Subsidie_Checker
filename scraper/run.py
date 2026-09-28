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
"""
import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import sys
import time

import requests

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
ALLEEN = [n.strip().lower() for n in sys.argv[sys.argv.index("--alleen") + 1].split(",")] if "--alleen" in sys.argv else None

if PROVIDER == "gemini":
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                          http_options=types.HttpOptions(timeout=180_000))  # max. 3 min per aanroep
else:
    from anthropic import Anthropic
    client = Anthropic()  # leest ANTHROPIC_API_KEY


# ---------- hulpfuncties ----------
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


def llm(taak, tekst, json_uit=False, zoeken=False):
    """Stuurt tekst naar het taalmodel. Bij drukte of limiet: eerst even wachten,
    dan het reservemodel proberen, en anders LimietOp opgooien.
    zoeken=True: het model mag op internet zoeken (Google bij Gemini, web search bij Claude)."""
    if time.monotonic() - START > MAX_AI_SEC:
        raise LimietOp("tijdslimiet van deze run bereikt")
    modellen = [MODELLEN[taak]] + ([MODELLEN[taak + "_reserve"]] if MODELLEN.get(taak + "_reserve") else [])
    laatste_fout = None
    for model in modellen:
        for poging in range(3):
            try:
                time.sleep(PAUZE)
                if PROVIDER == "gemini":
                    cfg = types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=TOKENS[taak],
                        # JSON-modus gaat niet samen met Google zoeken; dan zelf de JSON uit de tekst halen
                        response_mime_type="application/json" if json_uit and not zoeken else "text/plain",
                        tools=[types.Tool(google_search=types.GoogleSearch())] if zoeken else None,
                    )
                    r = client.models.generate_content(model=model, contents=tekst, config=cfg)
                    if not r.text:
                        raise RuntimeError("leeg antwoord")
                    return r.text
                extra = {"tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]} if zoeken else {}
                r = client.messages.create(model=model, max_tokens=min(TOKENS[taak], 8000),
                                           messages=[{"role": "user", "content": tekst}], **extra)
                return "".join(b.text for b in r.content if b.type == "text")
            except Exception as e:
                fout = str(e)
                laatste_fout = fout
                limiet = "429" in fout or "RESOURCE_EXHAUSTED" in fout or "rate_limit" in fout
                if limiet and poging >= 1:
                    print(f"  {model}: limiet bereikt, ander model proberen")
                    break
                wacht = 40 if limiet else 20 * (poging + 1)
                print(f"  {model}: fout ({fout[:110]}), wacht {wacht}s, poging {poging + 1}/3")
                time.sleep(wacht)
    if laatste_fout and ("429" in laatste_fout or "RESOURCE_EXHAUSTED" in laatste_fout or "rate_limit" in laatste_fout):
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
    for woord in trefwoorden or CFG["trefwoorden"]:
        params = {
            "version": "1.2", "operation": "searchRetrieve", "x-connection": "cvdr",
            "query": f'dcterms.creator="{gemeente}" AND keyword all "{woord}"',
            "startRecord": 1, "maximumRecords": CFG["max_resultaten_per_zoekvraag"],
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


def haal_webpagina(url):
    r = requests.get(url, headers=BROWSER, timeout=60)
    r.raise_for_status()
    t = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", r.text)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()[:60_000]


def web_zoek(g):
    """Laat het taalmodel op internet zoeken en leest gevonden pagina's uit. Geeft een lijst records."""
    naam = g["naam"]
    antw = parse_json(llm("zoeken", WEB_PROMPT.format(g=naam), json_uit=True, zoeken=True))
    recs = []
    for w in (antw.get("regelingen") or [])[:3]:
        url, titel = (w.get("url") or "").strip(), (w.get("naam") or "").strip()
        if not url.startswith("http") or not titel:
            continue
        rec = {
            "id": f"{slug(naam)}-web-{slug(titel)[:50]}", "cvdr_id": None, "bron": "web",
            "handmatig": False, "gecontroleerd": False,
            "gemeente": naam, "provincie": g.get("provincie"), "naam": titel,
            "bron_url": url, "peildatum": VANDAAG,
        }
        try:
            tekst = haal_webpagina(url)
            ext = extraheer(tekst) if len(tekst) > 300 else {}
        except LimietOp:
            raise
        except Exception as e:
            print(f"  web: {url} niet uit te lezen ({e})")
            ext = {}
        if ext and not ext.get("relevant", True):
            continue
        ext.pop("relevant", None)
        rec.update({k: v for k, v in ext.items() if v is not None})
        rec["naam"] = ext.get("naam") or titel
        rec["opmerkingen"] = ("Gevonden via AI-zoekactie op internet, niet in het CVDR. Controleer de bronpagina. "
                              + (w.get("samenvatting") or "") + " " + (ext.get("opmerkingen") or "")).strip()
        rec["status"] = status(rec)
        rec["betrouwbaarheid"] = "laag"
        recs.append(rec)
    return recs


# ---------- stap 2: tekst ophalen ----------
def haal_tekst(xml_url):
    r = requests.get(xml_url, headers=UA, timeout=60)
    r.raise_for_status()
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
    r"inspraak|klacht|archief|begroting|reglement van orde|horeca|kinderopvang|verkeer|riool|water", re.I)
TITEL_WEL = re.compile(r"subsidie|regeling|lening|voucher|waardebon|tegoed|bijdrage|stimulering|isol|glas|fonds", re.I)


def titel_valt_af(titel):
    """Stap 3a: alleen op de titel, zonder iets te downloaden."""
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
    gemeenten = gemeentelijst()
    namen = {g["naam"] for g in gemeenten}
    print(f"{len(gemeenten)} gemeenten")

    for g in gemeenten:
        naam = g["naam"]
        print(f"== {naam}")
        try:
            treffers = zoek_cvdr(naam)
        except Exception as e:
            print(f"  CVDR-zoekvraag mislukt ({e}); vorige uitkomst behouden")
            nieuw += [r for r in oud.values() if r["gemeente"] == naam and not r.get("handmatig")]
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

            if titel_valt_af(meta["titel"]):
                overslaan("titel"); continue
            if limiet_op:  # geen taalmodel meer: niet eens downloaden
                later(); continue
            if is_vervallen(cid):
                overslaan("vervallen"); continue
            try:
                tekst = haal_tekst(meta["xml_url"])
            except Exception as e:
                print(f"  {cid}: tekst ophalen mislukt ({e})")
                later(); continue
            if tekst_valt_af(tekst):
                overslaan("geen isolatie"); continue
            try:
                print(f"  {cid}: filter ({meta['titel'][:60]})")
                if not is_relevant(meta["titel"], tekst):
                    overslaan("gemini-filter"); continue
                print(f"  {cid} v{meta['versie']}: uitlezen")
                ext = extraheer(tekst)
            except LimietOp as e:
                print(f"  LIMIET BEREIKT ({e}). Rest volgt bij de volgende run.")
                limiet_op = True
                later(); continue
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
            rec["naam"] = rec.get("naam") or meta["titel"]
            rec["status"] = status(rec)
            rec["betrouwbaarheid"] = betrouwbaarheid(rec)
            state[cid] = {"versie": meta["versie"], "hash": hashlib.sha256(tekst.encode()).hexdigest()}
            relevant += 1
            tel["uitgelezen"] += 1
            nieuw.append(rec)
            diff = verschillen(vorige, rec)
            kop = f"**{naam} – {rec['naam']}** ({'nieuw' if not vorige else 'gewijzigd'}, {rec['bron_url']})"
            log.append(kop + "".join(f"\n  - {v}: {json.dumps(a, ensure_ascii=False)} → {json.dumps(b, ensure_ascii=False)}" for v, a, b in diff))

        print("  trechter: " + ", ".join(f"{k} {v}" for k, v in tel.items() if v))

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
            except LimietOp as e:
                print(f"  LIMIET BEREIKT bij zoeken op internet ({e})")
                limiet_op = True
                nieuw += oud_web
            except Exception as e:
                print(f"  zoeken op internet mislukt ({e})")
                nieuw += oud_web
        elif web_nodig:
            nieuw += oud_web  # vorige internetuitkomst blijft staan tot de volgende zoekactie
        # heeft de gemeente inmiddels een CVDR-regeling, dan vervallen de internetresultaten

        webtreffers = sum(1 for r in nieuw if r["gemeente"] == naam and r.get("bron") == "web")
        dekking[naam] = {"datum": VANDAAG,
                         "bronnen_gecheckt": ["CVDR"] + (["internet (AI)"] if web_state.get(naam) and web_nodig else []),
                         "treffers": len(treffers), "relevante_regelingen": relevant + webtreffers,
                         "wacht_op_uitlezen": len(wachtrij)}
        zoekstatus[naam] = {"gemeente": naam, "provincie": g.get("provincie"), "cvdr_gecheckt": VANDAAG,
                            "wacht_op_uitlezen": wachtrij,
                            "internet_gezocht": web_state.get(naam, {}).get("datum") if web_nodig else None}

    # handmatige regelingen blijven altijd staan; gemeenten die deze run niet aan bod kwamen ook
    nieuw += [r for r in oud.values() if r.get("handmatig")]
    nieuw += [r for r in oud.values() if not r.get("handmatig") and r["gemeente"] not in namen]
    nieuw = list({r["id"]: r for r in nieuw}.values())
    nieuw.sort(key=lambda r: (r["gemeente"], r["naam"]))

    schrijf(OUT, nieuw)
    schrijf(STATE, state)
    schrijf(WEB_STATE, web_state)
    schrijf(DEKKING, dekking)
    schrijf(ZOEKSTATUS, {"peildatum": VANDAAG,
                         "gemeenten": sorted(zoekstatus.values(), key=lambda x: x["gemeente"])})
    tekst = f"# Subsidie-update {VANDAAG}\n\n" + ("\n\n".join(log) if log else "Geen wijzigingen.") + "\n"
    wacht = sum(len(z["wacht_op_uitlezen"]) for z in zoekstatus.values())
    if limiet_op or wacht:
        tekst += (f"\n**Let op:** limiet van het taalmodel bereikt. Nog {wacht} regeling(en) in het CVDR wachten op "
                  "uitlezen; die volgen bij de volgende run(s).\n")
    LOG_LAST.write_text(tekst, encoding="utf-8")
    with LOG_ALL.open("a", encoding="utf-8") as f:
        f.write("\n" + tekst)
    print(f"Klaar: {len(nieuw)} regelingen, {len(log)} wijzigingen, {web_gedaan} zoekacties op internet, {wacht} wachten nog")

    if "--vergelijk" in sys.argv:
        vergelijk(pathlib.Path(sys.argv[sys.argv.index("--vergelijk") + 1]), nieuw)


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
