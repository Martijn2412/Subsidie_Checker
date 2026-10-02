# Werkafspraken voor Claude (Subsidie_Checker)

Eigenaar: Martijn (Takkenkamp, binnendienst). Uitleg van het project staat in `README.md`,
de koppeling met TIOS in `docs/TIOS-koppeling.md`.

## Waar dit om draait
Nederland moet van het gas af, en dat begint bij goed geïsoleerde huizen. Bijna elke gemeente heeft daar geld
voor: een subsidie, een voucher of een lening voor dak-, vloer-, gevel- of glasisolatie. Maar die regelingen
staan verspreid over 342 gemeenten, elk met eigen voorwaarden, budgetten en einddata. Ze veranderen
voortdurend, en geen mens houdt dat bij.

**Deze tool houdt het wél bij.** Zodra Martijn hem start, haalt hij van álle gemeenten de isolatieregelingen
op, leest de voorwaarden uit en zet ze klaar. Komt er bij Takkenkamp een lead binnen, dan staat in TIOS onder het
energielabel in één regel of die klant **mogelijk recht heeft op subsidie**. Bijvoorbeeld: "Mogelijk subsidie:
Isolatiesubsidie Doesburg (max. € 2.000). Nog checken: WOZ-waarde."

Waarom dat ertoe doet:
- **Voor de klant:** honderden tot duizenden euro's die anders blijven liggen, omdat niemand wist dat de
  regeling bestond. Dat kan het verschil zijn tussen wel of niet isoleren.
- **Voor de binnendienst:** geen zoekwerk per gemeente meer. Ze zien het meteen en kunnen het in het eerste
  gesprek noemen.
- **Voor Takkenkamp:** meer klanten die "ja" zeggen, en een voorsprong op bedrijven die dit niet weten.

Elke gemeente die ontbreekt, en elke voorwaarde die niet is uitgelezen, is dus een klant die misschien
subsidie misloopt. **Lever daarom werk af dat klopt en dat blijft werken**, ook als Martijn er niet meer is:
- Liever eerlijk "dit weet ik niet" dan een oordeel dat een klant iets belooft wat niet waar is.
- Liever een tool die zichzelf herstelt (verder waar hij stopte, niets kwijt) dan een die iemand moet oppassen.
- Liever simpel en uitgelegd dan slim en onbegrijpelijk.

## Doel
Van **elke Nederlandse gemeente** (± 342) uitzoeken of er een regeling is voor **isolatie van bestaande
koopwoningen** (subsidie, voucher, korting, gratis isolatieactie of lening), **op welke manier dan ook**:
in het CVDR, op de eigen gemeentesite of bij een partner die het voor de gemeente uitvoert (energieloket,
bouwloket, WoonWijzerWinkel, SVn). Van elke regeling de **voorwaarden** ophalen en bijwerken in
`overzicht_voorwaarden.xlsx` (en `regelingen.json`, de checkpagina en de TIOS-export).

Een gemeente zonder regeling moet aantoonbaar overal doorzocht zijn. "Niet gezocht" is iets anders dan
"niets gevonden". Dat onderscheid moet zichtbaar blijven in de Excel (blad *Gemeenten*, kolom *Bronnen doorzocht*).

## Hoe het werkt (per gemeente, `scraper/run.py`)
1. **CVDR** (`zoek_cvdr`): zoekwoorden uit `scraper/config.json` → trechter: titel → vervallen → tekst →
   AI-filter → AI-extractie (`scraper/prompt_extractie.md`), via Pollinations.
