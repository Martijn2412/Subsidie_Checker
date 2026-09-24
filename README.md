# Subsidiecheck isolatie (Takkenkamp)

Checkpagina voor de binnendienst plus een scraper die elke dag de gemeentelijke
isolatieregelingen ophaalt uit het CVDR (lokaleregelgeving.overheid.nl).

## Wat zit waar
| Bestand | Wat het doet |
|---|---|
| `index.html` | De checkpagina. Laadt automatisch `regelingen.json`. |
| `regelingen.json` | Alle regelingen met voorwaarden. Dit is wat de binnendienst ziet. |
| `scraper/run.py` | Zoekt, leest en extraheert de regelingen. |
| `scraper/config.json` | Welke gemeenten, trefwoorden en modellen. Gemeente toevoegen = hier. |
| `scraper/prompt_extractie.md` | De opdracht aan Claude. Hier schaaf je bij als het model iets verkeerd leest. |
| `notebooks/voorwaarden_scraper.ipynb` | Zoekt isolatiesubsidies op de websites van alle gemeenten (en energieloketten, pdf's) en leest de voorwaarden uit. Draait in Colab of via GitHub Actions. |
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
5. Tabblad Actions → "Subsidies bijwerken" → Run workflow (eerste testrun).

## Elke dag
De scraper draait automatisch. Is er iets nieuw of gewijzigd, dan krijg je een
pull request met de wijzigingen in gewone taal. Controleer ze tegen de bronlink,
zet bij goedgekeurde regelingen `"gecontroleerd": true` en merge. Pas dan ziet de
binnendienst de wijziging. Niets gewijzigd? Dan komt er geen pull request.

Regelingen die niet in het CVDR staan (zoals SAAK Doesburg) zet je zelf in
`regelingen.json` met `"handmatig": true`. De scraper laat die met rust.

## Gemeentewebsites scrapen (Colab of GitHub)
Niet elke gemeente zet haar isolatiesubsidie in het CVDR. `notebooks/voorwaarden_scraper.ipynb`
zoekt daarom op de websites van alle gemeenten (sitemap, zoekfunctie, gelinkte pdf's en energieloketten)
en laat Gemini de voorwaarden uitlezen met dezelfde prompt als `scraper/run.py`.

- **Colab**: open de notebook in Colab, zet onder 🔑 *Secrets* `GEMINI_API_KEY` en kies *Alles uitvoeren*.
  Bestanden komen in Drive, map `MyDrive/subsidie_checker`. Is de repo privé, zet dan ook
  `prompt_extractie.md` en `config.json` in die map.
- **GitHub**: workflow *Webpagina's gemeenten scrapen* draait elke nacht (of via Actions → Run workflow,
  eventueel met alleen een paar gemeenten). Elke run gaat verder waar de vorige stopte; resultaten komen
  als pull request in `data/web/`.

**Alle voorwaarden op één plek:** `overzicht_voorwaarden.xlsx`, één rij per regeling (website én CVDR)
met de voorwaarden in gewone taal, een klikbare bron en een kolom `gecontroleerd` die je zelf op ja zet
(blijft bewaard bij de volgende run). Blad *Dekking* toont per gemeente wat er gevonden is.

Overige uitvoer: `bronnen_sitemap.csv` (gevonden pagina's per gemeente), `voorwaarden.csv` (overzicht, ook
gemeenten zonder regeling), `regelingen_web.json` (zelfde formaat als `regelingen.json`, nog niet
gecontroleerd) en `samenvatting.md`. Controleer een regeling tegen de bron voordat je hem overneemt.
