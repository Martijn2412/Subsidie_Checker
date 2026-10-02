# Werkafspraken voor Claude (Subsidie_Checker)

Eigenaar: Martijn (Takkenkamp, binnendienst). Uitleg van het project staat in `README.md`,
de koppeling met TIOS in `docs/TIOS-koppeling.md`.

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

## Runs en AI-budget
- De dagelijkse run start rond 06:15. Het gratis Gemini-tegoed wordt om 09:00 Nederlandse tijd opnieuw
  gevuld. Is het tegoed op, dan stopt de run; de volgende gaat verder waar hij stopte (`data/voortgang.json`).
- Per gemeente staat het resultaat in de log van de stap "Regelingen ophalen en voorwaarden uitlezen":
  ✅ ⚠️ ➖ ❌ 🛑. Op de Summary-pagina van de run staat een tabel.

## Testen
- `node --test tests/*.test.js` (rekenregels en checkservice)
- `python -m unittest discover tests` (opschonen, verdergaan na onderbreking, internetregelingen).
  Er is geen sleutel nodig: Gemini, het CVDR en de websites worden nagebootst.
- De workflow "Tests" draait beide bij elke pull request.
