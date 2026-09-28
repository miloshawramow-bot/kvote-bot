# -*- coding: utf-8 -*-
"""OddsPortal — globalni agregator padajućih kvota (bez JS-a, SSR HTML).

Izvor: https://www.oddsportal.com/dropping-odds/2/2/0/overall/
Stranica server-side renderuje tabelu najvećih padova kvota preko mnogo
kladionica (bet365, Pinnacle, Unibet, ...) — fudbal, košarka, tenis...

Ovo je AGREGATOR (poređenje tržišta), ne kladionica: koristimo ga kao
dodatnu potvrdu ("🌐 globalni pad") uz naše 4 direktne源.

Redovi: [{sport, l, d, g, m, z, otv, sad, proc, datum}]
  sport  — "fudbal" / "kosarka" / ostali
  l      — liga
  d, g   — timovi (display imena; fallback: h2h slug)
  m      — tržište + selekcija (npr. "O/U 7.5 · Over", "1X2 · 2")
  z      — kladionica najvećeg pada (npr. "bet365.us")
  otv    — otvarajuća kvota
  sad    — trenutna kvota
  proc   — promena u % (negativno = pad)
  datum  — "01 Oct 21:00" (tekst sa stranice)
"""
from __future__ import annotations

import html as _html
import re
import time
import urllib.request
from typing import Any, Dict, List

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = "https://www.oddsportal.com/dropping-odds/2/2/0/overall/"

SPORT_MAP = {"football": "fudbal", "soccer": "fudbal", "basketball": "kosarka"}

_cache: Dict[str, Any] = {"ts": 0.0, "rows": [], "url": ""}


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", str(s or ""))).strip()


def _ime_iz_sluga(slug: str) -> str:
    slug = re.sub(r"-[A-Za-z0-9]{6,12}$", "", slug)  # skini ID sufiks
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def _tokeni(seg: str) -> List[str]:
    """HTML segment → lista vidljivih tokena (redom)."""
    t = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*>', r"|\1|", seg)
    t = re.sub(r"<svg.*?</svg>", "", t, flags=re.S)
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "|", t)
    t = _html.unescape(t)
    return [x.strip() for x in t.split("|") if x.strip()]


def parsiraj(html_str: str) -> List[Dict[str, Any]]:
    redovi: List[Dict[str, Any]] = []
    # svaki događaj počinje breadcrumb linkom tačno na sport: href="/football/"
    delovi = re.split(r'(?=href="/[a-z]+/")', html_str)
    for seg in delovi:
        m = re.match(r'href="/([a-z]+)/"', seg)
        if not m:
            continue
        sport = SPORT_MAP.get(m.group(1), m.group(1))
        if "Best Current Odds" not in seg:
            continue
        tok = _tokeni(seg[:12000])
        try:
            bco = tok.index("Best Current Odds")
        except ValueError:
            continue
        if bco < 3 or bco + 3 >= len(tok):
            continue
        market = tok[bco - 2]
        selekcija = tok[bco - 1]
        datum = f"{tok[bco + 1]} {tok[bco + 2]}"
        # liga: tokeni između poslednjeg "/" pre market-a
        liga = ""
        for i in range(bco - 3, 1, -1):
            if tok[i] == "/":
                cand = [t for t in tok[i + 1:bco - 2] if t not in ("/", sport.capitalize(), "Football", "Basketball")]
                # deduplikacija uzastopnih istih (breadcrumb + dupli tekst)
                ded = []
                for t in cand:
                    if not ded or ded[-1] != t:
                        ded.append(t)
                liga = " ".join(ded)
                break
        # procenat: prvi token sa % posle datuma
        proc_i = None
        for i in range(bco + 3, min(bco + 14, len(tok))):
            if re.fullmatch(r"[-+]?\d{1,3}(\.\d)?%", tok[i]):
                proc_i = i
                break
        if proc_i is None:
            continue
        proc = float(tok[proc_i].rstrip("%").replace("+", ""))
        # timovi: između datuma i procenta (bez "-" razdelnice i duplikata)
        sredina = [t for t in tok[bco + 3:proc_i] if t != "-"]
        ded = []
        for t in sredina:
            if not ded or ded[-1] != t:
                ded.append(t)
        d = g = ""
        if len(ded) >= 2:
            pola = len(ded) // 2
            d = " ".join(ded[:pola])
            g = " ".join(ded[pola:])
        if not d or not g:
            hm = re.search(r'href="/[a-z]+/[^"]*?/h2h/([^/"]+)/([^/"]+)/', seg)
            if hm:
                d = d or _ime_iz_sluga(hm.group(1))
                g = g or _ime_iz_sluga(hm.group(2))
        if not d or not g:
            continue
        # kvote: brojevi posle procenta
        nums, knjiga, best = [], "", None
        for t in tok[proc_i + 1:proc_i + 12]:
            if re.fullmatch(r"\d+\.\d{1,3}", t):
                nums.append(float(t))
            elif not knjiga and nums and re.fullmatch(r"[A-Za-z0-9.&' -]{2,30}", t):
                knjiga = t
        otv = nums[0] if nums else None
        sad = nums[1] if len(nums) > 1 else (nums[0] if nums else None)
        redovi.append({
            "sport": sport, "l": _clean(liga) or "—", "d": _clean(d), "g": _clean(g),
            "m": _clean(f"{market} · {selekcija}"), "z": _clean(knjiga) or "?",
            "otv": otv, "sad": sad, "proc": proc, "datum": _clean(datum),
        })
    # deduplikacija (isti meč+tržište) i sort po |proc|
    vidjeno, out = set(), []
    for r in sorted(redovi, key=lambda x: -abs(x["proc"])):
        klj = (r["d"].lower(), r["g"].lower(), r["m"])
        if klj in vidjeno:
            continue
        vidjeno.add(klj)
        out.append(r)
    return out


def pokupi(max_age: int = 600, url: str = URL) -> List[Dict[str, Any]]:
    """Globalni padovi (keš `max_age` sekundi)."""
    if max_age > 0 and _cache["rows"] and _cache["url"] == url \
            and time.time() - _cache["ts"] < max_age:
        return _cache["rows"]
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        s = resp.read().decode("utf-8", "replace")
    rows = parsiraj(s)
    _cache.update(ts=time.time(), rows=rows, url=url)
    return rows


if __name__ == "__main__":
    rs = pokupi(max_age=0)
    print(f"OddsPortal: {len(rs)} globalnih padova/rastova")
    for r in rs[:20]:
        print(f"  {r['proc']:+6.1f}%  {r['otv']}→{r['sad']}  {r['d']} - {r['g']}  "
              f"[{r['m']}]  {r['z']}  ({r['sport']}, {r['l']}, {r['datum']})")
