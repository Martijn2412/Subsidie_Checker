# Subsidiecheck isolatie (Takkenkamp)

Checkpagina voor de binnendienst plus een scraper die elke dag de gemeentelijke
isolatieregelingen van álle gemeenten ophaalt uit het CVDR (lokaleregelgeving.overheid.nl)
en, als daar niets staat, met AI zoekt op internet.

## Wat zit waar
| Bestand | Wat het doet |
|---|---|
| `index.html` | De checkpagina. Laadt automatisch `regelingen.json`. |
| `regelingen.json` | Alle regelingen met voorwaarden. Dit is wat de binnendienst ziet. |
| `zoekstatus.json` | Per gemeente: wat in het CVDR nog wacht op uitlezen en wanneer er op internet is gezocht. |
| `scraper/run.py` | Zoekt, leest en extraheert de regelingen. |
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

## Hoe het werkt (per gemeente)
1. **Snel zoeken in het CVDR** voor alle ± 340 gemeenten (lijst via PDOK).
2. **Gevonden?** Het taalmodel leest de voorwaarden uit. Daarna wordt alleen
   opnieuw gelezen wat in het CVDR verandert. Lukt iets niet (limiet of tijd op),
   dan volgt het bij de volgende run.
3. **Niets relevants in het CVDR?** Dan zoekt het taalmodel op internet (vooral de
   gemeentesite). Per gemeente hooguit eens per 30 dagen.
   Zulke regelingen hebben `"bron": "web"` en betrouwbaarheid "laag": altijd controleren.

De limieten in `scraper/config.json` staan ingesteld op een **betaalde** API-sleutel
(alles in één run). Gratis sleutel? Zie `_uitleg_limieten` in dat bestand.

## Elke dag
De scraper draait automatisch. Is er iets nieuw of gewijzigd, dan krijg je een
pull request met de wijzigingen in gewone taal. Controleer ze tegen de bronlink,
zet bij goedgekeurde regelingen `"gecontroleerd": true` en merge. Pas dan ziet de
binnendienst de wijziging. Niets gewijzigd? Dan komt er geen pull request.

Regelingen die niet in het CVDR staan (zoals SAAK Doesburg) zet je zelf in
`regelingen.json` met `"handmatig": true`. De scraper laat die met rust.
