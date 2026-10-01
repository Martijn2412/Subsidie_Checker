/* Checkservice voor TIOS: een kleine webservice op de eigen server (Ubuntu).
   Geen extra pakketten nodig, alleen Node.js 18 of nieuwer.

   Starten:   node koppeling/checkservice.js
   Aanroepen: GET http://localhost:8085/check?gemeente=Arnhem&energielabel=E&woz=325000&eigenaar_bewoner=ja
   Status:    GET http://localhost:8085/status

   - Haalt één keer per dag (en bij het starten) tios/subsidies.json op en bewaart de
     laatste goede versie op schijf. De lijst verandert hooguit één keer per dag.
     Lukt ophalen niet, dan rekent hij verder met die laatste versie.
   - Klantgegevens blijven op de server: alleen de (openbare) regelingen komen van buiten.
   - De rekenregels staan in subsidiecheck.js: hetzelfde bestand als de checkpagina.

   Instellen via omgevingsvariabelen (allemaal optioneel):
     POORT      (standaard 8085)
     ADRES      (standaard 127.0.0.1: alleen bereikbaar vanaf de server zelf)
     DATA_URL   (standaard het GitHub Pages-adres van tios/subsidies.json)
     CACHE      (standaard koppeling/subsidies-cache.json)
     SLEUTEL    (optioneel: dan moet de aanroep ?sleutel=... of header X-Sleutel meesturen)
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
const VERVERS_MS = 24 * 60 * 60 * 1000;
const OUD_NA_DAGEN = 14;

let data = null;
let laatstOpgehaald = null;
let laatsteFout = null;

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

function antwoord(res, code, body) {
  res.writeHead(code, {"Content-Type": "application/json; charset=utf-8"});
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
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
    });
  }

  if (url.pathname === "/check") {
    if (!data) return antwoord(res, 503, {fout: "nog geen subsidiedata geladen"});
    const klant = Object.fromEntries(url.searchParams);
    delete klant.sleutel;
    const uit = SC.check(klant, data.regelingen, {zoekstatus: data});
    const oud = dagenOud();
    return antwoord(res, 200, {
      uitkomst: uit.uitkomst,
      tekst: uit.tekst,
      ontbreekt: uit.ontbreekt,
      regelingen: uit.regelingen.map(r => ({naam: r.naam, bedrag: r.bedrag, uitkomst: r.uitkomst,
                                             aanvragen_tm: r.aanvragen_tm, bron_url: r.bron_url})),
      data_van: data.bijgewerkt,
      waarschuwing: oud !== null && oud > OUD_NA_DAGEN ? `Subsidiedata is ${oud} dagen oud.` : null,
    });
  }

  antwoord(res, 404, {fout: "gebruik /check of /status"});
});

laadCache();
ververs().finally(() => {
  setInterval(ververs, VERVERS_MS);
  server.listen(POORT, ADRES, () => console.log(`Checkservice luistert op http://${ADRES}:${POORT}`));
});
