# Vergelijking model vs. handmatig (2026-09-22)

## Doesburg – CVDR743563
- bedrag: handmatig "100% van de subsidiabele kosten, max. €2.000 per adres. Extra bij bio-based materiaal per m²: dak €5, zolder-/vlieringvloer €1,50, spouwmuur €1,50, gevel €6, vloer €2, bodem €1." | model "100% van de subsidiabele kosten met een maximum van €2.000,- per adres. Aanvullend voor bio-based: dakisolatie €5/m², zolder-/vlieringvloerisolatie €1,50/m², spouwmuurisolatie €1,50/m², gevelisolatie €6/m², vloerisolatie €2/m², bodemisolatie €1/m²"
- aanvragen: handmatig "Aanvraag met offerte of kostenindicatie via het portaal; na verlening 12 maanden om uit te voeren. Maatregelen uitgevoerd op of na 1-1-2025 komen in aanmerking." | model "vooraf"
- inkomensgrens: handmatig "geen" | model null
- stapelbaar_isde: handmatig "niet geregeld in de regelingstekst" | model null
- criteria.bouwjaar_opmerking: handmatig null | model "Bijlage 1 noemt slechts indicatieve bouwjaren per bouwdeel, geen harde bouwjaareis voor de woning"
- criteria.isolatiestaat: handmatig {"omschrijving": "Geregistreerd label D, E, F of G, of min. 2 bestaande bouwdelen niet/slecht geïsoleerd", "regels": [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}]} | model {"omschrijving": "Geregistreerd energielabel D of lager (E, F, of G) of minimaal 2 bestaande bouwdelen niet of slecht geïsoleerd conform bijlage 1", "regels": [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}]}
- criteria.woz_peildatum: handmatig "1-1-2024" | model "2024-01-01"

## Doetinchem – CVDR744251
- bedrag: handmatig "max. €2.000" | model {"max": 2000}
- aanvragen: handmatig "Aanvraag met offerte of kostenindicatie via het portaal; na verlening 12 maanden om uit te voeren. Maatregelen uitgevoerd na 1-1-2024 komen in aanmerking." | model "vooraf"
- inkomensgrens: handmatig "geen" | model null
- stapelbaar_isde: handmatig "niet geregeld in de regelingstekst" | model null
- criteria.isolatiestaat: handmatig {"omschrijving": "Geregistreerd label D, E, F of G, of min. 2 bestaande bouwdelen niet/slecht geïsoleerd", "regels": [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}]} | model {"omschrijving": "een woning met een geregistreerd energielabel D of lager (E, F, of G) of minimaal 2 van de bestaande bouwdelen niet of slecht geïsoleerd", "regels": [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}]}
- criteria.woz_peildatum: handmatig "1-1-2024" | model "2024-01-01"

## Apeldoorn – CVDR724051
- bedrag: handmatig "Via aannemer: inkomen onder 150% sociaal minimum max. €2.000 per woning (aanvragen vanaf 1-1-2026); inkomen boven 150% max. €1.000; buiten bebouwde kom met WOZ boven €477.000 max. €1.000; collectief (min. 3 buren) max. €1.500. Doe-het-zelf max. €1.000. Nooit meer dan de kosten." | model "Maximaal € 6.000 (inkomen < 150% sociaal minimum tot 31-12-2025; daarna € 2.000; € 4.000 bij eerdere subsidie); maximaal € 1.000 (inkomen > 150% sociaal minimum of buiten bebouwde kom); maximaal € 1.500 bij collectieve aanvraag; maximaal € 1.000 voor doe-het-zelvers"
- looptijd_eind: handmatig "2026-10-30" | model "2026-12-31"
- aanvragen: handmatig "Inkomen onder 150%: vóór uitvoering, met energieadviseur van de gemeente en 2 offertes per maatregel. Overige: vooraf of achteraf (achteraf binnen 1 jaar na uitvoering)." | model "vooraf of achteraf"
- inkomensgrens: handmatig "Hoger bedrag bij inkomen onder 150% van het sociaal minimum (peildatum: maand vóór de aanvraag)" | model "150% van het sociaal minimum"
- stapelbaar_isde: handmatig "ja (toelichting: ISDE wordt eerst verrekend)" | model true
- criteria.bouwjaar_opmerking: handmatig null | model "Bouwjaar van 1995 of ouder geldt alleen als voorwaarde bij energielabel B of C om als slecht geïsoleerd te worden aangemerkt"
- criteria.isolatiestaat: handmatig {"omschrijving": "Label D–G, óf geen label + min. 2 slechte bouwdelen, óf label B/C + bouwjaar t/m 1995 + min. 2 slechte bouwdelen", "regels": [{"labels": ["D", "E", "F", "G"]}, {"labels": ["geen"], "bouwdelen_min": 2}, {"labels": ["B", "C"], "bouwjaar_max": 1995, "bouwdelen_min": 2}]} | model {"omschrijving": "Koopwoning met label D, E, F, G; of zonder label en minstens twee slecht geïsoleerde bouwdelen; of met label B of C, bouwjaar 1995 of ouder, en minstens twee slecht geïsoleerde bouwdelen", "regels": [{"labels": ["D", "E", "F", "G"]}, {"labels": ["geen"], "bouwdelen_min": 2}, {"labels": ["B", "C"], "bouwjaar_max": 1995, "bouwdelen_min": 2}]}
- criteria.vve_opmerking: handmatig "Alleen grondgebonden woningen; voor VvE's volgt later een regeling" | model "Alleen grondgebonden woningen komen in aanmerking; VvE's gaan op een later moment open"
- criteria.woz_peildatum: handmatig "1-1-2022" | model "2022-01-01"
- criteria.woz_uitzondering: handmatig "Buiten de bebouwde kom geldt geen WOZ-grens (dan max. €1.000)" | model "Buiten de bebouwde kom geldt geen WOZ-maximum (maximaal 20% van de toekenningen)"

