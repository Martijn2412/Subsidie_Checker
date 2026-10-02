# Subsidiecheck isolatie (Takkenkamp)

Checkpagina voor de binnendienst plus een scraper die elke dag de isolatieregelingen van álle
gemeenten zoekt: in het CVDR (lokaleregelgeving.overheid.nl), op de eigen gemeentesite en bij
partners zoals energieloketten. De voorwaarden komen in `overzicht_voorwaarden.xlsx`.
Het doel en de afspraken staan in `CLAUDE.md`.

## Wat zit waar
| Bestand | Wat het doet |
|---|---|
| `index.html` | De checkpagina. Laadt automatisch `regelingen.json`. |
| `regelingen.json` | Alle regelingen met voorwaarden. Dit is wat de binnendienst ziet. |
| `overzicht_voorwaarden.xlsx` | Alles in één sheet: blad *Regelingen* (voorwaarden per regeling, geel = via AI) en blad *Gemeenten* (alle gemeenten met conclusie). Ook te downloaden via de knop op de checkpagina. Alleen om te lezen: wordt elke run opnieuw gemaakt. |
| `zoekstatus.json` | Per gemeente: wat in het CVDR nog wacht op uitlezen en wanneer er op internet is gezocht. |
| `scraper/run.py` | Zoekt, leest en extraheert de regelingen. |
| `scraper/webbronnen.py` | Zoekt buiten het CVDR: gemeentesite (sitemap), partners, pdf's, AI-zoekactie met Google; controleert het bewijs van het model. |
| `scraper/normaliseer.py` | Schoont de uitkomst van het model op (WOZ als getal, ja/nee als true/false). |
| `scraper/export_tios.py` | Schrijft na elke run de map `tios/` voor de koppeling met TIOS. |
| `subsidiecheck.js` | De rekenregels: klantgegevens erin, oordeel + één regel tekst eruit. Gebruikt door de checkpagina én bedoeld voor TIOS. |
| `tios/` | `subsidies.json`, `regelingen.csv`, `gemeenten.csv`: alles wat TIOS nodig heeft. Zie `docs/TIOS-koppeling.md`. |
| `docs/verbeterplan.md` | Wat er nog beter kan, op volgorde van belang. |
| `scraper/config.json` | Instellingen: alle gemeenten aan/uit, trefwoorden, modellen, limieten. |
| `scraper/prompt_extractie.md` | De opdracht aan Claude. Hier schaaf je bij als het model iets verkeerd leest. |
| `tests/baseline_pilot.json` | Handmatig gecontroleerde pilotdata (4 gemeenten) om het model tegen te testen. |
| `data/` | Logboek (`wijzigingen.md`), vergelijking, dekking per gemeente, interne status. |

## Eenmalig instellen
1. Maak een nieuwe (private) repo en upload alle bestanden, inclusief de map `.github`.
2. Settings → Secrets and variables → Actions → New repository secret:
   naam `GEMINI_API_KEY`, waarde je sleutel van aistudio.google.com (gratis).
   Liever Claude? Zet `"provider": "claude"` in `scraper/config.json` en maak het
   secret `ANTHROPIC_API_KEY` aan.
3. Settings → Actions → General → Workflow permissions: kies "Read and write" en
   vink "Allow GitHub Actions to create and approve pull requests" aan.
4. Settings → Pages → Deploy from a branch → `main`, map `/ (root)`.
   Let op: bij een private repo kan Pages een betaald GitHub-abonnement vereisen.
5. Tabblad Actions → "Subsidies bijwerken" → Run workflow (eerste testrun). Bij "gemeenten"
   kun je een paar namen invullen (bijv. `Doesburg,Arnhem`) voor een snelle test; leeg = alles.
   Vink **proef** aan voor een test zonder pull request (de uitkomst staat als download bij de run),
   en **zonder AI** om alleen het zoeken te testen zonder AI-tegoed te gebruiken.

## Hoe het werkt (per gemeente)
1. **CVDR**: zoeken met de trefwoorden uit `scraper/config.json` voor alle ± 340 gemeenten (lijst via PDOK).
   Gevonden regelingen leest het taalmodel uit. Daarna wordt alleen opnieuw gelezen wat in het CVDR verandert.
2. **Gemeentesite en partners** (elke gemeente, eens per 14 dagen): de scraper zoekt het webadres van de
   gemeente op in het Register van Overheidsorganisaties, leest de sitemap en kiest de pagina's die over
   subsidie of isolatie gaan. Daarnaast kijkt hij bij partners (Regionaal Energieloket, Duurzaam Bouwloket,
   WoonWijzerWinkel, Isolatieloket; uit te breiden in `partners` in de config). Links naar voorwaarden en
   pdf's worden gevolgd. Dit alles kost geen AI.
3. **AI-zoekactie met Google**: alleen als stap 2 niets oplevert of de gemeente nog geen open regeling heeft.
   De links die Google echt gaf worden gebruikt, niet wat het model zelf noemt.
4. Alle gevonden pagina's van een gemeente gaan samen in één AI-aanroep, en alleen als de tekst veranderd is.
   Staat dezelfde regeling al in het CVDR, dan komt de pagina bij "Ook vermeld op".
5. **Controle op verzinnen**: het model geeft per veld een zinsdeel als bewijs. Staat dat niet in de brontekst,
   dan gaat de betrouwbaarheid omlaag en staat het in de pull request.
   Regelingen van internet hebben `"bron": "web"` en zijn geel in de Excel: altijd controleren.

In de Excel (blad *Gemeenten*) zie je per gemeente waar is gezocht. "Nog niet volledig gezocht" betekent dat
alleen het CVDR is bekeken; de rest volgt bij een volgende run.

**Geen of te weinig AI-tegoed?** Is Gemini op, dan gaat de scraper vanzelf verder met gratis aanbieders
zonder sleutel (LLM7.io, Pollinations, OVHcloud; lage limieten) en met andere gratis aanbieders waarvan je een sleutel als secret zet:
`CEREBRAS_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` (aanmaken op hun site, zonder
creditcard). Zie `reserve_aanbieders` in `scraper/config.json`.

De limieten in `scraper/config.json` staan ingesteld op een **betaalde** API-sleutel
(alles in één run). Gratis sleutel? Zie `_uitleg_limieten` in dat bestand.

## Elke dag
De scraper draait automatisch. Is er iets nieuw of gewijzigd, dan krijg je een
pull request met de wijzigingen in gewone taal. Controleer ze tegen de bronlink,
zet bij goedgekeurde regelingen `"gecontroleerd": true` en merge. Pas dan ziet de
binnendienst de wijziging. Niets gewijzigd? Dan komt er geen pull request.

Nog niet gemerged? Geen probleem: de volgende run gaat verder op de openstaande
Subsidie-update en voegt zijn wijzigingen daaraan toe. Er gaat geen werk verloren.

Is het AI-budget of de daglimiet op, dan stopt de run meteen.
Stopt een run halverwege (budget op, crash, tijd op, handmatig geannuleerd)? Ook dan gaat er weinig
verloren: de run slaat elke 5 minuten tussentijds op, stopt zelf netjes na 5 uur
(`max_minuten_run` in `scraper/config.json`) en maakt toch een pull request met wat hij
gedaan heeft. De volgende run begint bij de gemeente waar hij stopte (`data/voortgang.json`).
Dat geldt ook als je hem zelf start via Run workflow met het veld "gemeenten" leeg.

Regelingen die niet in het CVDR staan (zoals SAAK Doesburg) zet je zelf in
`regelingen.json` met `"handmatig": true`. De scraper laat die met rust.
