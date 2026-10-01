"""
Export voor TIOS (of een ander systeem): schrijft na elke run de map tios/ met

  tios/subsidies.json   per gemeente de conclusie + alle open regelingen met voorwaarden.
                        Samen met subsidiecheck.js is dit alles wat een koppeling nodig heeft.
  tios/regelingen.csv   één rij per open regeling, voorwaarden in losse kolommen (import/Excel).
  tios/gemeenten.csv    alle gemeenten met de conclusie (import/Excel).

CSV: puntkomma als scheidingsteken en UTF-8 met BOM, zodat Excel het meteen goed opent.
Zie docs/TIOS-koppeling.md. Draait vanzelf aan het eind van scraper/run.py; los:
  python scraper/export_tios.py
"""
import csv
import datetime as dt
import json
import pathlib

VERSIE = 1
VELDEN = ["id", "gemeente", "provincie", "naam", "type", "bedrag", "looptijd_start", "looptijd_eind", "status",
          "bron", "betrouwbaarheid", "gecontroleerd", "bron_url", "peildatum", "aanvragen", "aanvraagloket",
          "inkomensgrens", "stapelbaar_isde", "budgetstatus", "maatregelen", "criteria"]


def _lees(p, standaard):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else standaard


def is_open(r, vandaag):
    if str(r.get("status")).lower() == "gesloten":
        return False
    eind = str(r.get("looptijd_eind") or "")[:10]
    return not (eind and eind < vandaag)


def _tekst(v):
    if v is None or v == "" or v == [] or v == {}:
        return ""
    if isinstance(v, bool):
        return "ja" if v else "nee"
    if isinstance(v, list):
        return ", ".join(_tekst(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_tekst(x)}" for k, x in v.items() if _tekst(x))
    return str(v)


def _eur(x):
    try:
        return f"€ {float(x):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(x)


def _bedrag(b):
    """Het model geeft het bedrag soms als {max, min, percentage} in plaats van een zin."""
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        return _eur(b)
    if isinstance(b, dict):
        d = [f"max. {_eur(b['max'])}" if b.get("max") is not None else "",
             f"min. {_eur(b['min'])}" if b.get("min") is not None else "",
             f"{b['percentage']}%" if b.get("percentage") is not None else ""]
        return ", ".join(x for x in d if x) or _tekst(b)
    return _tekst(b)


def _isolatie(c):
    """Isolatiestaat als korte tekst: 'label D/E/F/G | min. 2 slechte bouwdelen' (| = of)."""
    iso = c.get("isolatiestaat")
    if not isinstance(iso, dict) or not iso.get("regels"):
        return ""
    delen = []
    for r in iso["regels"]:
        d = []
        if r.get("labels"):
            d.append("label " + "/".join(r["labels"]))
        if r.get("bouwjaar_max") is not None:
            d.append(f"bouwjaar t/m {r['bouwjaar_max']}")
        if r.get("bouwjaar_min") is not None:
            d.append(f"bouwjaar vanaf {r['bouwjaar_min']}")
        if r.get("bouwdelen_min") is not None:
            d.append(f"min. {r['bouwdelen_min']} slechte bouwdelen")
        delen.append(" + ".join(d))
    return " | ".join(delen)


def _csv(pad, rijen):
    with pad.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rijen[0].keys()) if rijen else ["leeg"], delimiter=";")
        w.writeheader()
        w.writerows(rijen)


def schrijf(root, vandaag=None):
    root = pathlib.Path(root)
    vandaag = vandaag or dt.date.today().isoformat()
    regelingen = _lees(root / "regelingen.json", [])
    zoekstatus = _lees(root / "zoekstatus.json", {}).get("gemeenten", [])
    uit = root / "tios"
    uit.mkdir(exist_ok=True)

    open_regs = [{k: r.get(k) for k in VELDEN if r.get(k) is not None}
                 for r in regelingen if is_open(r, vandaag)]
    per_gemeente = {}
    for r in regelingen:
        per_gemeente.setdefault(r["gemeente"], []).append(r)

    gemeenten = {}
    for z in zoekstatus:
        regs = per_gemeente.get(z["gemeente"], [])
        open_ = [r for r in regs if is_open(r, vandaag)]
        wacht = len(z.get("wacht_op_uitlezen") or [])
        conclusie = ("regeling" if open_ else "wacht_op_uitlezen" if wacht
                     else "alleen_gesloten" if regs else "geen_regeling")
        gemeenten[z["gemeente"]] = {
            "provincie": z.get("provincie"), "conclusie": conclusie,
            "regelingen": [r["id"] for r in open_], "wacht_op_uitlezen": wacht,
            "cvdr_gecheckt": z.get("cvdr_gecheckt"),
        }

    (uit / "subsidies.json").write_text(json.dumps({
        "versie": VERSIE,
        "bijgewerkt": vandaag,
        "uitleg": ("Open gemeentelijke isolatieregelingen met voorwaarden. Toetsen met subsidiecheck.js: "
                   "SubsidieCheck.check(klant, data.regelingen, {zoekstatus: data}). "
                   "Indicatief, geen toezegging; controleer altijd de bron_url."),
        "gemeenten": gemeenten,
        "regelingen": open_regs,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    rijen = []
    for r in open_regs:
        c = r.get("criteria") or {}
        rijen.append({
            "gemeente": r.get("gemeente"), "regeling": r.get("naam"), "id": r.get("id"),
            "bedrag": _bedrag(r.get("bedrag")), "aanvragen_tm": r.get("looptijd_eind") or "",
            "eigenaar_bewoner": _tekst(c.get("eigenaar_bewoner")),
            "woz_max": c.get("woz_max") if c.get("woz_max") is not None else "",
            "woz_regel": {"lte": "<=", "lt": "<"}.get(c.get("woz_regel"), ""),
            "woz_peildatum": c.get("woz_peildatum") or "",
            "isolatiestaat": _isolatie(c),
            "bouwjaar_min": c.get("bouwjaar_min") or "", "bouwjaar_max": c.get("bouwjaar_max") or "",
            "woonoppervlak_max": c.get("woonoppervlak_max") or "",
            "inkomen": c.get("inkomen") or "", "inkomensgrens": _tekst(r.get("inkomensgrens")),
            "vve_appartement": c.get("vve") or "",
            "bron": r.get("bron") or "cvdr", "betrouwbaarheid": r.get("betrouwbaarheid") or "",
            "gecontroleerd": _tekst(r.get("gecontroleerd")), "link": r.get("bron_url") or "",
        })
    _csv(uit / "regelingen.csv", rijen)
    _csv(uit / "gemeenten.csv", [{"gemeente": g, "provincie": v["provincie"] or "", "conclusie": v["conclusie"],
                                  "open_regelingen": len(v["regelingen"]), "wacht_op_uitlezen": v["wacht_op_uitlezen"]}
                                 for g, v in sorted(gemeenten.items())])
    print(f"TIOS-export: {len(open_regs)} open regelingen, {len(gemeenten)} gemeenten → tios/")


if __name__ == "__main__":
    schrijf(pathlib.Path(__file__).resolve().parent.parent)
