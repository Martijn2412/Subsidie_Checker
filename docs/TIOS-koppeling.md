# Koppeling met TIOS

Doel: als er in TIOS een lead of klant binnenkomt, staat onder het energielabel één regel zoals

> **Mogelijk subsidie: Isolatiesubsidie Doesburg (max. € 2.000). Nog checken: eigenaar-bewoner.**

TIOS hoeft daarvoor niets zelf uit te rekenen. Alles staat klaar in deze repo en wordt elke dag bijgewerkt.

## Wat er klaarstaat

Na elke gemergde "Subsidie-update" staan deze bestanden online (GitHub Pages):

| Bestand | Adres | Waarvoor |
|---|---|---|
| `tios/subsidies.json` | `https://martijn2412.github.io/Subsidie_Checker/tios/subsidies.json` | Alle open regelingen met voorwaarden + per gemeente de conclusie |
| `subsidiecheck.js` | `https://martijn2412.github.io/Subsidie_Checker/subsidiecheck.js` | De rekenregels: klantgegevens erin, uitkomst + tekst eruit |
| `tios/regelingen.csv` | `.../tios/regelingen.csv` | Eén rij per open regeling (voor een import of Excel) |
| `tios/gemeenten.csv` | `.../tios/gemeenten.csv` | Alle 342 gemeenten met de conclusie |

De checkpagina (`index.html`) gebruikt precies dezelfde rekenregels. TIOS en de binnendienst zien dus altijd hetzelfde oordeel.

## Welke klantgegevens zijn nodig

Alles is optioneel. Wat ontbreekt, komt terug als "aanvullen".

| Veld | Voorbeeld | Waar haal je het vandaan |
|---|---|---|
| `gemeente` | `"Arnhem"` | Uit het adres. TIOS heeft het meestal al; anders gratis via PDOK (postcode + huisnummer). |
| `energielabel` | `"E"`, `"geen"` | TIOS (staat er al), of EP-Online van RVO. |
| `woz` | `325000` | Vragen aan de klant of het WOZ-waardeloket (geen gratis bulk-API). |
| `bouwjaar` | `1968` | BAG via PDOK (gratis, geen sleutel). |
| `woonoppervlak` | `115` | BAG via PDOK. |
| `eigenaar_bewoner` | `true` | Vraag in het intakeformulier. |
| `woningtype` | `"tussenwoning"`, `"appartement"` | TIOS of BAG. Woorden als tussen/hoek/vrijstaand = grondgebonden, flat/portiek/VvE = appartement. |
| `laag_inkomen` | `false` | Vraag in het intakeformulier (alleen nodig bij inkomensregelingen). |
| `slechte_bouwdelen` | `2` | Inschatting adviseur: aantal niet of slecht geïsoleerde bouwdelen. |

**Tip:** voeg in TIOS twee vragen toe aan de intake: "Woont u zelf in de woning?" en "Weet u uw WOZ-waarde?". Dat zijn de gegevens die het vaakst ontbreken.

## De uitkomst

```js
const uit = SubsidieCheck.check(
  {gemeente: "Doesburg", energielabel: "D", woz: 280000, eigenaar_bewoner: true, woningtype: "tussenwoning"},
  data.regelingen            // uit tios/subsidies.json
);
uit.uitkomst   // "mogelijk" | "aanvullen" | "voldoet_niet" | "geen_regeling" | "onbekend"
uit.tekst      // de regel voor onder het energielabel
uit.ontbreekt  // bijv. ["woz", "eigenaar_bewoner"]: wat de binnendienst nog moet vragen
uit.regelingen // per regeling: naam, bedrag, aanvragen_tm, bron_url, uitkomst, controles
```

| `uitkomst` | Betekenis | Voorbeeldtekst |
|---|---|---|
| `mogelijk` | Voldoet aan alle bekende voorwaarden van minstens één regeling | Mogelijk subsidie: … (max. € 2.000). |
| `aanvullen` | Kan nog, maar er mist informatie | Mogelijk subsidie (2 regelingen in Arnhem). Aanvullen: WOZ-waarde, eigenaar-bewoner. |
| `voldoet_niet` | Er zijn regelingen, maar de klant valt erbuiten | Geen passende subsidie in Apeldoorn: voldoet niet aan WOZ ≤ €477.000. |
| `geen_regeling` | Geen open regeling gevonden (of nog niet uitgelezen) | Geen open gemeentelijke isolatiesubsidie gevonden in Groningen. |

