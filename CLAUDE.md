# CLAUDE.md – Subsidie_Checker (Takkenkamp)

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
   AI-filter (Flash-Lite) → AI-extractie (`scraper/prompt_extractie.md`).
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
   De dagelijkse workflow maakt een PR "Subsidie-update". Pas na het mergen ziet de binnendienst het.

## De grootste rem: het AI-tegoed
Met een gratis Gemini-sleutel is het tegoed na een paar dozijn aanroepen op (429). Dan schakelt `llm()` over
naar de **reserve-aanbieders** (`reserve_aanbieders` in de config), op volgorde: eigen Ollama (als die draait),
**Mistral** (aanrader: gratis sleutel `MISTRAL_API_KEY`, ~1 miljard tokens per maand), Cerebras, dan aanbieders zonder
sleutel met zeer lage limieten (LLM7.io, Pollinations, OVHcloud), dan Groq en OpenRouter. Zonder secret wordt een
aanbieder overgeslagen. Is de hoofdaanbieder op, dan wordt hij de rest van de run niet meer geprobeerd (`HOOFD_OP`).
GitHub Models is per 30-7-2026 gestopt. Te lange tekst voor een aanbieder → de volgende; zoeken met Google kan alleen Gemini.
Een **open model** (Ollama, standaard Qwen 2.5 7B) kan op de runner zelf draaien: vinkje *lokaal_model* of
repository-variabele `LOKAAL_MODEL=true`. Geen sleutel en geen limiet, wel traag (geen grafische kaart).
Ollama op een eigen server met grafische kaart: zet `OLLAMA_URL`.
Is alles op, dan stopt de run en gaat hij de volgende dag verder (`data/voortgang.json`). Daarom: zoeken zonder AI waar het kan, AI alleen voor
uitlezen, en nooit opnieuw uitlezen wat niet veranderd is. Een betaalde sleutel (enkele euro's per maand) maakt
een volle ronde in één à twee dagen mogelijk. Zie `_uitleg_limieten` in de config.

## Afspraken
- Alles in **gewoon Nederlands**: code-commentaar, logregels, PR-teksten, documentatie. Korte zinnen.
- Wijzig het extractieformaat niet zonder `normaliseer.py`, `subsidiecheck.js`, `export_tios.py` en de tests mee te nemen.
- Velden in `regelingen.json` die mensen zetten (`gecontroleerd`, `handmatig: true`) laat de scraper met rust.
- Wordt een filter ruimer, verhoog dan `FILTER_VERSIE`. Verandert het zoeken op internet, verhoog dan `WEB_VERSIE`
  (dan wordt alles opnieuw bekeken).
- Geen API-sleutels of klantgegevens in de repo; de repo en de checkpagina zijn openbaar.
- Bestanden die de scraper maakt (`regelingen.json`, `zoekstatus.json`, de xlsx, `tios/`, `data/`) niet met de hand
  aanpassen in een code-PR. Die komen uit de PR "Subsidie-update".

## Testen
- `python -m unittest discover tests` en `node --test tests/*.test.js` (draaien ook bij elke PR).
  Internet en taalmodel worden in de tests nagebootst (`tests/test_webbronnen.py`, `tests/test_web_run.py`).
- Echt testen: tabblad Actions → *Subsidies bijwerken* → Run workflow, met een paar gemeenten,
  **proef** aan (geen PR, uitkomst als download) en eventueel **zonder AI** (alleen zoeken, kost geen tegoed)
  of **aanbieder** `llm7` (meteen de gratis reserve zonder sleutel, zonder Gemini).
  Lokaal: `python scraper/run.py --zonder-ai --alleen Zeist`.
