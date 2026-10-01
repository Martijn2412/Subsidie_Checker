"""
Maakt de uitkomst van het taalmodel netjes en voorspelbaar, zodat de checkpagina en
TIOS er zonder uitzonderingen mee kunnen rekenen.

- Getallen als getal: "500000", "€ 390.000" of 477000.0 wordt 477000 (WOZ, bouwjaar, m²).
- Ja/nee als true/false: eigenaar_bewoner "ja" wordt true.
- Energielabels in hoofdletters, "geen" klein.
- "Slecht geïsoleerde woning volgens de Regeling SPUK LAI" zonder regels: de landelijke
  definitie invullen (label D t/m G, of een vergelijkbare staat = min. 2 slechte bouwdelen).

Draait automatisch in scraper/run.py. Los gebruiken (bijv. na handmatig bewerken):
  python scraper/normaliseer.py            regelingen.json in de hoofdmap bijwerken
"""
import json
import pathlib
import re
import sys

GETAL_VELDEN = ["woz_max", "bouwjaar_min", "bouwjaar_max", "woonoppervlak_max"]
REGEL_GETALLEN = ["bouwdelen_min", "bouwjaar_min", "bouwjaar_max"]
SPUK_REGELS = [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}]


def getal(x):
    """'€ 390.000,-' -> 390000, '500000' -> 500000, 477000.0 -> 477000. Onleesbaar: None."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(x) if float(x).is_integer() else x
    s = str(x).strip()
    m = re.search(r"\d[\d.,\s]*", s)
    if not m:
        return None
    t = re.sub(r"\s", "", m.group(0)).rstrip(".,")
    t = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", t)  # duizendtallen: 390.000 / 390,000
    t = t.replace(",", ".")
    try:
        n = float(t)
    except ValueError:
        return None
    if re.search(r"\b(mln|miljoen)\b", s, re.I):
        n *= 1_000_000
    return int(n) if n.is_integer() else n


def ja_nee(x):
    if isinstance(x, bool) or x is None:
        return x
    s = str(x).strip().lower()
    if s in ("ja", "j", "true", "yes", "1"):
        return True
    if s in ("nee", "n", "false", "no", "0"):
        return False
    return x  # bijv. een toelichting: laten staan


def label(x):
    s = str(x).strip()
    return "geen" if s.lower().startswith("geen") else s.upper()


def normaliseer(rec):
    """Geeft dezelfde regeling terug met opgeschoonde criteria (past rec niet aan)."""
    c = rec.get("criteria")
    if not isinstance(c, dict):
        return rec
    c = dict(c)
    for v in GETAL_VELDEN:
        if c.get(v) is not None:
            n = getal(c[v])
            if n is None:
                print(f"  let op: {rec.get('id')}: {v}={c[v]!r} is geen getal, weggelaten")
            c[v] = n
    if "eigenaar_bewoner" in c:
        c["eigenaar_bewoner"] = ja_nee(c["eigenaar_bewoner"])
    if isinstance(c.get("woz_regel"), str):
        c["woz_regel"] = c["woz_regel"].strip().lower()
    for v in ("inkomen", "vve"):
        if isinstance(c.get(v), str):
            c[v] = c[v].strip().lower() or None
    iso = c.get("isolatiestaat")
    if isinstance(iso, dict):
        iso = dict(iso)
        regels = []
        for r in iso.get("regels") or []:
            if not isinstance(r, dict):
                continue
            r = dict(r)
            if r.get("labels"):
                r["labels"] = [label(x) for x in r["labels"]]
            for v in REGEL_GETALLEN:
                if r.get(v) is not None:
                    r[v] = getal(r[v])
            regels.append(r)
        if not regels and re.search(r"\bSPUK\b", iso.get("omschrijving") or "", re.I):
            regels = [dict(x) for x in SPUK_REGELS]
            iso["afgeleid"] = ("Definitie 'slecht geïsoleerde woning' uit de Regeling SPUK Lokale Aanpak Isolatie: "
                               "label D t/m G, of een vergelijkbare energetische staat (gangbaar: min. 2 slechte bouwdelen).")
        iso["regels"] = regels
        c["isolatiestaat"] = iso
    return {**rec, "criteria": c}


if __name__ == "__main__":
    pad = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent / "regelingen.json"
    oud = json.loads(pad.read_text(encoding="utf-8"))
    nieuw = [normaliseer(r) for r in oud]
    anders = sum(1 for a, b in zip(oud, nieuw) if a != b)
    pad.write_text(json.dumps(nieuw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{pad.name}: {anders} van {len(nieuw)} regelingen bijgewerkt")
