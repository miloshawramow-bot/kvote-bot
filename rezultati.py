#!/usr/bin/env python3
"""
Rezultati završenih mečeva — MaxBet zvanični results feed.

    GET https://www.maxbet.rs/restapi/results/sr/day/{dd.MM.yyyy.}
        → {"resultsMap": {"S": [meč...], "B": [...], ...}}

meč: {id, home, away, kickOffTime (ms), status, leagueName, sport,
      matchResult: {hs: {...}, as: {...}}}
status == 1  → ZAVRŠEN; konačan skor = hs["FULLTIME"] : as["FULLTIME"]
(status 6 = LIVE, 0 = nije počeo, 2/3 = specijalni)

Izlaz: kompaktne vrste {z,i,d,g,gd,gg,p,s,l} za push u Worker
(Worker /push_rezultati) i za lokalni HTML izvoz.
"""
import json
import os
import time
import urllib.request
from datetime import date, timedelta

BASE = "https://www.maxbet.rs/restapi/results/sr/day/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
KEŠ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "podaci", "rez_cache.json")
SPORTOVI = {"S": "fudbal", "B": "kosarka"}


def _dan(d: date) -> str:
    return d.strftime("%d.%m.%Y.")  # MaxBet format: 26.09.2026. (tačka na kraju!)


def _get(url: str, timeout: int = 120):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def pokupi(dana: int = 2, max_age: int = 900):
    """Rezultati za poslednjih `dana` dana; keš `max_age` sekundi (0 = forsiraj)."""
    if max_age > 0:
        try:
            with open(KEŠ, encoding="utf-8") as f:
                c = json.load(f)
            if time.time() - c.get("ts", 0) < max_age and c.get("dana", -1) >= dana:
                return c["rows"]
        except Exception:
            pass
    redovi = []
    danas = date.today()
    for i in range(dana):
        d = danas - timedelta(days=i)
        try:
            podaci = _get(BASE + _dan(d))
        except Exception as e:
            print(f"rezultati {d}: {e}")
            continue
        rm = podaci.get("resultsMap") or {}
        for kod, sport in SPORTOVI.items():
            for m in rm.get(kod) or []:
                if m.get("status") != 1:
                    continue  # samo ZAVRŠENI
                mr = m.get("matchResult") or {}
                hs, as_ = mr.get("hs") or {}, mr.get("as") or {}
                gd, gg = hs.get("FULLTIME"), as_.get("FULLTIME")
                if not isinstance(gd, (int, float)) or not isinstance(gg, (int, float)):
                    continue
                if gd < 0 or gg < 0:
                    continue
                redovi.append({
                    "z": "maxbet",
                    "i": str(m.get("id")),
                    "d": str(m.get("home") or "?")[:80],
                    "g": str(m.get("away") or "?")[:80],
                    "gd": int(gd),
                    "gg": int(gg),
                    "p": int((m.get("kickOffTime") or 0) / 1000),
                    "s": sport,
                    "l": str(m.get("leagueName") or "")[:60],
                })
    # dedupe po id
    seen, out = set(), []
    for r in redovi:
        if r["i"] in seen:
            continue
        seen.add(r["i"])
        out.append(r)
    try:
        os.makedirs(os.path.dirname(KEŠ), exist_ok=True)
        with open(KEŠ, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "dana": dana, "rows": out}, f)
    except Exception:
        pass
    return out


if __name__ == "__main__":
    t0 = time.time()
    redovi = pokupi(max_age=0)
    fud = [r for r in redovi if r["s"] == "fudbal"]
    kos = [r for r in redovi if r["s"] == "kosarka"]
    print(f"Ukupno {len(redovi)} završenih (fudbal {len(fud)}, košarka {len(kos)}) za {time.time()-t0:.1f}s")
    for r in fud[:4] + kos[:4]:
        print(f'  {r["d"]} - {r["g"]} = {r["gd"]}:{r["gg"]} ({r["s"]}, {r["l"]})')
