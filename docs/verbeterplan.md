# Verbeterplan Subsidie_Checker (stand 1-10-2026)

Het idee: een scraper haalt alle gemeentelijke isolatieregelingen op met voorwaarden en budget.
Bij een nieuwe lead in TIOS staat onder het energielabel of de klant mogelijk recht heeft.

De basis staat. Alle 342 gemeenten zijn doorzocht, en bij 288 gemeenten (84%) kun je een klant
toetsen. Hieronder staat wat er beter kan, het belangrijkste eerst.

## Al gedaan (deze PR)
- **Eén set rekenregels** (`subsidiecheck.js`) voor de checkpagina én TIOS, plus `check()` dat één regel tekst geeft. Zie `docs/TIOS-koppeling.md`.
- **TIOS-export**: `tios/subsidies.json`, `tios/regelingen.csv` en `tios/gemeenten.csv`, na elke run.
- **Data opschonen** (`scraper/normaliseer.py`): WOZ, bouwjaar en m² altijd als getal ("€ 390.000" → 390000) en eigenaar-bewoner als ja/nee. Dat laatste was nodig: 16 regelingen hadden `"ja"` als tekst, waardoor de check op eigenaar-bewoner werd overgeslagen.
- **SPUK-definitie ingevuld** bij 14 regelingen die alleen "slecht geïsoleerde woning (SPUK LAI)" zeiden. Die zijn nu wel te toetsen: label D–G of min. 2 slechte bouwdelen.
- **Gratis tegoed beter benut**: is de daglimiet van een model op, dan probeert de scraper dat model deze run niet meer (scheelt ~80 s per regeling). Tegoed op (402) telt nu ook als limiet.
- **Niet opnieuw uitlezen** als alleen het versienummer in het CVDR verandert en de tekst gelijk blijft.
- **XML kapot (404)?** Dan probeert de scraper de gewone CVDR-pagina (Wassenaar zat hierdoor vast; bij de volgende run zien we of het werkt).
- **Bedrag "[object Object]"** op de checkpagina opgelost (52 regelingen). Gesloten regelingen staan nu onderaan.
- **Automatische tests** bij elke pull request.

## Hoog: doen
1. **Budget actueel houden.** Het CVDR noemt het plafond, maar niet of het op is. Veel regelingen stoppen
   eerder omdat het geld op is. Voorstel: één keer per maand per open regeling de gemeentepagina laten
   checken (Flash-Lite, goedkoop) op "plafond bereikt", "gesloten" of "vol". Dan wordt `budgetstatus` = `uitgeput`
   en zegt TIOS "budget op". Dit is het grootste gat tussen het idee en wat er nu staat.
2. ~~**Geen werk meer kwijt bij een ongemergde update.**~~ Gedaan: staat er een "Subsidie-update" open,
   dan gaat de volgende run daar verder (`scraper/verder_op_open_update.sh`).
3. **Leningen en "maatregelenlijsten" apart.** Er komen nu ook regelingen door zonder voorwaarden
   (bijv. Arnhem: "Maatregelenlijst Toekomstbestendig Wonen Lening"). Voorstel: `type` vast indelen
   (subsidie / lening / voucher / in natura). TIOS telt alleen subsidies en vouchers mee voor "mogelijk subsidie",
   en noemt leningen apart.
4. **Controle op verzinnen (hallucinatie).** Het model geeft per veld een "bewijs"-zinsdeel. Laat de scraper
   checken of dat zinsdeel echt in de tekst staat. Zo niet: betrouwbaarheid "middel" en in de PR melden.
   Goedkoop en vangt de meeste fouten.

## Middel
5. **Steekproef en `gecontroleerd`.** Nu staat maar bij 1 regeling `gecontroleerd: true`. Doel: de 50 gemeenten
   waar Takkenkamp de meeste klanten heeft met de hand controleren en `gecontroleerd` op true zetten.
   De baseline in `tests/baseline_pilot.json` uitbreiden van 4 naar ~30 regelingen, als vaste meetlat voor elke modelwissel.
6. **Klantgegevens in TIOS vullen.** WOZ en eigenaar-bewoner ontbreken het vaakst. Voeg twee vragen toe aan de
   intake. Bouwjaar, oppervlak en appartement/grondgebonden komen gratis uit de BAG (PDOK), het energielabel uit EP-Online.
7. **Landelijke en provinciale regelingen** als extra laag: ISDE (altijd relevant voor isolatie), Warmtefonds,
   provinciale regelingen (bijv. Gelderland "Toekomstbestendig Wonen"). Dan kan TIOS zeggen:
   "Gemeente: geen, maar ISDE: ja".
8. **Melding bij problemen.** Laat de workflow een issue of e-mail maken als een run faalt, de limiet bereikt is
   of de wachtrij een week niet kleiner wordt.

## Laag / later
9. **Gemeentelijke herindelingen** (meestal per 1 januari): oude regelingen koppelen aan de nieuwe gemeente.
   De gemeentelijst komt al automatisch van PDOK.
10. **`run.py` opsplitsen** (zoeken, filteren, uitlezen, schrijven) en tests met opgeslagen CVDR-voorbeelden,
    zodat een wijziging aan de zoekservice van de overheid meteen opvalt.
11. **Taalmodel als reserve van een andere aanbieder** (bijv. Mistral, gratis) voor als Gemini vol of overbelast is.

## Kosten
Het uitlezen van voorwaarden gebeurt door een taalmodel via een API-sleutel. Elke aanroep verbruikt tokens,
en tokens kosten geld zodra het gratis tegoed op is. Na de eerste vulling verandert er per maand maar een
handvol regelingen, dus het verbruik daalt dan sterk (filter en uitlezen alleen bij wijzigingen).

Mogelijk kan het ook zonder betaalde sleutel: met een taalmodel dat lokaal op een eigen computer draait
(bijvoorbeeld via Ollama). Dan zijn er geen tokenkosten. Nadelen:
- Het kan traag zijn. Hoe snel hangt af van de rekenkracht van de computer (vooral de videokaart).
- Die computer moet aanstaan tijdens de run; GitHub Actions kan er niet zomaar bij.
- Zoeken op internet doet het model dan niet zelf; dat moet de scraper overnemen.
- Een klein lokaal model leest voorwaarden mogelijk minder goed. Eerst testen tegen `tests/baseline_pilot.json`.

Dit is nog niet gebouwd of getest. De scraper kent nu alleen `"provider": "gemini"` en `"claude"`.

## Privacy
Met optie 2 uit `docs/TIOS-koppeling.md` gaan er geen klantgegevens naar GitHub of naar een AI-model:
TIOS haalt alleen de openbare regelingen op en rekent zelf. Zet nooit API-sleutels of klantgegevens in deze
repo of op de checkpagina; die zijn openbaar.
