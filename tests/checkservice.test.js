// Test de checkservice zonder internet: fetch wordt nagebootst.
const test = require("node:test");
const assert = require("node:assert/strict");

const PDOK = {
  "2511AB|12": {docs: [{gemeentenaam: "'s-Gravenhage", woonplaatsnaam: "Den Haag", huisnummer: 12, postcode: "2511AB", adresseerbaarobject_id: "1"}],
                bag: [{identificatie: "1", bouwjaar: "1931", oppervlakte: "95"}]},
  "7255AA|3":  {docs: [{gemeentenaam: "Bronckhorst", woonplaatsnaam: "Hengelo", huisnummer: 3, postcode: "7255AA", adresseerbaarobject_id: "2"}],
                bag: [{identificatie: "2", bouwjaar: "1965", oppervlakte: "120"}]},
  "1000AA|5":  {docs: [{gemeentenaam: "Testdorp", huisnummer: 5, huisletter: "A", adresseerbaarobject_id: "3"},
                       {gemeentenaam: "Testdorp", huisnummer: 5, huisletter: "B", adresseerbaarobject_id: "4"}],
                bag: [{identificatie: "3", bouwjaar: "1950", oppervlakte: "60"}, {identificatie: "4", bouwjaar: "2010", oppervlakte: "80"}]},
};
let pdokAanroepen = 0, pdokPlat = false;
global.fetch = async (url) => {
  pdokAanroepen++;
  if (pdokPlat) throw new Error("netwerk weg");
  const u = new URL(url);
  const pc = (u.searchParams.getAll("fq").find(x => x.startsWith("postcode:")) || "").slice(9)
          || (/<Literal>(\d{4}[A-Z]{2})<\/Literal>/.exec(u.searchParams.get("filter") || "") || [])[1];
  const hn = (/^\S+ (\d+)$/.exec(u.searchParams.get("q") || "") || [])[1]
          || (/huisnummer<\/PropertyName><Literal>(\d+)/.exec(u.searchParams.get("filter") || "") || [])[1];
  const rec = PDOK[`${pc}|${hn}`] || {docs: [], bag: []};
  assert.equal(u.hostname, "api.pdok.nl", "alleen de Locatieserver mag worden aangeroepen");
  const body = {response: {docs: rec.docs}};
  return {ok: true, json: async () => body};
};

const svc = require("../koppeling/checkservice.js");
const regeling = (gemeente, extra = {}) => ({id: gemeente + "-1", gemeente, naam: "Isolatiesubsidie " + gemeente, status: "open",
  bedrag: "max. € 1.000", criteria: {eigenaar_bewoner: true, bouwjaar_max: 1980, ...extra}});
svc._zetData({bijgewerkt: new Date().toISOString().slice(0, 10), gemeenten: {},
  regelingen: [regeling("'s-Gravenhage"), regeling("Bronckhorst"), regeling("Testdorp")]});

test("postcode geeft de officiële gemeentenaam, ook als TIOS 'Den Haag' stuurt", async () => {
  const uit = await svc.beoordeel({postcode: "2511 ab", huisnummer: "12", gemeente: "Den Haag", bouwjaar: "1931", eigenaar_bewoner: "ja"});
  assert.equal(uit.gemeente, "'s-Gravenhage");
  assert.equal(uit.uitkomst, "mogelijk");
});

test("woonplaats Hengelo in gemeente Bronckhorst gaat goed", async () => {
  const uit = await svc.beoordeel({postcode: "7255AA", huisnummer: "3", eigenaar_bewoner: "ja"});
  assert.equal(uit.gemeente, "Bronckhorst");
  assert.equal(uit.adres.woonplaats, "Hengelo");
});

test("meerdere woningen op één nummer: gemeente is gewoon bekend", async () => {
  const uit = await svc.zoekAdres("1000AA", "5");
  assert.equal(uit.gemeente, "Testdorp");
});

test("adres niet gevonden of PDOK plat: waarschuwing, geen crash", async () => {
  const onbekend = await svc.beoordeel({postcode: "9999ZZ", huisnummer: "1"});
  assert.equal(onbekend.uitkomst, "onbekend");
  assert.match(onbekend.waarschuwing, /adres niet gevonden/);
  pdokPlat = true;
  const plat = await svc.beoordeel({postcode: "8888ZZ", huisnummer: "1", gemeente: "Testdorp", eigenaar_bewoner: "ja"});
  pdokPlat = false;
  assert.equal(plat.gemeente, "Testdorp");       // valt terug op de meegestuurde gemeente
  assert.match(plat.waarschuwing, /PDOK niet bereikbaar/);
});

test("zelfde adres wordt maar één keer opgezocht", async () => {
  await svc.zoekAdres("2511AB", "12");
  const voor = pdokAanroepen;
  await svc.zoekAdres("2511AB", "12");
  assert.equal(pdokAanroepen, voor);
});

test("eigenaar-bewoner hoeft niet meegestuurd te worden: standaard ja", async () => {
  const uit = await svc.beoordeel({postcode: "2511AB", huisnummer: "12", bouwjaar: "1931"});
  assert.equal(uit.uitkomst, "mogelijk");
  assert.ok(!uit.ontbreekt.includes("eigenaar_bewoner"));
  assert.doesNotMatch(uit.tekst, /eigenaar-bewoner/);
});

test("eigenaar_bewoner=nee van TIOS telt wel", async () => {
  const uit = await svc.beoordeel({postcode: "2511AB", huisnummer: "12", bouwjaar: "1931", eigenaar_bewoner: "nee"});
  assert.equal(uit.uitkomst, "voldoet_niet");
});
