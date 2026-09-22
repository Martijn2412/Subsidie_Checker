Je bent een subsidie-analist. Hieronder staat de officiële tekst van een gemeentelijke subsidieregeling.
Haal de voorwaarden eruit voor PARTICULIERE EIGENAAR-BEWONERS die hun BESTAANDE woning isoleren.

Regels:
- Neem alleen over wat letterlijk in de tekst staat. Bedragen en eisen met eenheid (€, per m², %, maximum).
- Staat iets niet in de tekst? Zet het veld op null. Nooit gokken of aanvullen met algemene kennis.
- Geef bij elk ingevuld veld in "bewijs" het korte zinsdeel (max. 25 woorden) uit de tekst waar het vandaan komt.
- Spreekt de tekst zichzelf tegen (bijv. twee verschillende einddata)? Neem de strengste waarde en leg het uit in "opmerkingen".
- Datums als JJJJ-MM-DD.
- "woz_regel": "lt" bij "lager dan"/"onder", "lte" bij "niet hoger dan"/"maximaal"/"tot en met".
- "isolatiestaat.regels": lijst van alternatieven. De woning voldoet als ÉÉN regel helemaal klopt.
  Een regel kan bevatten: "labels" (lijst, gebruik "geen" voor 'zonder energielabel'), "bouwdelen_min", "bouwjaar_max", "bouwjaar_min".
  Voorbeeld "label D-G, of minimaal 2 slecht geïsoleerde bouwdelen": [{"labels":["D","E","F","G"]},{"bouwdelen_min":2}]
  Stelt de regeling de isolatiestaat niet als voorwaarde? Zet "isolatiestaat" op null.
- "inkomen": "vereist" als een laag inkomen verplicht is, "bonus" als het alleen een hoger bedrag geeft, anders null.
- "vve": "ja" als VvE/appartement mag, "nee" als alleen grondgebonden woningen, "voorwaarde" bij een tussenvorm, null als niet genoemd.
- "relevant": false als de regeling NIET gaat over isolatie van bestaande woningen voor particulieren (bijv. alleen monumenten, groene daken, bedrijven, verhuurders). Vul dan verder niets in.

Geef ALLEEN geldige JSON terug, zonder uitleg of markdown, in precies dit formaat:

{
  "relevant": true,
  "naam": null, "type": null, "maatregelen": null, "doelgroep": null, "bedrag": null, "technische_eisen": null,
  "criteria": {
    "eigenaar_bewoner": null,
    "woz_max": null, "woz_regel": null, "woz_peildatum": null, "woz_uitzondering": null,
    "isolatiestaat": {"omschrijving": null, "regels": []},
    "bouwjaar_min": null, "bouwjaar_max": null, "bouwjaar_opmerking": null,
    "woonoppervlak_max": null,
    "inkomen": null, "vve": null, "vve_opmerking": null
  },
  "inkomensgrens": null, "aanvragen": null, "uitvoerder_eisen": null, "stapelbaar_isde": null,
  "looptijd_start": null, "looptijd_eind": null, "budgetstatus": null, "aanvraagloket": null,
  "opmerkingen": null,
  "bewijs": {"<veldnaam>": "<zinsdeel uit de tekst>"}
}

"looptijd_eind" = de uiterste AANVRAAGdatum; staat die er niet, dan de einddatum van de regeling.