## Arnhem – CVDR759969
- bedrag: handmatig "100% van de kosten, max. €2.300: max. €1.700 isolatietegoed plus max. €600 bonustegoed (biobased en/of max. €300 hulp Buurtklusbedrijf)" | model "maximaal € 2.300,-"
- looptijd_eind: handmatig "2030-12-31" | model "2031-01-01"
- aanvragen: handmatig "vóór uitvoering; na de beschikking 1 jaar om uit te voeren" | model "vooraf"
- inkomensgrens: handmatig "geen (wel ruimere WOZ-grens bij schulden of GelrePas)" | model null
- stapelbaar_isde: handmatig "niet geregeld in de regelingstekst" | model null
- criteria.isolatiestaat: handmatig null | model {"omschrijving": "Een woning met Energielabelklasse D, E, F, G of een vergelijkbare energetische staat waarin ten minste twee bouwdelen niet of slecht geïsoleerd zijn.", "regels": [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}]}
- criteria.vve_opmerking: handmatig "Alleen grondgebonden woningen en woonboten" | model "Alleen grondgebonden woningen en woonboten komen in aanmerking; appartementen/VvE zijn uitgesloten."
- criteria.woz_peildatum: handmatig "peiljaar 2022" | model "2022-01-01"
- criteria.woz_uitzondering: handmatig "Max. €477.000 (peiljaar 2024) bij schuldhulpverlening, GelrePas, Energiebank-traject of Bijzondere Bijstand Hoge Energiekosten" | model "De WOZ-waarde is in peiljaar 2024 maximaal € 477.000,- indien de aanvrager in aanmerking komt voor schuldhulpverlening, schuldsanering, een GelrePas heeft, in een traject zit van de Energiebank met energiearmoede, of de afgelopen 2 jaar Bijzondere Bijstand Hoge Energiekosten ontving."

## Extra gevonden door de scraper
- Apeldoorn: Subsidieregeling Woningisolatie gemeente Apeldoorn deel 3 (CVDR703804)
- Arnhem: Kleine Woning Aanpak Subsidie (KWAS) (CVDR692728)
- Arnhem: Maatregelenlijst Toekomstbestendig Wonen Lening gemeente Arnhem (CVDR755037)
- Arnhem: Regeling duurzaamheidsleningen Arnhem 2018 (CVDR609449)
- Arnhem: Subsidieregeling Eigen Woning Aanpak Arnhem-Oost 2.0 (CVDR714847)
- Arnhem: Subsidieregeling Isolatie Subsidie Arnhem (ISA) (CVDR738986)
- Arnhem: Subsidieregeling woningeigenaren Elderveld Noord (SWEN) (CVDR701280)
- Bronckhorst: Subsidiebeleidsregels Bloemenbuurt Zelhem 2021 - 2031 (CVDR682026)
- Bronckhorst: Subsidieregeling Isolatie Subsidie Achterhoek – Bronckhorst 2025 (CVDR743293)
- Bronckhorst: Verordening Duurzaamheidslening gemeente Bronckhorst 2017 (CVDR467088)
- Doesburg: Subsidieregeling Isolatiesubsidie laag inkomen Achterhoek (CVDR757582)
- Doesburg: Subsidieverordening aardgasvrij of aardgasvrij-klaar 2024 - 2028 (CVDR723930)
- Doesburg: Verordening ‘Toekomstbestendig Wonen Gelderland, gemeente Doesburg 2025’ (CVDR749101)
- Doetinchem: Subsidieregeling Woningisolatie De Happert-Leerinkstraat, De IJkenberg en De Bezelhorst (CVDR745517)
- Doetinchem: Subsidieregeling toekomstbestendige particuliere woningen Overstegen - west, Muziekbuurt en Schrijvers en dichtersbuurt 2023-2031 (CVDR719693)
- Doetinchem: Subsidieregeling “Isolatiesubsidie laag inkomen” (CVDR758159)
- Doetinchem: Subsidieverordening Achterhoek Bespaart 2016 (CVDR407463)
- Zutphen: Tijdelijke subsidieregeling energetische woningverbetering voor eigenaar-bewoners in energiearmoede gemeente Zutphen 2022-2027 II (CVDR741234)
- Zutphen: Tijdelijke subsidieregeling lokale aanpak isolatie koopwoningen gemeente Zutphen 2024-2028-II (CVDR758825)
- Zutphen: Verordening Toekomstbestendig Wonen Gelderland gemeente Zutphen 2025 (CVDR751546)
