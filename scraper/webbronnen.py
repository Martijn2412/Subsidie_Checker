"""
Regelingen vinden buiten het CVDR, per gemeente:
  1. de eigen gemeentesite (adres uit het Register van Overheidsorganisaties; sitemap of korte rondgang),
  2. partners die regelingen voor gemeenten uitvoeren (energieloketten, bouwloketten),
  3. links op gevonden pagina's naar voorwaarden, pdf's of het loket van een partner,
  4. (als 1-3 niets opleveren) een AI-zoekactie met Google, waarbij de echte Google-bronnen gebruikt worden.

Stap 1-3 kosten geen AI. Alle gevonden pagina's van een gemeente gaan daarna samen in één
AI-aanroep (zie run.py), en alleen als de tekst sinds de vorige keer veranderd is.

Alles in dit bestand is los te testen: het internet gaat via haal() en het taalmodel via een
meegegeven functie, zodat de tests ze kunnen nadoen.
"""
import difflib
import gzip
import hashlib
import html
import io
import re
import time
import unicodedata
import urllib.parse

import requests

BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36", "Accept-Language": "nl-NL,nl;q=0.9"}
ROO = "https://organisaties.overheid.nl/archive/exportOO_gemeenten.xml"
MAX_TEKST_PAGINA = 40_000      # tekens per pagina
MAX_TEKST_GEMEENTE = 140_000   # tekens die per gemeente naar het taalmodel gaan
PAUZE = 0.3                    # netjes blijven tegen de websites

# ---------- teksten herkennen ----------
ISOLATIE = re.compile(r"isol|spouwmuur|hr\+\+|triple glas|dubbel glas|isolerend glas|kierdicht", re.I)
GELD = re.compile(r"subsidie|lening|voucher|waardebon|tegoed|korting|vergoeding|bijdrage|cashback|"
                  r"gratis|financier|regeling", re.I)
WONING = re.compile(r"woning|huis|eigenaar|bewoner|inwoner", re.I)

# Woorden in een webadres die op een regeling voor isolatie wijzen (hoger = sterker)
URL_STERK = re.compile(r"isol|subsid|lening|voucher|waardebon|verduurzam|energiebespa|bespaar|spouw|"
                       r"energieloket|woonlasten|energiecoach|energie-?advies|tegoed", re.I)
URL_ZWAK = re.compile(r"duurzaam|energie|wonen|woning|klimaat|glas|dak|vloer", re.I)
URL_NIET = re.compile(r"vacature|raadsinformatie|vergader|agenda|bekendmaking|ondernem|bedrijv|"
                      r"monument|evenement|sport|cultuur|jeugd|onderwijs|afval|parkeren|login|"
                      r"\.(jpg|jpeg|png|gif|svg|zip|docx?|xlsx?|mp4|ics)$", re.I)
LINK_DETAIL = re.compile(r"voorwaarden|regels|reglement|spelregels|aanvra|subsidieregel|"
                         r"veelgestelde|meer informatie|lees meer|bekijk|\.pdf\b", re.I)


