#!/usr/bin/env python3
"""
Kvote bot — skida PRAVE Mozzart kvote (fudbal + košarka) i šalje ih u Kvote Worker.

Pokreće GitHub Actions svakih 10 minuta (24/7). Radi i lokalno:
    PUSH_URL=... PUSH_KEY=... python3 kvote_push.py
"""
import json
import os
import sys
import time
import urllib.request

BASE = "https://www.mozzartbet.com"
PUSH_URL = os.environ.get(
    "PUSH_URL", "https://tight-glitter-2dcb.miloshawramow.workers.dev/push"
)
PUSH_KEY = os.environ.get("PUSH_KEY", "")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "medium": "PREMATCH_WEB",
    "Referer": BASE + "/",
    "Origin": BASE,
}
SPORTOVI = {"fudbal": 1, "kosarka": 2}
ID_U_SPORT = {1: "fudbal", 2: "kosarka"}
MAX_STRANICA = 12
SVEZE = 3 * 3600  # mečevi koji su počeli pre više od 3h se ne šalju


def post_json(putanja, telo, pokusaja=3):
    poslednja = None
    for i in range(pokusaja):
        try:
            req = urllib.request.Request(
                BASE + putanja, data=json.dumps(telo).encode(), headers=HEADERS
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:  # mreža, timeout, JSON...
            poslednja = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Ne mogu da dohvatim {putanja}: {poslednja}")


def parsiraj_kvote(stavka):
    """Izvuče (market, ishod, vrednost) iz oddsGroup strukture."""
    out = []
    for grupa in stavka.get("oddsGroup") or []:
        market = grupa.get("groupName") or "?"
        for o in grupa.get("odds") or []:
            if o.get("oddStatus") not in (None, "ACTIVE"):
                continue  # blokirana/ugašena kvota
            vrednost = o.get("value")
            if not vrednost:
                continue
            sg = o.get("subgame") or {}
            igra = o.get("game") or {}
            ishod = sg.get("shortName") or sg.get("name") or "?"
            param = igra.get("parameterName") or ""
            if param:
                ishod = f"{ishod} {param}".strip()
            out.append((market, ishod, float(vrednost)))
    return out


def pokupi():
    """Cela prematch ponuda (fudbal + košarka) kao {id: {s,l,d,g,p,k}}."""
    svi = {}
    for sport, sid in SPORTOVI.items():
        for strana in range(MAX_STRANICA):
            odg = post_json(
                "/betting/matches",
                {
                    "sportId": sid,
                    "pageSize": 50,
                    "currentPage": strana,
                    "orderType": "BY_COMPETITION",
                    "medium": "PREMATCH_WEB",
                },
            )
            items = odg.get("items") or []
            if not items:
                break
            for it in items:
                kvote = parsiraj_kvote(it)
                if not kvote:
                    continue
                m = {
                    "s": ID_U_SPORT.get((it.get("sport") or {}).get("id"), sport),
                    "l": (it.get("competition") or {}).get("name") or "?",
                    "d": (it.get("home") or {}).get("name") or "?",
                    "g": (it.get("visitor") or {}).get("name") or "?",
                    "p": int(float(it.get("startTime") or 0) / 1000),
                    "k": {f"{market}|{ishod}": v for market, ishod, v in kvote},
                }
                svi[int(it["id"])] = m
            if len(items) < 50:
                break
            time.sleep(0.4)  # blaga pauza da ne opterećujemo sajt
    return svi


def posalji(meci):
    url = PUSH_URL
    if PUSH_KEY:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={PUSH_KEY}"
    req = urllib.request.Request(
        url,
        data=json.dumps(meci).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    sada = time.time()
    meci = pokupi()
    svi = {i: m for i, m in meci.items() if m["p"] >= sada - SVEZE}
    if not svi:
        print("Greška: prazna ponuda — ništa nije poslato (sigurnosna zaštita)")
        sys.exit(1)
    odg = posalji(svi)
    print(f"Poslato {len(svi)} mečeva (od ukupno {len(meci)}) → {odg}")


if __name__ == "__main__":
    main()
