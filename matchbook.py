#!/usr/bin/env python3
"""
Matchbook klijent — svetska betting berza (London).

Javni REST API (radi bez ključa):
    GET https://www.matchbook.com/edge/rest/events?sport-ids=15,4&language=en
        &country=UK&exchange-type=back&per-page=1000
Struktura: events[] → markets[] (market-type) → runners[] → prices[]
    (side=back/lay, decimal-odds, available-amount)

sport-id: 15 = fudbal, 4 = košarka, 1 = američki fudbal, 9 = tenis.
Kvote = najbolja BACK cena (decimal-odds) po ishodu — prava tržišna kvota.

Izlazni format je ISTI kao maxbet.pokupi():
    [{"id", "sport", "liga", "domacin", "gost", "pocetak", "kvote":
      [{"market", "ishod", "vrednost"}], "izvor": "matchbook"}]
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.matchbook.com/edge/rest/events"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
SPORT_ID = {15: "fudbal", 4: "kosarka"}

# Matchbook market-type → (naš market, mapa ishoda po imenu runnera)
DS_MAPA = {
    "home or draw": "1X", "home or away": "12", "draw or away": "X2",
    "home/away": "12", "home/draw": "1X", "draw/away": "X2",
}
BTTS_MAPA = {"yes": "DA", "no": "NE"}


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _najbolji_back(runner):
    """Najbolja dostupna BACK decimal-odds za runnera."""
    najbolja = None
    for p in runner.get("prices") or []:
        if p.get("side") != "back":
            continue
        d = p.get("decimal-odds")
        if not d or d < 1.01:
            continue
        if (p.get("available-amount") or 0) < 5:
            continue  # džunk-ponuda bez pokrivenosti
        if najbolja is None or d > najbolja:
            najbolja = d
    return round(najbolja, 2) if najbolja else None


def _iso_u_epoch(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _kratak_id(eid):
    """Matchbook id je 17-cifren (veći od JS 2^53) — uzmi poslednjih 12 cifara."""
    return int(str(eid)[-12:])


def pokupi(sport_ids=(15, 4)):
    ids = ",".join(str(i) for i in sport_ids)
    url = (f"{BASE}?sport-ids={ids}&language=en&country=UK"
           f"&exchange-type=back&per-page=1000")
    d = _get(url)
    mecevi = []
    vidjeni = set()
    for e in d.get("events") or []:
        sport = SPORT_ID.get(e.get("sport-id"))
        if not sport:
            continue
        if e.get("in-running-flag"):
            continue  # live meč — pratimo prematch
        ime = e.get("name") or ""
        if " vs " not in ime:
            continue  # futures/outright (npr. "NBA Championship Winner")
        domacin, gost = [x.strip() for x in ime.split(" vs ", 1)]
        mid = _kratak_id(e.get("id"))
        if mid in vidjeni:
            continue
        vidjeni.add(mid)

        kvote = []
        for m in e.get("markets") or []:
            mt = m.get("market-type")
            mn = (m.get("name") or "").strip().lower()
            status = m.get("status")
            if status and status != "open":
                continue
            runners = m.get("runners") or []
            if mt == "one_x_two" and len(runners) == 3:
                # Match Odds: Home/Draw/Away → Konačan ishod 1/X/2
                za = ["1", "X", "2"]
                for r, ishod in zip(runners, za):
                    v = _najbolji_back(r)
                    if v:
                        kvote.append({"market": "Konačan ishod", "ishod": ishod, "vrednost": v})
            elif mt == "other" and mn == "double chance":
                for r in runners:
                    ishod = DS_MAPA.get((r.get("name") or "").strip().lower())
                    if not ishod:
                        continue
                    v = _najbolji_back(r)
                    if v:
                        kvote.append({"market": "Dupla šansa", "ishod": ishod, "vrednost": v})
            elif mt == "both_to_score":
                for r in runners:
                    ishod = BTTS_MAPA.get((r.get("name") or "").strip().lower())
                    if not ishod:
                        continue
                    v = _najbolji_back(r)
                    if v:
                        kvote.append({"market": "Oba tima daju gol", "ishod": ishod, "vrednost": v})
            elif mt == "moneyline" and sport == "kosarka":
                za = ["1", "2"]
                for r, ishod in zip(runners[:2], za):
                    v = _najbolji_back(r)
                    if v:
                        kvote.append({"market": "Konačan ishod", "ishod": ishod, "vrednost": v})
        if not kvote:
            continue
        # dedupe (market, ishod)
        seen = set()
        ciste = []
        for k in kvote:
            kljuc = (k["market"], k["ishod"])
            if kljuc in seen:
                continue
            seen.add(kljuc)
            ciste.append(k)
        mecevi.append({
            "id": mid,
            "sport": sport,
            "liga": "Matchbook berza",
            "domacin": domacin,
            "gost": gost,
            "pocetak": _iso_u_epoch(e.get("start") or ""),
            "kvote": ciste,
            "izvor": "matchbook",
        })
    return mecevi


if __name__ == "__main__":
    t0 = time.time()
    meci = pokupi()
    nk = sum(len(m["kvote"]) for m in meci)
    print(f"Matchbook: {len(meci)} mečeva, {nk} kvota za {time.time()-t0:.1f}s")
    for m in meci[:5]:
        print(f'  {m["domacin"]} - {m["gost"]} ({m["sport"]}) {m["kvote"][:4]}')
