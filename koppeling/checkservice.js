/* Checkservice voor TIOS: een kleine webservice op de eigen server (Ubuntu).
   Geen extra pakketten nodig, alleen Node.js 18 of nieuwer.

   Starten:   node koppeling/checkservice.js
   Aanroepen: GET http://localhost:8085/check?postcode=2511AB&huisnummer=12&energielabel=E&bouwjaar=1931&woonoppervlak=95&woz=325000&eigenaar_bewoner=ja
   Status:    GET http://localhost:8085/status

   - Met postcode + huisnummer zoekt de service zelf de gemeente op bij PDOK (gratis
     adresdienst van de overheid, geen sleutel). De gemeentenaam is dan precies die uit
     de subsidielijst; "Den Haag" of een woonplaats geeft dus geen misser meer.
     Bouwjaar, woonoppervlak en de rest stuurt TIOS zelf mee.
     Alleen postcode + huisnummer gaan naar PDOK; geen naam of andere klantgegevens.
   - Zonder postcode werkt ?gemeente=... nog steeds (dan moet de naam wel kloppen).
   - Haalt één keer per dag (en bij het starten) tios/subsidies.json op en bewaart de
     laatste goede versie op schijf. Lukt ophalen niet, dan rekent hij verder met die versie.
   - De rekenregels staan in subsidiecheck.js: hetzelfde bestand als de checkpagina.

   Instellen via omgevingsvariabelen (allemaal optioneel):
     POORT      (standaard 8085)
     ADRES      (standaard 127.0.0.1: alleen bereikbaar vanaf de server zelf)
     DATA_URL   (standaard het GitHub Pages-adres van tios/subsidies.json)
     CACHE      (standaard koppeling/subsidies-cache.json)
     SLEUTEL    (optioneel: dan moet de aanroep ?sleutel=... of header X-Sleutel meesturen)
     PDOK       (zet op "uit" om nooit adressen op te zoeken)
     EIGENAAR_BEWONER_STANDAARD  (standaard "ja": alle leads van Takkenkamp zijn eigenaar-bewoner.
                Stuurt TIOS eigenaar_bewoner wel mee, dan telt dat. Zet op "" om het niet aan te nemen.)
*/
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");
const SC = require("../subsidiecheck.js");

const POORT = Number(process.env.POORT || 8085);
const ADRES = process.env.ADRES || "127.0.0.1";
const DATA_URL = process.env.DATA_URL || "https://martijn2412.github.io/Subsidie_Checker/tios/subsidies.json";
const CACHE = process.env.CACHE || path.join(__dirname, "subsidies-cache.json");
const SLEUTEL = process.env.SLEUTEL || "";
const PDOK_AAN = process.env.PDOK !== "uit";
const EIGENAAR_BEWONER_STANDAARD = process.env.EIGENAAR_BEWONER_STANDAARD ?? "ja";
const VERVERS_MS = 24 * 60 * 60 * 1000;
const OUD_NA_DAGEN = 14;
const PDOK_TIMEOUT_MS = 3000;

let data = null;
let laatstOpgehaald = null;
let laatsteFout = null;

/* ---------------- adres opzoeken (zelfde bronnen als de checkpagina) ---------------- */
const normPc = s => String(s || "").toUpperCase().replace(/\s+/g, "");
const normHn = s => String(s || "").trim().replace(/\D/g, "");

