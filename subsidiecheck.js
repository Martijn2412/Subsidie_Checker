/* Subsidiecheck: de rekenregels in één bestand.
   Wordt gebruikt door index.html (de checkpagina) en is bedoeld voor TIOS of een
   andere koppeling. Werkt in de browser (window.SubsidieCheck) en in Node
   (require("./subsidiecheck.js")). Geen afhankelijkheden.

   Snel gebruiken (zie docs/TIOS-koppeling.md):
     const uit = SubsidieCheck.check(
       {gemeente: "Arnhem", energielabel: "E", woz: 325000, bouwjaar: 1968, eigenaar_bewoner: true},
       regelingen);              // inhoud van regelingen.json
     uit.uitkomst                // "mogelijk" | "aanvullen" | "voldoet_niet" | "geen_regeling"
     uit.tekst                   // één regel voor onder het energielabel
*/
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SubsidieCheck = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const eur = n => "€" + Number(n).toLocaleString("nl-NL");
  const labelTxt = k => k.label === "geen" ? "geen label" : k.label ? `label ${k.label}` : "label onbekend";
  const norm = s => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/g, "");

  /* ---------- toetsing van één regeling (zelfde regels als de checkpagina) ---------- */
  function isolatiestaat(c) {
    if (c.isolatiestaat !== undefined) return c.isolatiestaat;
    // ouder plat formaat omzetten
    if (!c.labels && c.bouwdelen_min == null) return null;
    if (c.bouwdelen_modus === "alternatief") return {regels: [{labels: c.labels}, {bouwdelen_min: c.bouwdelen_min}]};
    const r = {}; if (c.labels) r.labels = c.labels; if (c.bouwdelen_min != null) r.bouwdelen_min = c.bouwdelen_min;
    return {regels: [r]};
  }
  function beschrijf(r) {
    const d = [];
    if (r.labels) d.push(r.labels.length === 1 && r.labels[0] === "geen" ? "geen label" : "label " + r.labels.join("/"));
    if (r.bouwjaar_max != null) d.push("bouwjaar t/m " + r.bouwjaar_max);
    if (r.bouwjaar_min != null) d.push("bouwjaar vanaf " + r.bouwjaar_min);
    if (r.bouwdelen_min != null) d.push(`min. ${r.bouwdelen_min} slechte bouwdelen`);
    return d.join(" + ");
  }
  function toetsRegel(r, k) {
    const s = [];
    if (r.labels) s.push(!k.label ? "unk" : r.labels.includes(k.label) ? "ok" : "no");
    if (r.bouwdelen_min != null) s.push(!k.bouwdelenBeoordeeld ? "unk" : k.bouwdelen.length >= r.bouwdelen_min ? "ok" : "no");
    if (r.bouwjaar_max != null) s.push(k.bouwjaar == null ? "unk" : k.bouwjaar <= r.bouwjaar_max ? "ok" : "no");
    if (r.bouwjaar_min != null) s.push(k.bouwjaar == null ? "unk" : k.bouwjaar >= r.bouwjaar_min ? "ok" : "no");
    return s.includes("no") ? "no" : s.every(x => x === "ok") ? "ok" : "unk";
  }

  /* Geeft per voorwaarde {status, label, detail, veld}.
     status: ok | no | unk (klantgegeven ontbreekt) | nodata | info.
     veld: welk klantgegeven nodig is (handig om te tonen wat er nog mist). */
  function evaluate(r, k) {
    const c = r.criteria || {}, out = [];
    const add = (status, label, detail, veld) => out.push({status, label, detail, veld});

    if (c.eigenaar_bewoner === true) {
      add(k.eb === "ja" ? "ok" : k.eb === "nee" ? "no" : "unk", "Eigenaar-bewoner", k.eb ? "" : "Vraag of de klant zelf in de woning woont", "eigenaar_bewoner");
    }
    if (c.woz_max != null) {
      const rule = c.woz_regel === "lte" ? "≤" : "<";
      const txt = `WOZ ${rule} ${eur(c.woz_max)}${c.woz_peildatum ? ` (${/peil/.test(c.woz_peildatum) ? "" : "peildatum "}${c.woz_peildatum})` : ""}`;
      if (k.woz == null) add("unk", txt, "WOZ-waarde klant ontbreekt" + (c.woz_uitzondering ? `. Uitzondering: ${c.woz_uitzondering}` : ""), "woz");
      else {
        const pass = c.woz_regel === "lte" ? k.woz <= c.woz_max : k.woz < c.woz_max;
        if (pass) add("ok", txt, `Klant: ${eur(k.woz)}. Check of dit de WOZ op de peildatum is.`, "woz");
        else if (c.woz_uitzondering) add("unk", txt, `Klant: ${eur(k.woz)}, boven de grens. Kan nog als: ${c.woz_uitzondering}`, "woz");
        else add("no", txt, `Klant: ${eur(k.woz)}`, "woz");
      }
    }
    const iso = isolatiestaat(c);
    if (iso && iso.regels && iso.regels.length) {
      const txt = iso.omschrijving || iso.regels.map(beschrijf).join(", of ");
      const res = iso.regels.map(x => toetsRegel(x, k));
      const i = res.indexOf("ok");
      if (i >= 0) add("ok", txt, "Voldoet via: " + beschrijf(iso.regels[i]) + (iso.afgeleid ? ". Afgeleid uit de SPUK-definitie, check de regeling" : ""), "energielabel");
      else if (res.every(x => x === "no")) add("no", txt, `Klant: ${labelTxt(k)}, ${k.bouwdelen.length} slechte bouwdelen${k.bouwjaar ? ", bouwjaar " + k.bouwjaar : ""}`, "energielabel");
      else add("unk", txt, "Vul energielabel, bouwdelen en/of bouwjaar in", "energielabel");
    }
    if (c.bouwjaar_max != null || c.bouwjaar_min != null) {
      const txt = `Bouwjaar ${c.bouwjaar_min != null ? "vanaf " + c.bouwjaar_min + " " : ""}${c.bouwjaar_max != null ? "t/m " + c.bouwjaar_max : ""}`.trim();
      if (k.bouwjaar == null) add("unk", txt, "Bouwjaar ontbreekt", "bouwjaar");
      else add((c.bouwjaar_max == null || k.bouwjaar <= c.bouwjaar_max) && (c.bouwjaar_min == null || k.bouwjaar >= c.bouwjaar_min) ? "ok" : "no", txt, `Klant: ${k.bouwjaar}`, "bouwjaar");
    } else if (c.bouwjaar_opmerking) {
      add("nodata", "Bouwjaar", c.bouwjaar_opmerking, "bouwjaar");
    }
    if (c.woonoppervlak_max != null) {
      const txt = `Woonoppervlak max. ${c.woonoppervlak_max} m²`;
      if (k.opp == null) add("unk", txt, "Woonoppervlak ontbreekt (Kadaster/BAG)", "woonoppervlak");
      else add(k.opp <= c.woonoppervlak_max ? "ok" : "no", txt, `Klant: ${k.opp} m²`, "woonoppervlak");
    }
    if (c.inkomen === "vereist") {
      add(k.inkomen === "ja" ? "ok" : k.inkomen === "nee" ? "no" : "unk", "Laag inkomen vereist", r.inkomensgrens || "", "laag_inkomen");
    } else if (c.inkomen === "bonus") {
      add("info", "Hoger bedrag bij laag inkomen", k.inkomen === "ja" ? "Klant komt mogelijk in aanmerking voor het hogere bedrag" : (r.inkomensgrens || ""), "laag_inkomen");
    }
    if (c.vve) {
      if (k.type === "appartement") {
        if (c.vve === "nee") add("no", "Alleen grondgebonden woningen", c.vve_opmerking || "", "woningtype");
        else if (c.vve === "ja") add("ok", "Appartement/VvE", c.vve_opmerking || "VvE kan aanvragen", "woningtype");
        else add("unk", "Appartement/VvE", c.vve_opmerking || "", "woningtype");
      } else if (k.type === "grondgebonden") {
        if (c.vve === "nee") add("ok", "Grondgebonden woning", c.vve_opmerking || "", "woningtype");
      } else if (c.vve !== "ja") {
        add("unk", "Woningtype", c.vve_opmerking || "Check of het om een appartement gaat", "woningtype");
      }
    }
    return out;
  }
  function isClosed(r, nu) {
    if (String(r.status).toLowerCase() === "gesloten") return true;
    if (r.looptijd_eind) { const d = new Date(r.looptijd_eind + "T23:59:59"); if (!isNaN(d) && d < (nu || new Date())) return true; }
    return false;
  }
  function verdict(r, crit, nu) {
    if (isClosed(r, nu)) return ["v-off", "Gesloten"];
    if (crit.some(x => x.status === "no")) return ["v-no", "Voldoet niet"];
    if (crit.some(x => x.status === "unk" || x.status === "nodata") || crit.length === 0) return ["v-unk", "Aanvullen of checken"];
    return ["v-ok", "Voldoet aan bekende voorwaarden"];
  }

  /* ---------- koppeling (TIOS e.d.): eenvoudige invoer, één antwoord ---------- */
  const leeg = v => v == null || v === "";
  const getal = x => {
    if (leeg(x)) return null;
    if (typeof x === "number") return isFinite(x) ? x : null;
    const n = Number(String(x).replace(/[^\d.,-]/g, "").replace(/\.(?=\d{3}\b)/g, "").replace(",", "."));
    return isNaN(n) ? null : n;
  };
  const jaNee = x => {
    if (leeg(x)) return "";
    if (x === true || /^(ja|j|yes|true|1)$/i.test(String(x).trim())) return "ja";
    if (x === false || /^(nee|n|no|false|0)$/i.test(String(x).trim())) return "nee";
    return "";
  };
  function labelNorm(x) {
    if (leeg(x)) return "";
    const s = String(x).trim().toUpperCase();
    if (/^GEEN/.test(s)) return "geen";
    const m = /^([A-G])/.exec(s);
    return m ? m[1] : "";
  }
  function woningtype(x) {
    const s = String(x || "").toLowerCase();
    if (/appartement|flat|etage|portiek|galerij|bovenwoning|benedenwoning|maisonnette|vve/.test(s)) return "appartement";
    if (/grondgebonden|rijtjes|tussen|hoek|twee-onder|2-onder|vrijstaand|eengezins|woonhuis|geschakeld/.test(s)) return "grondgebonden";
    return "";
  }

  /* Zet de invoer van een koppeling om naar het klantformaat van evaluate().
     Alle velden zijn optioneel; wat ontbreekt blijft 'onbekend'.
       gemeente           "Arnhem"
       energielabel       "E", "A++", "geen"
       woz                325000
       bouwjaar           1968
       woonoppervlak      115           (m²)
       eigenaar_bewoner   true/false of "ja"/"nee"
       woningtype         "grondgebonden" / "appartement" (of bijv. "tussenwoning", "flat")
       laag_inkomen       true/false of "ja"/"nee"
       slechte_bouwdelen  aantal (2) of lijst (["dak","gevel"]); leeg = niet beoordeeld */
  function maakKlant(inv) {
    inv = inv || {};
    const bd = inv.slechte_bouwdelen;
    const bouwdelen = Array.isArray(bd) ? bd.slice() : getal(bd) != null ? Array.from({length: getal(bd)}, (_, i) => "bouwdeel " + (i + 1)) : [];
    return {
      gemeente: inv.gemeente || "",
      label: labelNorm(inv.energielabel != null ? inv.energielabel : inv.label),
      woz: getal(inv.woz),
      bouwjaar: getal(inv.bouwjaar),
      opp: getal(inv.woonoppervlak != null ? inv.woonoppervlak : inv.oppervlakte),
      bouwdelen,
      bouwdelenBeoordeeld: !leeg(bd),
      eb: jaNee(inv.eigenaar_bewoner),
      type: woningtype(inv.woningtype),
      inkomen: jaNee(inv.laag_inkomen),
    };
  }

  function bedragTekst(b) {
    if (leeg(b)) return "";
    if (typeof b === "number") return eur(b);
    if (typeof b === "object") {
      const d = [b.max != null ? "max. " + eur(b.max) : "", b.min != null ? "min. " + eur(b.min) : "", b.percentage != null ? b.percentage + "%" : ""].filter(Boolean);
      return d.join(", ");
    }
    return String(b);
  }
  const kort = (s, n) => (s = String(s || "").replace(/\s+/g, " ").trim()).length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;

  const VELD_TEKST = {
    eigenaar_bewoner: "eigenaar-bewoner", woz: "WOZ-waarde", energielabel: "energielabel/isolatiestaat",
    bouwjaar: "bouwjaar", woonoppervlak: "woonoppervlak", laag_inkomen: "inkomen", woningtype: "woningtype",
  };
  const UITKOMST = {"v-ok": "voldoet", "v-unk": "aanvullen", "v-no": "voldoet_niet", "v-off": "gesloten"};

  /* Toetst een klant tegen alle regelingen van zijn gemeente.
     invoer:      zie maakKlant()
     regelingen:  array uit regelingen.json (of tios/subsidies.json → .regelingen)
     opties.zoekstatus: (optioneel) inhoud van zoekstatus.json óf van tios/subsidies.json, voor "nog niet uitgelezen"
     opties.nu:   (optioneel) Date, voor testen
     Geeft {gemeente, uitkomst, tekst, regelingen:[...], ontbreekt:[...], wacht_op_uitlezen} */
  function check(invoer, regelingen, opties) {
    opties = opties || {};
    const k = maakKlant(invoer);
    const g = norm(k.gemeente);
    const regs = g ? (regelingen || []).filter(r => norm(r.gemeente) === g) : [];
    // zoekstatus.json heeft een lijst; tios/subsidies.json een object per gemeentenaam.
    const zsBron = opties.zoekstatus && opties.zoekstatus.gemeenten;
    let zs = null;
    if (Array.isArray(zsBron)) zs = zsBron.find(x => norm(x.gemeente) === g) || null;
    else if (zsBron) {
      const naam = Object.keys(zsBron).find(n => norm(n) === g);
      if (naam) zs = Object.assign({gemeente: naam}, zsBron[naam]);
    }
    const wacht = !zs ? 0 : Array.isArray(zs.wacht_op_uitlezen) ? zs.wacht_op_uitlezen.length : (zs.wacht_op_uitlezen || 0);

    const uit = regs.map(r => {
      const crit = evaluate(r, k);
      const [code, tekst] = verdict(r, crit, opties.nu);
      return {
        id: r.id, naam: r.naam, type: r.type || null, uitkomst: UITKOMST[code], uitkomst_tekst: tekst,
        bedrag: bedragTekst(r.bedrag), aanvragen_tm: r.looptijd_eind || null,
        bron: r.bron || "cvdr", betrouwbaarheid: r.betrouwbaarheid || null, gecontroleerd: !!r.gecontroleerd,
        bron_url: r.bron_url || null,
        ontbreekt: [...new Set(crit.filter(x => x.status === "unk").map(x => x.veld))],
        controles: crit,
      };
    });
    const open = uit.filter(r => r.uitkomst !== "gesloten");
    const rang = {voldoet: 0, aanvullen: 1, voldoet_niet: 2};
    open.sort((a, b) => rang[a.uitkomst] - rang[b.uitkomst]);
    let uitkomst;
    if (!g) uitkomst = "onbekend";
    else if (open.some(r => r.uitkomst === "voldoet")) uitkomst = "mogelijk";
    else if (open.some(r => r.uitkomst === "aanvullen")) uitkomst = "aanvullen";
    else if (open.length) uitkomst = "voldoet_niet";
    else uitkomst = "geen_regeling";
    const kandidaten = open.filter(r => r.uitkomst !== "voldoet_niet");
    const ontbreekt = [...new Set(kandidaten.flatMap(r => r.ontbreekt))];

    const res = {gemeente: regs[0] ? regs[0].gemeente : (zs ? zs.gemeente : k.gemeente), uitkomst,
                 regelingen: open.concat(uit.filter(r => r.uitkomst === "gesloten")), ontbreekt, wacht_op_uitlezen: wacht};
    res.tekst = samenvatting(res);
    return res;
  }

  /* Eén regel tekst, bedoeld voor onder het energielabel in TIOS. */
  function samenvatting(res) {
    const isLening = r => /lening/i.test(r.type || "") && !/lening/i.test(r.naam || "");
    const naamBedrag = r => kort(r.naam, 60) + (isLening(r) ? " (lening)" : "") + (r.bedrag ? ` (${kort(r.bedrag, 45)})` : "");
    const mist = res.ontbreekt.map(v => VELD_TEKST[v] || v);
    const nog = res.wacht_op_uitlezen ? ` Nog ${res.wacht_op_uitlezen} regeling(en) niet uitgelezen.` : "";
    const web = res.regelingen.some(r => r.uitkomst !== "voldoet_niet" && r.uitkomst !== "gesloten" && r.bron === "web") ? " Let op: bron is internet, controleren." : "";
    switch (res.uitkomst) {
      case "onbekend":
        return "Subsidiecheck: gemeente onbekend.";
      case "mogelijk": {
        const ok = res.regelingen.filter(r => r.uitkomst === "voldoet");
        return `Mogelijk subsidie: ${ok.map(naamBedrag).join("; ")}.` + (mist.length ? ` Nog checken: ${mist.join(", ")}.` : "") + web + nog;
      }
      case "aanvullen": {
        const n = res.regelingen.filter(r => r.uitkomst === "aanvullen").length;
        return `Mogelijk subsidie (${n} regeling${n > 1 ? "en" : ""} in ${res.gemeente}). Aanvullen: ${mist.join(", ") || "voorwaarden checken via de bron"}.` + web + nog;
      }
      case "voldoet_niet": {
        const reden = [...new Set(res.regelingen.filter(r => r.uitkomst === "voldoet_niet")
          .flatMap(r => r.controles.filter(x => x.status === "no").map(x => x.label)))];
        return `Geen passende subsidie in ${res.gemeente}: voldoet niet aan ${kort(reden.join("; "), 120)}.` + nog;
      }
      default:
        return res.wacht_op_uitlezen
          ? `Subsidie ${res.gemeente}: ${res.wacht_op_uitlezen} regeling(en) gevonden, voorwaarden nog niet uitgelezen.`
          : `Geen open gemeentelijke isolatiesubsidie gevonden in ${res.gemeente}.`;
    }
  }

  return {evaluate, verdict, isClosed, isolatiestaat, beschrijf, toetsRegel, labelTxt,
          maakKlant, check, samenvatting, labelNorm, bedragTekst, norm};
});