Altijd indicatief: de binnendienst checkt de bron voordat er iets aan de klant wordt beloofd.

## Aanbevolen: checkservice op de TIOS-server

TIOS draait op Ubuntu. De kortste route is `koppeling/checkservice.js`: een kleine service (alleen Node.js nodig, geen pakketten) die één keer per dag `tios/subsidies.json` ophaalt en op `GET http://localhost:8085/check?gemeente=…&energielabel=…` een oordeel teruggeeft. `koppeling/subsidiecheck.service` laat hem als systemd-dienst draaien. Uitleg, beheer en overdracht: `docs/Technisch-ontwerp-TIOS-koppeling.docx`.

## Andere manieren om het in TIOS te krijgen

Welke het wordt, hangt af van wat TIOS kan. Vraag de leverancier van TIOS:
*"Kan TIOS bij een nieuwe lead een HTTP-aanroep doen (webhook) en het antwoord in een veld zetten? Of kunnen we eigen JavaScript draaien?"*

### 1. Link of knop (werkt nu al, geen bouwwerk)
Zet in TIOS een knop "Subsidiecheck" met deze link. De checkpagina vult de gegevens zelf in:
```
https://martijn2412.github.io/Subsidie_Checker/?postcode={postcode}&huisnummer={huisnummer}&toevoeging={toevoeging}&label={energielabel}&woz={woz}
```
Nadeel: het oordeel staat niet automatisch onder het energielabel. De binnendienst moet klikken.

### 2. TIOS rekent zelf (aanbevolen als TIOS eigen scripts toestaat)
1. TIOS laadt één keer per dag `tios/subsidies.json` en `subsidiecheck.js`.
2. Bij een nieuwe lead roept TIOS `SubsidieCheck.check(klant, data.regelingen)` aan.
3. `uit.tekst` gaat in het veld onder het energielabel.

Voordeel: de klantgegevens verlaten TIOS niet (privacy). Er is geen server nodig en het kost niets.

### 3. Klein tussenstation (als TIOS alleen webhooks kan)
Een gratis Cloudflare Worker (of Azure Function) die TIOS aanroept:
```
GET https://subsidiecheck.<jouw-domein>.workers.dev/?gemeente=Arnhem&energielabel=E&woz=300000
→ {"uitkomst":"aanvullen","tekst":"Mogelijk subsidie (…). Aanvullen: …","ontbreekt":["eigenaar_bewoner"]}
```
De code is kort, omdat al het rekenwerk in `subsidiecheck.js` zit:
```js
// worker.js (Cloudflare Workers). Plak subsidiecheck.js erboven, of bundel het mee.
export default {
  async fetch(req) {
    const p = Object.fromEntries(new URL(req.url).searchParams);
    const data = await (await fetch("https://martijn2412.github.io/Subsidie_Checker/tios/subsidies.json",
                                    {cf: {cacheTtl: 3600}})).json();
    const uit = SubsidieCheck.check(p, data.regelingen);
    return Response.json({uitkomst: uit.uitkomst, tekst: uit.tekst, ontbreekt: uit.ontbreekt,
                          regelingen: uit.regelingen.map(({naam, bedrag, uitkomst, bron_url}) => ({naam, bedrag, uitkomst, bron_url}))});
  }
};
```
Let op: zo gaan klantgegevens (geen naam, wel gemeente/label/WOZ) via die Worker. Zet er een geheime sleutel op als TIOS dat ondersteunt.

### 4. Alleen importeren (als TIOS niets anders kan)
`tios/gemeenten.csv` importeren als opzoektabel op gemeente. Dan zie je per gemeente "regeling / geen regeling", maar niet of déze klant voldoet.

## Testen
```
node --test tests/*.test.js
```
De tests staan in `tests/subsidiecheck.test.js` en draaien ook automatisch bij elke pull request.
