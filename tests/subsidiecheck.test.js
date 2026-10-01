// Draaien: node --test tests/
const test = require("node:test");
const assert = require("node:assert");
const SC = require("../subsidiecheck.js");

const NU = new Date("2026-10-01T12:00:00");
const regeling = (extra = {}) => ({
  id: "test-1", gemeente: "Testdorp", naam: "Isolatiesubsidie Testdorp", bedrag: "max. € 2.000",
  looptijd_eind: "2027-12-31", status: "open", bron: "cvdr",
  criteria: {
    eigenaar_bewoner: true, woz_max: 450000, woz_regel: "lte", vve: "nee",
    isolatiestaat: {omschrijving: "label D-G of 2 slechte bouwdelen", regels: [{labels: ["D", "E", "F", "G"]}, {bouwdelen_min: 2}]},
  },
  ...extra,
});

test("maakKlant zet TIOS-invoer om", () => {
  const k = SC.maakKlant({energielabel: "e ", woz: "€ 325.000", eigenaar_bewoner: "Ja", woningtype: "Tussenwoning", slechte_bouwdelen: 2, laag_inkomen: false});
  assert.equal(k.label, "E");
  assert.equal(k.woz, 325000);
  assert.equal(k.eb, "ja");
  assert.equal(k.type, "grondgebonden");
  assert.equal(k.bouwdelen.length, 2);
  assert.equal(k.bouwdelenBeoordeeld, true);
  assert.equal(k.inkomen, "nee");
  assert.equal(SC.maakKlant({energielabel: "A++"}).label, "A");
  assert.equal(SC.maakKlant({woningtype: "portiekflat"}).type, "appartement");
});

test("alles bekend en goed: mogelijk", () => {
  const uit = SC.check({gemeente: "testdorp", energielabel: "E", woz: 300000, eigenaar_bewoner: true, woningtype: "hoekwoning"}, [regeling()], {nu: NU});
  assert.equal(uit.uitkomst, "mogelijk");
  assert.equal(uit.regelingen[0].uitkomst, "voldoet");
  assert.match(uit.tekst, /^Mogelijk subsidie: Isolatiesubsidie Testdorp \(max\. € 2\.000\)\.$/);
});

test("gegevens ontbreken: aanvullen met lijst van wat mist", () => {
  const uit = SC.check({gemeente: "Testdorp", energielabel: "E"}, [regeling()], {nu: NU});
  assert.equal(uit.uitkomst, "aanvullen");
  assert.deepEqual(uit.ontbreekt.sort(), ["eigenaar_bewoner", "woningtype", "woz"]);
  assert.match(uit.tekst, /Aanvullen: .*WOZ-waarde/);
});

test("WOZ te hoog: voldoet niet, met reden", () => {
  const uit = SC.check({gemeente: "Testdorp", energielabel: "E", woz: 600000, eigenaar_bewoner: true}, [regeling()], {nu: NU});
  assert.equal(uit.uitkomst, "voldoet_niet");
  assert.match(uit.tekst, /voldoet niet aan WOZ ≤ €450\.000/);
});

test("label B zonder slechte bouwdelen: voldoet niet; met 2 slechte bouwdelen wel", () => {
  const basis = {gemeente: "Testdorp", woz: 300000, eigenaar_bewoner: true, woningtype: "grondgebonden"};
  assert.equal(SC.check({...basis, energielabel: "B", slechte_bouwdelen: 0}, [regeling()], {nu: NU}).uitkomst, "voldoet_niet");
  assert.equal(SC.check({...basis, energielabel: "B", slechte_bouwdelen: 2}, [regeling()], {nu: NU}).uitkomst, "mogelijk");
  // bouwdelen niet beoordeeld: nog niet afwijzen
  assert.equal(SC.check({...basis, energielabel: "B"}, [regeling()], {nu: NU}).uitkomst, "aanvullen");
});

test("verlopen regeling telt niet mee", () => {
  const uit = SC.check({gemeente: "Testdorp", energielabel: "E"}, [regeling({looptijd_eind: "2026-01-01"})], {nu: NU});
  assert.equal(uit.uitkomst, "geen_regeling");
  assert.match(uit.tekst, /Geen open gemeentelijke isolatiesubsidie gevonden in Testdorp/);
});

test("geen regeling maar wel in de wachtrij", () => {
  const zoekstatus = {gemeenten: [{gemeente: "Leegdorp", wacht_op_uitlezen: [{cvdr_id: "CVDR1"}]}]};
  const uit = SC.check({gemeente: "Leegdorp"}, [regeling()], {nu: NU, zoekstatus});
  assert.equal(uit.uitkomst, "geen_regeling");
  assert.equal(uit.wacht_op_uitlezen, 1);
  assert.match(uit.tekst, /1 regeling\(en\) gevonden, voorwaarden nog niet uitgelezen/);
});

test("internetbron krijgt een waarschuwing", () => {
  const uit = SC.check({gemeente: "Testdorp", energielabel: "E", woz: 1, eigenaar_bewoner: true, woningtype: "grondgebonden"}, [regeling({bron: "web"})], {nu: NU});
  assert.match(uit.tekst, /bron is internet, controleren/);
});

test("draait zonder fouten op alle echte regelingen", () => {
  const regs = require("../regelingen.json");
  const gemeenten = [...new Set(regs.map(r => r.gemeente))];
  for (const g of gemeenten) {
    const uit = SC.check({gemeente: g, energielabel: "E", woz: 300000, bouwjaar: 1970, eigenaar_bewoner: true}, regs);
    assert.ok(["mogelijk", "aanvullen", "voldoet_niet", "geen_regeling"].includes(uit.uitkomst), g);
    assert.ok(uit.tekst.length > 10 && uit.tekst.length < 400, g + ": " + uit.tekst);
  }
});

test("tios/subsidies.json werkt met check()", () => {
  const data = require("../tios/subsidies.json");
  const zoekstatus = {gemeenten: Object.entries(data.gemeenten).map(([gemeente, v]) => ({gemeente, wacht_op_uitlezen: Array(v.wacht_op_uitlezen).fill({})}))};
  const uit = SC.check({gemeente: "Arnhem", energielabel: "E", woz: 300000}, data.regelingen, {zoekstatus});
  assert.ok(uit.regelingen.length > 0);
});
