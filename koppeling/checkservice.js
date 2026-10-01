/* Checkservice voor TIOS: een kleine webservice op de eigen server (Ubuntu).
   Geen extra pakketten nodig, alleen Node.js 18 of nieuwer.

   Starten:   node koppeling/checkservice.js
   Aanroepen: GET http://localhost:8085/check?postcode=2511AB&huisnummer=12&energielabel=E&woz=325000&eigenaar_bewoner=ja
   Status:    GET http://localhost:8085/status

   - Met postcode + huisnummer zoekt de service zelf de gemeente op bij PDOK (gratis
     adresdienst van de overheid, geen sleutel). De gemeentenaam is dan precies die uit
     de subsidielijst; "Den Haag" of een woonplaats geeft dus geen misser meer.
     Bouwjaar en woonoppervlak komen uit het BAG, als TIOS die niet zelf meestuurt.
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
const VERVERS_MS = 24 * 60 * 60 * 1000;
const OUD_NA_DAGEN = 14;
const PDOK_TIMEOUT_MS = 3000;

let data = null;
let laatstOpgehaald = null;
let laatsteFout = null;

/* ---------------- adres opzoeken (zelfde bronnen als de checkpagina) ---------------- */
const normPc = s => String(s || "").toUpperCase().replace(/\s+/g, "");
const normHn = s => String(s || "").trim().replace(/\D/g, "");
const normTv = s => String(s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const getal = x => (x == null || x === "" || isNaN(Number(x))) ? null : Number(x);
const toevoegingVan = d => normTv((d.huisletter || "") + (d.huisnummertoevoeging || d.toevoeging || ""));

async function haalJson(url) {
  const r = await fetch(url, {signal: AbortSignal.timeout(PDOK_TIMEOUT_MS), headers: {Accept: "application/json"}});
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
async function zoekLocatie(pc, hn) {
  const q = new URLSearchParams({q: `${pc} ${hn}`, rows: "50",
    fl: "gemeentenaam,woonplaatsnaam,huisnummer,huisletter,huisnummertoevoeging,postcode,adresseerbaarobject_id"});
  q.append("fq", "type:adres"); q.append("fq", "postcode:" + pc);
  const j = await haalJson("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?" + q);
  return ((j.response && j.response.docs) || []).filter(d => String(d.huisnummer) === String(hn));
}
async function zoekBag(pc, hn) {
  const f = `<Filter><And><PropertyIsEqualTo><PropertyName>postcode</PropertyName><Literal>${pc}</Literal></PropertyIsEqualTo>` +
            `<PropertyIsEqualTo><PropertyName>huisnummer</PropertyName><Literal>${hn}</Literal></PropertyIsEqualTo></And></Filter>`;
  const q = new URLSearchParams({service: "WFS", version: "2.0.0", request: "GetFeature", typeName: "bag:verblijfsobject",
                                 outputFormat: "json", count: "50", filter: f});
  const j = await haalJson("https://service.pdok.nl/lv/bag/wfs/v2_0?" + q);
  return (j.features || []).map(x => x.properties || {});
}

/* Postcode + huisnummer → {gemeente, woonplaats, bouwjaar, woonoppervlak} of {fout}.
   Een postcode + huisnummer ligt altijd in één gemeente; de toevoeging is alleen nodig
   om bij meerdere woningen op hetzelfde nummer het juiste bouwjaar/oppervlak te kiezen. */
const adresCache = new Map();
async function zoekAdres(postcode, huisnummer, toevoeging) {
  const pc = normPc(postcode), hn = normHn(huisnummer), tv = normTv(toevoeging);
  if (!/^\d{4}[A-Z]{2}$/.test(pc) || !hn) return {fout: "ongeldige postcode of huisnummer"};
  const sleutel = `${pc}|${hn}|${tv}`;
  if (adresCache.has(sleutel)) return adresCache.get(sleutel);

  const [loc, bag] = await Promise.allSettled([zoekLocatie(pc, hn), zoekBag(pc, hn)]);
  if (loc.status === "rejected") return {fout: "adresdienst PDOK niet bereikbaar"};
  const lijst = loc.value;
  if (!lijst.length) return {fout: "adres niet gevonden"};
  const keuze = lijst.find(d => toevoegingVan(d) === tv) || (lijst.length === 1 || !tv ? lijst[0] : null) || lijst[0];
  const eenduidig = lijst.length === 1 || lijst.some(d => toevoegingVan(d) === tv);

  const uit = {gemeente: keuze.gemeentenaam || null, woonplaats: keuze.woonplaatsnaam || null, bouwjaar: null, woonoppervlak: null};
  if (bag.status === "fulfilled" && eenduidig) {
    const vbo = bag.value.find(v => v.identificatie && v.identificatie === keuze.adresseerbaarobject_id)
             || bag.value.find(v => toevoegingVan(v) === toevoegingVan(keuze));
    if (vbo) { uit.bouwjaar = getal(vbo.bouwjaar); uit.woonoppervlak = getal(vbo.oppervlakte); }
  }
  if (adresCache.size > 5000) adresCache.clear();
  adresCache.set(sleutel, uit);
  return uit;
}

/* ---------------- de check zelf ---------------- */
async function beoordeel(params) {
  const klant = Object.assign({}, params);
  delete klant.sleutel; delete klant.postcode; delete klant.huisnummer; delete klant.toevoeging;
  let adres = null, waarschuwing = null;

  if (PDOK_AAN && params.postcode && params.huisnummer) {
    adres = await zoekAdres(params.postcode, params.huisnummer, params.toevoeging);
    if (adres.fout) {
      waarschuwing = `Gemeente niet opgezocht: ${adres.fout}.`;
    } else {
      klant.gemeente = adres.gemeente;   // PDOK wint: die naam staat precies zo in de lijst
      if (klant.bouwjaar == null && adres.bouwjaar != null) klant.bouwjaar = adres.bouwjaar;
      if (klant.woonoppervlak == null && adres.woonoppervlak != null) klant.woonoppervlak = adres.woonoppervlak;
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