def norm(s):
    """Naam vergelijken: kleine letters, geen accenten, geen haakjes of 'gemeente'."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bgemeente\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s):
    """'Bergen op Zoom' -> 'bergen-op-zoom', "'s-Hertogenbosch" -> 's-hertogenbosch'."""
    return norm(s).replace(" ", "-")


def is_regelingpagina(tekst):
    """Gratis filter: gaat deze tekst over geld voor isolatie van een woning?"""
    return bool(ISOLATIE.search(tekst) and GELD.search(tekst) and WONING.search(tekst))


def score_tekst(tekst):
    t = tekst.lower()
    return (len(ISOLATIE.findall(t)) * 2 + min(len(GELD.findall(t)), 20)
            + (5 if re.search(r"subsidie\w* voor (het )?isol|isolatiesubsidie|isolatievoucher", t) else 0))


def score_url(url, tekst_link=""):
    pad = urllib.parse.unquote(urllib.parse.urlparse(url).path + " " + tekst_link)
    if URL_NIET.search(pad):
        return 0
    return 3 * len(set(m.lower() for m in URL_STERK.findall(pad))) + len(set(m.lower() for m in URL_ZWAK.findall(pad)))


# ---------- internet ----------
def haal(url, timeout=30):
    """GET met browserkop. Los te vervangen in de tests."""
    r = requests.get(url, headers=BROWSER, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def pdf_naar_tekst(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        lezer = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in lezer.pages[:40])
    except Exception:
        return ""


def html_naar_tekst(ruw):
    """Leesbare tekst van een webpagina. Staat er een <main>, dan alleen dat deel (geen menu's)."""
    m = re.search(r"(?is)<main\b[^>]*>(.*)</main>", ruw)
    t = m.group(1) if m and len(m.group(1)) > 500 else ruw
    t = re.sub(r"(?is)<(script|style|nav|footer|header|noscript|svg|form)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|tr|div)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def links_van(ruw, basis):
    """[(absolute url, linktekst)] van een HTML-pagina, zonder ankers en dubbelen."""
    uit, gezien = [], set()
    for href, tekst in re.findall(r'(?is)<a\b[^>]*?href\s*=\s*["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', ruw):
        url = urllib.parse.urljoin(basis, html.unescape(href.strip()))
        if not url.startswith("http") or url in gezien:
            continue
        gezien.add(url)
        uit.append((url, re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", tekst))).strip()))
    return uit


def lees_pagina(url):
    """Haalt een pagina of pdf op. Geeft {url, tekst, links, pdf} of None als het niet lukt."""
    try:
        r = haal(url)
    except Exception as e:
        if not re.search(r"\b(404|410)\b", str(e)):   # niet-bestaande pagina's van sjablonen zijn normaal
            print(f"    niet bereikbaar: {url} ({str(e)[:80]})")
        return None
    soort = (r.headers.get("content-type") or "").lower()
    if "pdf" in soort or r.url.lower().endswith(".pdf"):
        return {"url": r.url, "tekst": pdf_naar_tekst(r.content)[:MAX_TEKST_PAGINA], "links": [], "pdf": True}
    if "html" not in soort and "xml" not in soort and soort:
        return None
    ruw = r.text
    titel = re.search(r"(?is)<title[^>]*>(.*?)</title>", ruw)
    tekst = html_naar_tekst(ruw)
    if titel:
        tekst = html.unescape(re.sub(r"\s+", " ", titel.group(1))).strip() + "\n" + tekst
    return {"url": r.url, "tekst": tekst[:MAX_TEKST_PAGINA], "links": links_van(ruw, r.url), "pdf": False}


# ---------- 1. gemeentesite ----------
def lees_roo(xml):
    """Uit de export van het Register van Overheidsorganisaties: {genormaliseerde naam: website}."""
    sites = {}
    for blok in re.split(r"<(?:\w+:)?organisatie\b", xml)[1:]:
        naam = re.search(r"<(?:\w+:)?naam>([^<]+)</", blok)
        if not naam or not re.match(r"\s*gemeente\s", html.unescape(naam.group(1)), re.I):
            continue
        urls = re.findall(r"<(?:\w+:)?url>\s*(https?://[^<\s]+)\s*</", blok) or \
            re.findall(r">\s*(https?://(?:www\.)?[a-z0-9.-]+\.(?:nl|frl)/?)\s*<", blok, re.I)
        urls = [u for u in urls if "overheid.nl" not in u]
        if urls:
            sites.setdefault(norm(html.unescape(naam.group(1))), urls[0].rstrip("/"))
    return sites


def haal_roo():
    try:
        sites = lees_roo(haal(ROO, timeout=120).text)
        print(f"Register van Overheidsorganisaties: {len(sites)} gemeentesites")
        return sites
    except Exception as e:
        print(f"Register van Overheidsorganisaties niet bereikbaar ({e})")
        return {}


def gok_sites(naam):
    a = norm(naam).replace(" ", "")
    b = slug(naam)
    kandidaten = [f"https://www.{a}.nl", f"https://www.gemeente{a}.nl", f"https://www.{b}.nl", f"https://{a}.nl"]
    return list(dict.fromkeys(kandidaten))


def vind_site(naam, roo, vast=None):
    """Webadres van de gemeentesite: vaste lijst (config) > register > gokken (alleen als hij bestaat)."""
    for bron in (vast or {}, roo):
        for k, v in bron.items():
            if norm(k) == norm(naam):
                return v.rstrip("/")
    for url in gok_sites(naam):
        try:
            r = haal(url, timeout=15)
            if re.search(r"gemeente", r.text[:200_000], re.I):
                return r.url.rstrip("/")
        except Exception:
            continue
    return None


def sitemap_urls(site, max_bestanden=15):
    """Alle webadressen uit de sitemap(s) van een site. Leeg als er geen sitemap is."""
    host = urllib.parse.urlparse(site).netloc
    te_doen = []
    try:
        robots = haal(site + "/robots.txt", timeout=15).text
        te_doen += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    except Exception:
        pass
    te_doen += [site + "/sitemap.xml", site + "/sitemap_index.xml"]
    urls, gedaan = [], set()
    while te_doen and len(gedaan) < max_bestanden:
        sm = te_doen.pop(0)
        if sm in gedaan:
            continue
        gedaan.add(sm)
        try:
            r = haal(sm, timeout=30)
        except Exception:
            continue
        data = r.content
        if sm.endswith(".gz") or data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except OSError:
                continue
        tekst = data.decode("utf-8", "ignore")
        if "<urlset" not in tekst and "<sitemapindex" not in tekst:
            continue
        locs = [html.unescape(x.strip()) for x in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", tekst)]
        if "<sitemapindex" in tekst:
            # eerst de sitemaps die op pagina's lijken, niet die van nieuws of afbeeldingen
            locs.sort(key=lambda u: (bool(re.search(r"image|video|news|nieuws|agenda", u, re.I)), u))
            te_doen = locs + te_doen
        else:
            urls += [u for u in locs if urllib.parse.urlparse(u).netloc.endswith(host.replace("www.", ""))]
        time.sleep(PAUZE)
        if urls and "<sitemapindex" not in tekst and len(urls) > 20000:
            break
    return list(dict.fromkeys(urls))


def rondgang(site, max_paginas=12):
    """Geen sitemap? Dan vanaf de homepage de links volgen die op subsidies of isolatie lijken."""
    host = urllib.parse.urlparse(site).netloc
    gevonden, te_doen, gedaan, gelukt = {}, [(site, "")], set(), 0
    while te_doen and len(gedaan) < max_paginas:
        te_doen.sort(key=lambda x: -score_url(*x))
        url, _ = te_doen.pop(0)
        if url in gedaan:
            continue
        gedaan.add(url)
        p = lees_pagina(url)
        time.sleep(PAUZE)
        if not p:
            continue
        gelukt += 1
        for link, tekst in p["links"]:
            if urllib.parse.urlparse(link).netloc.replace("www.", "") != host.replace("www.", "") or link in gedaan:
                continue
            s = score_url(link, tekst)
            if s >= 1:
                gevonden[link] = max(gevonden.get(link, 0), s)
                te_doen.append((link, tekst))
    return gevonden, gelukt   # {url: score (adres + linktekst)}, aantal bekeken pagina's


def kandidaten_gemeentesite(site, max_kandidaten=12):
    """De webadressen op de gemeentesite die het meest op een isolatieregeling lijken.
    Geeft (urls, 'sitemap'/'rondgang', aantal bekeken adressen)."""
    urls = sitemap_urls(site)
    if urls:
        bron, gescoord = "sitemap", [(score_url(u), u) for u in urls]
    else:
        gevonden, bekeken = rondgang(site)
        bron, gescoord = "rondgang", [(sc, u) for u, sc in gevonden.items()]
    gescoord.sort(key=lambda x: (-x[0], len(x[1])))
    aantal = len(urls) if urls else bekeken
    return [u for sc, u in gescoord if sc >= 3][:max_kandidaten], bron, aantal


# ---------- 2. partners ----------
class Partners:
    """Partners met een lijst van gemeenten (index) en/of vaste webadressen per gemeente (sjablonen).
    De lijstpagina's worden één keer per run opgehaald."""

    def __init__(self, config):
        self.config = config or []
        self._index = {}

    def index(self, partner):
        naam = partner["naam"]
        if naam not in self._index:
            links = []
            for url in partner.get("index", []):
                p = lees_pagina(url)
                if p:
                    links += p["links"]
                time.sleep(PAUZE)
            self._index[naam] = links
        return self._index[naam]

    def kandidaten(self, gemeente):
        """[(partnernaam, url)] die bij deze gemeente horen."""
        uit, g, s = [], norm(gemeente), slug(gemeente)
        for p in self.config:
            for link, tekst in self.index(p):
                pad = norm(urllib.parse.unquote(urllib.parse.urlparse(link).netloc + " " + urllib.parse.urlparse(link).path))
                if g and (norm(tekst) == g or re.search(rf"(^| ){re.escape(g)}( |$)", pad)):
                    uit.append((p["naam"], link))
            for sjabloon in p.get("sjablonen", []):
                uit.append((p["naam"], sjabloon.format(slug=s, naam=urllib.parse.quote(gemeente))))
        return list(dict.fromkeys(uit))


def hoort_bij_gemeente(pagina, gemeente):
    """Staat de gemeente echt op deze pagina (en is het geen doorverwijzing naar een algemene homepage)?"""
    g = norm(gemeente)
    return bool(g) and (re.search(rf"\b{re.escape(g)}\b", norm(pagina["tekst"][:20000])) is not None
                        or slug(gemeente) in pagina["url"].lower())


# ---------- 3. links volgen ----------
def detail_links(pagina, max_links=4):
    """Links op een relevante pagina naar voorwaarden, pdf's of het loket dat de regeling uitvoert."""
    kies = []
    for url, tekst in pagina["links"]:
        if url.rstrip("/") == pagina["url"].rstrip("/") or URL_NIET.search(urllib.parse.urlparse(url).path):
            continue
        s = (5 if LINK_DETAIL.search(tekst + " " + url) else 0) + score_url(url, tekst)
        if re.search(r"isol|subsid|voucher|loket", tekst + " " + url, re.I) and s >= 5:
            kies.append((s, url))
    kies.sort(key=lambda x: -x[0])
    return [u for _, u in kies[:max_links]]


# ---------- 4. AI-zoekactie ----------
ZOEK_PROMPT = """Zoek op internet welke regelingen er op dit moment zijn voor inwoners van de gemeente {g}
(provincie {p}) om hun BESTAANDE koopwoning te ISOLEREN (dak, zolder, gevel, spouwmuur, vloer/bodem,
isolerend glas): subsidie, voucher, waardebon, korting, gratis isolatieactie of lening.
Kijk op de website van de gemeente {g} én bij partners die dit voor gemeenten uitvoeren, zoals
Regionaal Energieloket, Duurzaam Bouwloket, WoonWijzerWinkel, het lokale energieloket of energiecoöperatie,
en SVn (duurzaamheidslening). Negeer landelijke regelingen (ISDE, Warmtefonds) en regelingen van andere gemeenten.

Antwoord met ALLEEN deze JSON, zonder uitleg:
{{"regelingen": [{{"naam": "...", "url": "directe link naar de pagina over deze regeling",
  "uitvoerder": "gemeente of naam van de partner", "samenvatting": "1-3 zinnen"}}]}}
Niets gevonden? Antwoord {{"regelingen": []}}. Verzin nooit een regeling of link."""


def ai_zoek(gemeente, provincie, zoek_functie, parse_json):
    """zoek_functie(prompt) -> (tekst, [bron-urls]). Geeft [(url, uitvoerder)] die echt bestaan:
    eerst de links uit het antwoord, aangevuld met de bronnen die Google meegaf."""
    antwoord = zoek_functie(ZOEK_PROMPT.format(g=gemeente, p=provincie or "onbekend"))
    if antwoord is None:   # zoeken kan nu niet (bijv. tegoed op)
        return None
    tekst, bronnen = antwoord
    try:
        antw = parse_json(tekst)
    except Exception:
        antw = {}
    uit = [((w.get("url") or "").strip(), (w.get("uitvoerder") or "AI-zoekactie").strip())
           for w in (antw.get("regelingen") or []) if isinstance(w, dict)]
    uit = [(u, b) for u, b in uit if u.startswith("http")]
    uit += [(u, "AI-zoekactie (Google-bron)") for u in bronnen]
    return list(dict.fromkeys(uit))


# ---------- alles samen per gemeente ----------
def verzamel(gemeente, provincie, site, partners, zoek_functie=None, parse_json=None, ai_altijd=False,
             max_paginas=6):
    """Zoekt op de gemeentesite en bij partners (en zo nodig met AI) naar pagina's over isolatieregelingen.
    Geeft {"paginas": [{url, tekst, bron}], "verslag": {...}}. Het taalmodel wordt alleen gebruikt
    voor de AI-zoekactie, en alleen als zoek_functie is meegegeven."""
    verslag = {"site": site, "site_bron": None, "site_urls": 0, "kandidaten": 0, "partners": [],
               "ai_gezocht": False, "paginas": []}
    kandidaten = []   # (bron, url)
    if site:
        try:
            urls, verslag["site_bron"], verslag["site_urls"] = kandidaten_gemeentesite(site)
            kandidaten += [("gemeentesite", u) for u in urls]
        except Exception as e:
            print(f"    gemeentesite {site}: {e}")
    if partners:
        kandidaten += [(f"partner: {naam}", u) for naam, u in partners.kandidaten(gemeente)]
    verslag["kandidaten"] = len(kandidaten)

    def bekijk(lijst):
        gevonden = []
        for bron, url in lijst:
            p = lees_pagina(url)
            time.sleep(PAUZE)
            if not p or len(p["tekst"]) < 200 or not is_regelingpagina(p["tekst"]):
                continue
            if bron.startswith("partner") and not hoort_bij_gemeente(p, gemeente):
                continue
            p["bron"] = bron
            p["score"] = score_tekst(p["tekst"])
            gevonden.append(p)
        return gevonden

    paginas = bekijk(kandidaten)
    gevonden_ai = ai_zoek(gemeente, provincie, zoek_functie, parse_json) if zoek_functie and (ai_altijd or not paginas) else None
    if gevonden_ai is not None:
        verslag["ai_gezocht"] = True
        gezien = {p["url"] for p in paginas}
        extra = [(b if b.startswith("AI") else f"AI-zoekactie: {b}", u)
                 for u, b in gevonden_ai if u not in gezien]
        extra = [(b, u) for b, u in extra
                 if "lokaleregelgeving.overheid.nl" not in u and "officiele-overheidspublicaties" not in u]
        paginas += bekijk(extra[:8])

    # dubbele pagina's (zelfde eindadres na doorverwijzing) eruit; beste eerst
    uniek = {}
    for p in sorted(paginas, key=lambda p: -p["score"]):
        uniek.setdefault(p["url"].rstrip("/"), p)
    paginas = list(uniek.values())[:max_paginas]

    # links volgen naar voorwaarden / pdf / loket
    gedaan = {p["url"].rstrip("/") for p in paginas}
    for p in list(paginas):
        extra = []
        for url in detail_links(p):
            if url.rstrip("/") in gedaan:
                continue
            gedaan.add(url.rstrip("/"))
            d = lees_pagina(url)
            time.sleep(PAUZE)
            if d and len(d["tekst"]) > 50 and ISOLATIE.search(d["tekst"]):
                extra.append(f"\n--- Doorgelinkt vanaf deze pagina: {d['url']} ---\n{d['tekst'][:20000]}")
        p["tekst"] = (p["tekst"] + "".join(extra))[:MAX_TEKST_PAGINA * 2]
    if paginas:
        verslag["partners"] = sorted({p["bron"].split(": ", 1)[1] for p in paginas if p["bron"].startswith("partner")})
    verslag["paginas"] = [{"url": p["url"], "bron": p["bron"]} for p in paginas]
    return {"paginas": paginas, "verslag": verslag}


def samengevoegd(paginas):
    """Eén tekst voor het taalmodel, met per pagina een kop met het webadres."""
    delen, totaal = [], 0
    for p in paginas:
        stuk = f"\n\n=== Pagina: {p['url']} (bron: {p['bron']}) ===\n{p['tekst']}"
        if totaal + len(stuk) > MAX_TEKST_GEMEENTE:
            stuk = stuk[:max(0, MAX_TEKST_GEMEENTE - totaal)]
        delen.append(stuk)
        totaal += len(stuk)
        if totaal >= MAX_TEKST_GEMEENTE:
            break
    return "".join(delen).strip()


def tekst_hash(paginas):
    """Vingerafdruk van de inhoud; datums en tijden tellen niet mee (die veranderen vaak zonder reden)."""
    t = " ".join(p["url"] + " " + p["tekst"] for p in sorted(paginas, key=lambda p: p["url"]))
    t = re.sub(r"\b\d{1,2}[-/ ]\w{1,9}[-/ ]\d{2,4}\b|\b\d{1,2}:\d{2}\b", " ", t)
    return hashlib.sha256(re.sub(r"\s+", " ", t).encode()).hexdigest()


# ---------- bewijs controleren ----------
def _woorden(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = s.replace("euro", " ").replace("eur", " ")
    return re.findall(r"[a-z]+|\d+", re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", s))


def controleer_bewijs(rec, tekst):
    """Staat elk 'bewijs'-zinsdeel echt in de brontekst? Geeft {"gecontroleerd": n, "niet_gevonden": [velden]}.
    Een zinsdeel telt als gevonden als het letterlijk voorkomt, of als 85% van de woorden in dezelfde
    volgorde in de tekst staat (het model verandert soms een leesteken of hoofdletter)."""
    bewijs = rec.get("bewijs") if isinstance(rec.get("bewijs"), dict) else {}
    tekst_w = _woorden(tekst)
    tekst_s = " " + " ".join(tekst_w) + " "
    niet = []
    for veld, zin in bewijs.items():
        w = _woorden(zin)
        if not w:
            continue
        if " " + " ".join(w) + " " in tekst_s:
            continue
        m = difflib.SequenceMatcher(None, tekst_w, w, autojunk=False)
        if sum(b.size for b in m.get_matching_blocks()) / len(w) < 0.85:
            niet.append(veld)
    return {"gecontroleerd": len(bewijs), "niet_gevonden": niet}


# ---------- dubbele regelingen ----------
def kern(naam, gemeente=""):
    n = norm(naam)
    for w in [norm(gemeente), "subsidieregeling", "subsidie", "regeling", "gemeente", "de", "het", "voor", "van"]:
        if w:
            n = re.sub(rf"\b{re.escape(w)}\b", " ", n)
    n = re.sub(r"\b(19|20)\d{2}\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def lijkt_op(a, b, gemeente=""):
    ka, kb = kern(a, gemeente), kern(b, gemeente)
    if not ka or not kb:
        return False
    return ka == kb or difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.8