2. **Internet** (`scraper/webbronnen.py`, eens per `web_zoeken_elke_dagen`):
   gemeentesite (adres uit het Register van Overheidsorganisaties, sitemap of rondgang) + partners
   (`partners` in config: lijstpagina's en URL-sjablonen) → gratis tekstfilter → links naar voorwaarden en pdf's volgen.
   Levert dat niets op, of heeft de gemeente nog geen open regeling: AI-zoekactie met Google (de echte bronnen).
   Alle pagina's van een gemeente gaan in **één** AI-aanroep, en alleen als de tekst veranderd is (hash in `data/web_state.json`).
3. **Controle op verzinnen**: het `bewijs` per veld moet in de brontekst staan (`controleer_bewijs`).
   Zo niet: betrouwbaarheid omlaag en een melding in de PR.
4. **Dubbelen**: een webpagina over een regeling die al uit het CVDR komt wordt geen nieuw record, maar
   komt bij `extra_bronnen` ("Ook vermeld op" in de Excel).
5. Uitvoer: `regelingen.json`, `zoekstatus.json`, `overzicht_voorwaarden.xlsx`, `tios/`, `data/`.
   De workflow (alleen handmatig gestart) maakt een PR "Subsidie-update". Pas na het mergen ziet de binnendienst het.

## Communicatie
- Schrijf in het Nederlands, in gewone taal en met korte zinnen. Niet technisch, tenzij Martijn erom vraagt.
- Documenten voor anderen (zoals TIOS): alleen wat er nodig is en waarom, en kort hoe het gebruikt wordt.
- Zeg eerlijk wat wel en niet getest is. Gemeentesites en PDOK zijn vanuit de Claude-omgeving meestal niet
  bereikbaar. Zeg het dan, en claim niet dat iets werkt.

## Lijsten met gemeenten
- Bepaal nooit zelf welke gemeenten voorrang hebben. Geef geen volgorde of advies over waar te beginnen.
- Vraagt Martijn om gemeenten die nog werk nodig hebben, geef dan alleen de gemeenten waar **mogelijk
  voorwaarden zijn die nog niet met AI zijn uitgelezen**:
  - gemeenten met regelingen in de wachtrij (`wacht_op_uitlezen` in `zoekstatus.json`);
  - gemeenten met een open regeling zonder voorwaarden (vooral regelingen die via internet zijn gevonden).
  - Neem gemeenten waar geen regeling is gevonden en gemeenten met alleen gesloten regelingen **niet** op.
  - Is een regeling zonder voorwaarden handmatig (`"handmatig": true`), noem dat in één zin: de scraper slaat
    die over.
- Opmaak: alfabetisch, alleen een komma ertussen, zonder spatie erna. Zo kun je de lijst direct in het veld
  "gemeenten" van Run workflow plakken.
- Gebruik de nieuwste data. Dat is de openstaande Subsidie-update (branch `subsidie-update`) als die er is,
  anders `main`. Zeg welke je hebt gebruikt.

## Keuzes en instellingen
- Kies niet stilletjes een grens of aantal (maximum aantal links, dagen, regelingen per run). Maak er een
  instelling van in `scraper/config.json` met uitleg (`_uitleg_...`), en noem de keuze in je antwoord.
- Wijzig het extractieformaat niet zonder `normaliseer.py`, `subsidiecheck.js`, `export_tios.py` en de tests mee te nemen.
- Wordt een filter ruimer, verhoog dan `FILTER_VERSIE` in `scraper/run.py`. Verandert het zoeken op internet,
  verhoog dan `WEB_VERSIE` (dan wordt alles opnieuw bekeken).
- Geen API-sleutels of klantgegevens in de repo; de repo en de checkpagina zijn openbaar.

## Git en pull requests
- Martijn controleert en merget zelf. Maak alleen een pull request als hij daarom vraagt, of als hij vraagt om
  iets in `main` te zetten.
- Martijn merget soms snel. Is een PR al gemerged, push dan niet meer naar die branch alsof de PR nog openstaat.
  Begin opnieuw vanaf `main` en maak een nieuwe PR. Zeg duidelijk wat wel en wat nog niet in `main` staat.
- Werkt iets pas na een merge (workflow, scraper), zeg dat erbij.
- Stuurt Martijn een aangepast Word-bestand terug, bewerk dan **zijn** versie. Maak het document niet opnieuw
  vanuit een script, want dan gaan zijn wijzigingen verloren.

## Data
- Deze bestanden worden door de scraper gemaakt; pas ze niet met de hand aan: `regelingen.json`,
  `zoekstatus.json`, `overzicht_voorwaarden.xlsx`, `tios/` en `data/`. Uitzondering: regelingen met
  `"handmatig": true` in `regelingen.json`.
- Gemeentenamen komen van PDOK, bijvoorbeeld "'s-Gravenhage" en "Hengelo (O)". TIOS stuurt postcode en
  huisnummer; de checkservice zoekt de gemeente zelf op. TIOS stuurt bouwjaar en woonoppervlak altijd mee.
- Alle leads van Takkenkamp zijn eigenaar-bewoner. Vraag daar niet naar en laat de check het niet als
  "nog checken" noemen; de checkservice en de checkpagina gaan standaard uit van "ja".

## Runs en AI-budget
- Er is geen vast schema: de run start alleen als Martijn op Run workflow drukt. Het gratis Gemini-tegoed (alleen
  voor zoeken) wordt om 09:00 Nederlandse tijd opnieuw gevuld. Lukt het uitlezen niet meer, dan stopt de run; de volgende gaat verder waar hij stopte (`data/voortgang.json`).
- Per gemeente staat het resultaat in de log van de stap "Regelingen ophalen en voorwaarden uitlezen":
  ✅ ⚠️ ➖ ❌ 🛑. Op de Summary-pagina van de run staat een tabel.

## Taalmodellen
- **Filter en uitlezen: Pollinations** (`taalmodel` in `scraper/config.json`, OpenAI-compatibel). Zonder sleutel
  werkt het anoniem (model `openai-fast`, ongeveer 1 aanvraag per 15 seconden, soms een tijdelijke 402: daarom
  meerdere pogingen). Met een gratis sleutel (secret `POLLINATIONS_API_KEY`, account op auth.pollinations.ai)
  is het betrouwbaarder en kan Pollinations ook op internet zoeken (`modellen.zoeken`).
- **Gemini** wordt alleen nog gebruikt voor de AI-zoekactie met Google (`gemini_alleen_voor_zoeken`). Is Gemini op,
  dan wordt alleen dat zoeken overgeslagen; de rest gaat door.
- Mistral, Ollama en andere aanbieders zijn er bewust uitgehaald (Martijn, 2-10-2026). `reserve_aanbieders` in de
  config kan nog wel een lijst van OpenAI-compatibele aanbieders bevatten, maar staat standaard leeg.
- Is het taalmodel niet bereikbaar, dan stopt de run en gaat de volgende verder waar hij stopte (`data/voortgang.json`).
  Daarom: zoeken zonder AI waar het kan, AI alleen voor uitlezen, en nooit opnieuw uitlezen wat niet veranderd is.

## Testen
- `node --test tests/*.test.js` (rekenregels en checkservice)
- `python -m unittest discover tests` (opschonen, verdergaan na onderbreking, internetregelingen).
  Er is geen sleutel nodig: Gemini, het CVDR en de websites worden nagebootst.
- De workflow "Tests" draait beide bij elke pull request.
- Internet en taalmodellen worden in de tests nagebootst (`tests/test_webbronnen.py`, `tests/test_web_run.py`,
  `tests/test_aanbieders.py`).
- Echt testen: Actions → *Subsidies bijwerken* → Run workflow met een paar gemeenten en **proef** aan (geen PR,
  uitkomst als download en per regeling een regel met `→` in de log). Eventueel **zonder AI** (alleen zoeken)
  Lokaal: `python scraper/run.py --zonder-ai --alleen Zeist`.