async function haalJson(url) {
  const r = await fetch(url, {signal: AbortSignal.timeout(PDOK_TIMEOUT_MS), headers: {Accept: "application/json"}});
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
async function zoekLocatie(pc, hn) {
  const q = new URLSearchParams({q: `${pc} ${hn}`, rows: "50",
    fl: "gemeentenaam,woonplaatsnaam,huisnummer,postcode"});
  q.append("fq", "type:adres"); q.append("fq", "postcode:" + pc);
  const j = await haalJson("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?" + q);
  return ((j.response && j.response.docs) || []).filter(d => String(d.huisnummer) === String(hn));
}

/* Postcode + huisnummer → {gemeente, woonplaats} of {fout}.
   Een postcode + huisnummer ligt altijd in één gemeente, dus de toevoeging is niet nodig. */
const adresCache = new Map();
async function zoekAdres(postcode, huisnummer) {
  const pc = normPc(postcode), hn = normHn(huisnummer);
  if (!/^\d{4}[A-Z]{2}$/.test(pc) || !hn) return {fout: "ongeldige postcode of huisnummer"};
  const sleutel = `${pc}|${hn}`;
  if (adresCache.has(sleutel)) return adresCache.get(sleutel);
  let lijst;
  try { lijst = await zoekLocatie(pc, hn); } catch (e) { return {fout: "adresdienst PDOK niet bereikbaar"}; }
  if (!lijst.length) return {fout: "adres niet gevonden"};
  const uit = {gemeente: lijst[0].gemeentenaam || null, woonplaats: lijst[0].woonplaatsnaam || null};
  if (adresCache.size > 5000) adresCache.clear();
  adresCache.set(sleutel, uit);
  return uit;
}

/* ---------------- de check zelf ---------------- */
async function beoordeel(params) {
  const klant = Object.assign({}, params);
  delete klant.sleutel; delete klant.postcode; delete klant.huisnummer; delete klant.toevoeging;
  if (klant.eigenaar_bewoner == null || klant.eigenaar_bewoner === "") klant.eigenaar_bewoner = EIGENAAR_BEWONER_STANDAARD;
  let adres = null, waarschuwing = null;

  if (PDOK_AAN && params.postcode && params.huisnummer) {
    adres = await zoekAdres(params.postcode, params.huisnummer);
    if (adres.fout) {
      waarschuwing = `Gemeente niet opgezocht: ${adres.fout}.`;
    } else {
      klant.gemeente = adres.gemeente;   // PDOK wint: die naam staat precies zo in de lijst
    }
  }

  const uit = SC.check(klant, data.regelingen, {zoekstatus: data});
  if (uit.uitkomst === "onbekend" && !waarschuwing) waarschuwing = "Geen gemeente of postcode meegegeven.";
  const oud = dagenOud();
  if (oud !== null && oud > OUD_NA_DAGEN) waarschuwing = [waarschuwing, `Subsidiedata is ${oud} dagen oud.`].filter(Boolean).join(" ");
  return {
    uitkomst: uit.uitkomst,
    tekst: uit.tekst,
    ontbreekt: uit.ontbreekt,
    gemeente: uit.gemeente || null,
    adres: adres && !adres.fout ? adres : null,
    regelingen: uit.regelingen.map(r => ({naam: r.naam, bedrag: r.bedrag, uitkomst: r.uitkomst,
                                           aanvragen_tm: r.aanvragen_tm, bron_url: r.bron_url})),
    data_van: data.bijgewerkt,
    waarschuwing,
  };
}

/* ---------------- data ophalen en bewaren ---------------- */
function laadCache() {
  try { data = JSON.parse(fs.readFileSync(CACHE, "utf8")); } catch (e) { /* nog geen cache */ }
}

async function ververs() {
  try {
    const r = await fetch(DATA_URL, {signal: AbortSignal.timeout(30000)});
    if (!r.ok) throw new Error("HTTP " + r.status);
    const nieuw = await r.json();
    if (!Array.isArray(nieuw.regelingen) || !nieuw.gemeenten) throw new Error("onverwacht formaat");
    data = nieuw;
    laatstOpgehaald = new Date().toISOString();
    laatsteFout = null;
    fs.writeFileSync(CACHE + ".tmp", JSON.stringify(nieuw));
    fs.renameSync(CACHE + ".tmp", CACHE);
  } catch (e) {
    laatsteFout = String(e.message || e);
    console.error("Ophalen mislukt, verder met laatste versie:", laatsteFout);
  }
}

function dagenOud() {
  if (!data || !data.bijgewerkt) return null;
  return Math.floor((Date.now() - Date.parse(data.bijgewerkt)) / 86400000);
}

/* ---------------- webservice ---------------- */
function antwoord(res, code, body) {
  res.writeHead(code, {"Content-Type": "application/json; charset=utf-8"});
  res.end(JSON.stringify(body));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (SLEUTEL && url.searchParams.get("sleutel") !== SLEUTEL && req.headers["x-sleutel"] !== SLEUTEL)
    return antwoord(res, 401, {fout: "sleutel ontbreekt of klopt niet"});

  if (url.pathname === "/status") {
    const oud = dagenOud();
    return antwoord(res, data ? 200 : 503, {
      ok: !!data && oud !== null && oud <= OUD_NA_DAGEN,
      data_van: data ? data.bijgewerkt : null, dagen_oud: oud,
      regelingen: data ? data.regelingen.length : 0,
      laatst_opgehaald: laatstOpgehaald, laatste_fout: laatsteFout,
      adres_opzoeken: PDOK_AAN,
    });
  }

  if (url.pathname === "/check") {
    if (!data) return antwoord(res, 503, {fout: "nog geen subsidiedata geladen"});
    try {
      return antwoord(res, 200, await beoordeel(Object.fromEntries(url.searchParams)));
    } catch (e) {
      return antwoord(res, 500, {fout: String(e.message || e)});
    }
  }

  antwoord(res, 404, {fout: "gebruik /check of /status"});
});

if (require.main === module) {
  laadCache();
  ververs().finally(() => {
    setInterval(ververs, VERVERS_MS);
    server.listen(POORT, ADRES, () => console.log(`Checkservice luistert op http://${ADRES}:${POORT}`));
  });
}

// Voor de tests
module.exports = {zoekAdres, beoordeel, _zetData: d => { data = d; }, _adresCache: adresCache};
