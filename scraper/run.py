"""
Subsidie-scraper: haalt gemeentelijke isolatieregelingen op uit het CVDR
(lokaleregelgeving.overheid.nl), laat een taalmodel de voorwaarden in vaste
velden zetten en schrijft regelingen.json voor de checkpagina.

Draait in GitHub Actions. Taalmodel kies je in scraper/config.json ("provider":
"gemini" of "claude"). Lokaal testen: pip install requests google-genai anthropic
  python scraper/run.py                       normale run
  python scraper/run.py --forceer             alles opnieuw extraheren
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
SRU = "https://zoekservice.overheid.nl/sru/Search"
UA = {"User-Agent": "Takkenkamp-subsidiecheck/0.1 (interne tool)"}
VANDAAG = dt.date.today().isoformat()
DATA.mkdir(parents=True, exist_ok=True)  # map data/ aanmaken als die ontbreekt
FORCEER = "--forceer" in sys.argv
PROVIDER = CFG.get("provider", "gemini")
MODELLEN = CFG["modellen"][PROVIDER]
PAUZE = CFG.get("pauze_tussen_aanroepen_sec", 7)  # gratis Gemini: max. enkele verzoeken per minuut

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


def llm(taak, tekst, json_uit=False):
    """Stuurt tekst naar het taalmodel. Bij drukte of limiet: eerst even wachten,
    dan het reservemodel proberen, en anders LimietOp opgooien."""
    modellen = [MODELLEN[taak]] + ([MODELLEN[taak + "_reserve"]] if MODELLEN.get(taak + "_reserve") else [])
    laatste_fout = None
    for model in modellen:
        for poging in range(3):
            try:
                time.sleep(PAUZE)
                if PROVIDER == "gemini":
                    cfg = types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=16000 if taak == "extractie" else 1000,
                        response_mime_type="application/json" if json_uit else "text/plain",
                    )
                    r = client.models.generate_content(model=model, contents=tekst, config=cfg)
                    if not r.text:
                        raise RuntimeError("leeg antwoord")
                    return r.text
                r = client.messages.create(model=model, max_tokens=8000 if taak == "extractie" else 10,
                                           messages=[{"role": "user", "content": tekst}])
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
    return json.loads(tekst)


# ---------- stap 1: zoeken in het CVDR ----------
def zoek_cvdr(gemeente):
    """Geeft {cvdr_id: {versie, titel, xml_url, gewijzigd}} met alleen de hoogste versie."""
    gevonden = {}
    for woord in CFG["trefwoorden"]:
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
    oud = {r["id"]: r for r in lees(OUT, [])}
    oud_per_cvdr = {r["cvdr_id"]: r for r in oud.values() if r.get("cvdr_id")}
    dekking = lees(DEKKING, {})
    nieuw, log = [], []
    limiet_op, uitgesteld = False, 0

    for g in CFG["gemeenten"]:
        naam = g["naam"]
        print(f"== {naam}")
        treffers = zoek_cvdr(naam)
        print(f"  {len(treffers)} treffers in CVDR")
        relevant = 0
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

            if titel_valt_af(meta["titel"]):
                overslaan("titel"); continue
            if is_vervallen(cid):
                overslaan("vervallen"); continue
            try:
                tekst = haal_tekst(meta["xml_url"])
            except Exception as e:
                print(f"  {cid}: tekst ophalen mislukt ({e})")
                if vorige:
                    nieuw.append(vorige)
                continue
            if tekst_valt_af(tekst):
                overslaan("geen isolatie"); continue
            if limiet_op:  # limiet al bereikt: bewaren voor de volgende run
                uitgesteld += 1
                if vorige:
                    nieuw.append(vorige)
                continue
            try:
                print(f"  {cid}: Gemini-filter ({meta['titel'][:60]})")
                if not is_relevant(meta["titel"], tekst):
                    overslaan("gemini-filter"); continue
                print(f"  {cid} v{meta['versie']}: uitlezen")
                ext = extraheer(tekst)
            except LimietOp as e:
                print(f"  LIMIET BEREIKT ({e}). Resterende regelingen volgen bij de volgende run.")
                limiet_op, uitgesteld = True, uitgesteld + 1
                if vorige:
                    nieuw.append(vorige)
                continue
            except Exception as e:
                print(f"  {cid}: mislukt ({e})")
                if vorige:
                    nieuw.append(vorige)
                continue
            if not ext.get("relevant", True):
                overslaan("gemini-filter"); continue
            ext.pop("relevant", None)
            rec = {
                "id": vorige["id"] if vorige else f"{slug(naam)}-{cid.lower()}", "cvdr_id": cid, "versie": meta["versie"],
                "handmatig": False, "gecontroleerd": False,
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
        dekking[naam] = {"datum": VANDAAG, "bronnen_gecheckt": ["CVDR"], "treffers": len(treffers), "relevante_regelingen": relevant}

        # regelingen die niet meer gevonden worden: niet weggooien, wel markeren
        gezien = {r["cvdr_id"] for r in nieuw if r.get("cvdr_id")}
        for r in oud.values():
            if r["gemeente"] == naam and r.get("cvdr_id") and r["cvdr_id"] not in gezien and not r.get("handmatig"):
                r = {**r, "status": "onbekend", "gecontroleerd": False,
                     "opmerkingen": f"Niet meer gevonden in CVDR op {VANDAAG}: mogelijk ingetrokken of vervangen. " + (r.get("opmerkingen") or "")}
                nieuw.append(r)
                log.append(f"**{naam} – {r['naam']}**: niet meer gevonden in CVDR")

    # handmatige regelingen blijven altijd staan
    nieuw += [r for r in oud.values() if r.get("handmatig")]
    nieuw.sort(key=lambda r: (r["gemeente"], r["naam"]))

    schrijf(OUT, nieuw)
    schrijf(STATE, state)
    schrijf(DEKKING, dekking)
    tekst = f"# Subsidie-update {VANDAAG}\n\n" + ("\n\n".join(log) if log else "Geen wijzigingen.") + "\n"
    if uitgesteld:
        tekst += f"\n**Let op:** limiet van het taalmodel bereikt. {uitgesteld} regeling(en) nog niet verwerkt; die volgen bij de volgende run.\n"
    LOG_LAST.write_text(tekst, encoding="utf-8")
    with LOG_ALL.open("a", encoding="utf-8") as f:
        f.write("\n" + tekst)
    print(f"Klaar: {len(nieuw)} regelingen, {len(log)} wijzigingen")

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
