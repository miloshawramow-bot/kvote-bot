#!/usr/bin/env python3
"""
Unibet klijent — Kambi feed (ista platforma pokreće Unibet, 888sport i dr.).

Javni CDN (radi bez ključa; iz Srbije i sa GitHub servera, NE iz US sandboxa):
    https://eu-offering-api.kambicdn.com/offering/v2018/ubse/listView/football.json
        ?lang=sv_SE&market=SE&channel_id=1
Struktura: events[] →
  event: {id, englishName, homeName, awayName, start (ISO), group (liga!), path[]}
  betOffers[]: {betOfferType{englishName}, criterion{label}, outcomes[]:
                {type: HOME/DRAW/AWAY/..., englishLabel, label, odds (int ×1000)}}

Marketi koje mapiramo (imena kao u Mozzart/MaxBet radi poređenja):
  "Match" (fudbal 3-way)        → Konačan ishod 1/X/2
  "Match" (košarka 2-way)       → Konačan ishod 1/2
  "Double chance"               → Dupla šansa 1X/12/X2
  "Both teams to score"         → Oba tima daju gol DA/NE
"""
import json
import time
import urllib.request
from datetime import datetime

BASE = "https://eu-offering-api.kambicdn.com/offering/v2018/ubse/listView"
UPIT = "?lang=sv_SE&market=SE&channel_id=1"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
SPORT_URL = {"fudbal": "football", "kosarka": "basketball"}

# Kambi outcome "type" → naš ishod za Match (1X2)
TIP_KI = {"OT_ONE": "1", "OT_CROSS": "X", "OT_TWO": "2",
          "HOME": "1", "DRAW": "X", "AWAY": "2"}
# Double chance: label/englishLabel može biti "1X" ili "Hem eller oavgjort" itd.
DC_NORM = {"1x": "1X", "12": "12", "x2": "X2", "1 x": "1X", "x 2": "X2"}
DC_TIP = {"OT_ONE_OT_CROSS": "1X", "OT_ONE_OT_TWO": "12", "OT_CROSS_OT_TWO": "X2",
          "HOME_DRAW": "1X", "HOME_AWAY": "12", "DRAW_AWAY": "X2",
          "OT1_OT2": "12", "OT1_DRAW": "1X", "DRAW_OT2": "X2"}
BTTS_NORM = {"yes": "DA", "ja": "DA", "no": "NE", "nej": "NE"}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _iso_u_epoch(iso):
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _kvota(outcome):
    """Kambi odds = int ×1000."""
    o = outcome.get("odds")
    if not o:
        return None
    v = round(o / 1000.0, 2)
    return v if v >= 1.01 else None


def _dc_ishod(o):
    for kljuc in ("label", "englishLabel"):
        lab = str(o.get(kljuc) or "").strip().lower()
        if lab in DC_NORM:
            return DC_NORM[lab]
    t = str(o.get("type") or "").strip().upper()
    if t in DC_TIP:
        return DC_TIP[t]
    # fallback: engleski tekst ("Home or draw"...)
    lab = str(o.get("englishLabel") or "").strip().lower()
    if "draw" in lab and lab.startswith("home"):
        return "1X"
    if lab.startswith("home") and "away" in lab:
        return "12"
    if lab.startswith("draw") or "draw" in lab and "away" in lab:
        return "X2"
    return None


def pokupi():
    """Unibet ponuda (fudbal + košarka) u istom formatu kao maxbet/matchbook."""
    mecevi = []
    for sport, slug in SPORT_URL.items():
        try:
            d = _get(f"{BASE}/{slug}.json{UPIT}")
        except Exception as e:
            print(f"unibet {sport}: {e}")
            continue
        for ev in d.get("events") or []:
            e = ev.get("event") or {}
            stanje = str(e.get("state") or "NOT_STARTED").upper()
            if stanje != "NOT_STARTED":
                continue  # preskačemo live/završene — pratimo prematch
            domacin = e.get("homeName") or e.get("englishName", "").split(" - ")[0]
            gost = e.get("awayName") or ""
            if not domacin or not gost:
                ime = e.get("englishName") or e.get("name") or ""
                if " - " in ime:
                    domacin, gost = [x.strip() for x in ime.split(" - ", 1)]
                else:
                    continue  # outrights bez parova
            liga = e.get("group") or "?"
            putanja = [p.get("englishName") or p.get("name") for p in (e.get("path") or [])]
            if len(putanja) >= 3 and putanja[-1]:
                liga = f"{putanja[-2]} · {putanja[-1]}" if putanja[-2] else str(putanja[-1])

            kvote = []
            for b in ev.get("betOffers") or []:
                bt = (b.get("betOfferType") or {})
                ime_tipa = str(bt.get("englishName") or bt.get("name") or "").strip().lower()
                outcomes = b.get("outcomes") or []
                if b.get("live") is True:
                    continue
                if ime_tipa == "match":
                    for o in outcomes:
                        if str(o.get("status") or "OPEN").upper() not in ("OPEN", ""):
                            continue  # SUSPENDED/CLOSED — nema ni odds
                        ishod = TIP_KI.get(str(o.get("type") or "").upper())
                        if ishod is None:
                            lab = str(o.get("label") or "").strip()
                            ishod = lab if lab in ("1", "X", "2") else None
                        v = _kvota(o)
                        if ishod and v:
                            kvote.append({"market": "Konačan ishod", "ishod": ishod, "vrednost": v})
                elif "double chance" in ime_tipa:
                    for o in outcomes:
                        ishod = _dc_ishod(o)
                        v = _kvota(o)
                        if ishod and v:
                            kvote.append({"market": "Dupla šansa", "ishod": ishod, "vrednost": v})
                elif "both teams to score" in ime_tipa:
                    for o in outcomes:
                        lab = str(o.get("englishLabel") or o.get("label") or "").strip().lower()
                        ishod = BTTS_NORM.get(lab)
                        v = _kvota(o)
                        if ishod and v:
                            kvote.append({"market": "Oba tima daju gol", "ishod": ishod, "vrednost": v})
            if not kvote:
                continue
            seen = set()
            ciste = []
            for k in kvote:
                kljuc = (k["market"], k["ishod"])
                if kljuc in seen:
                    continue
                seen.add(kljuc)
                ciste.append(k)
            mecevi.append({
                "id": int(e["id"]),
                "sport": sport,
                "liga": str(liga)[:90],
                "domacin": str(domacin)[:80],
                "gost": str(gost)[:80],
                "pocetak": _iso_u_epoch(e.get("start")),
                "kvote": ciste,
                "izvor": "unibet",
            })
    return mecevi


if __name__ == "__main__":
    t0 = time.time()
    meci = pokupi()
    nk = sum(len(m["kvote"]) for m in meci)
    print(f"Unibet: {len(meci)} mečeva, {nk} kvota za {time.time()-t0:.1f}s")
    for m in meci[:5]:
        print(f'  {m["domacin"]} - {m["gost"]} ({m["sport"]}, {m["liga"]}) {m["kvote"][:4]}')
