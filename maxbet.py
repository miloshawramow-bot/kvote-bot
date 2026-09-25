#!/usr/bin/env python3
"""
MaxBet klijent — PRAVE kvote (fudbal + košarka) sa maxbet.rs.

API je reverse-engineered (bez javne dokumentacije):
  GET /restapi/offer/sr/ttg_lang          → rečnik tržišta (betMap/betPickMap/betPickGroupMap)
  GET /live/init/sr                       → LIVE mečevi + kvote (liveHeaders/liveBets)
  GET /restapi/offer/sr/search/{term}/mob → prematch mečevi SA KVOTAMA (esMatches[].odds)
  GET /restapi/offer/sr/categories/sport/{S|B}/l → lige (S=fudbal, B=košarka)
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List, Optional

BASE = "https://www.maxbet.rs"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
SPORTOVI = {"fudbal": "S", "kosarka": "B"}
OZNAKA_U_SPORT = {"S": "fudbal", "B": "kosarka", "T": "tenis"}


def _get(putanja: str, pokusaja: int = 3) -> Any:
    req = urllib.request.Request(
        BASE + putanja, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    poslednja = None
    for i in range(pokusaja):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            poslednja = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"MaxBet {putanja}: {poslednja}")


# ---------------- rečnik ----------------

def recnik() -> Dict[str, Any]:
    """Kompletan rečnik tržišta (keširaj ga — menja se retko)."""
    return _get("/restapi/offer/sr/ttg_lang")


def _indeksi(rec: Dict[str, Any]):
    betmap = rec.get("betMap") or {}
    pickmap = rec.get("betPickMap") or {}
    po_bpc = {}  # betPickCode → pick
    for p in pickmap.values():
        bpc = p.get("betPickCode")
        if bpc:
            po_bpc[int(bpc)] = p
    return betmap, pickmap, po_bpc


def _sredi(s: str) -> str:
    return (s or "").replace("\xa0", " ").strip()


def klasifikuj(bet_caption: str, pick: Dict[str, Any]) -> Optional[tuple]:
    """
    Vraća (market, ishod) NAŠIM imenima (kao Mozzart) ili None.
    Pravila: mainType + caption/label šabloni; cilj = tržišta poredljiva sa Mozzartom.
    """
    kap = _sredi(str(pick.get("caption") or "")).upper().replace(" ", "")
    lab = _sredi(str(pick.get("label") or "")).lower()
    bet = _sredi(bet_caption).lower()
    main = bool(pick.get("mainType"))

    nus = ("poluvreme", "poluvremena", "četvrt", "cetvrt", "trećin", "trecin",
           "produžet", "produzet", "prvo pol", "drugo pol", "i pol", "ii pol")

    # Konačan ishod 1 / X / 2
    if kap in ("1", "X", "2") and main and not any(n in lab for n in nus):
        return ("Konačan ishod", kap)
    # Dupla šansa 1X / 12 / X2
    if kap in ("1X", "12", "X2") and main:
        return ("Dupla šansa", kap)
    # Oba tima daju gol — SAMO čisto tržište (caption GG / NG, bez kombinacija)
    if kap == "GG":
        return ("Oba tima daju gol", "DA")
    if kap == "NG":
        return ("Oba tima daju gol", "NE")
    # Košarka: Pobednik meča sa ev. produžecima (P1/P2 — bez X)
    if ("uključujući produžetke" in lab or "sa produžet" in lab) and kap in ("1", "2", "P1", "P2"):
        return ("Pobednik meča sa ev. produžecima", kap[-1])
    return None


def _obradi_kvote(odds: Dict[str, Any], betmap: Dict[str, Any],
                  po_bpc: Dict[int, Any]) -> List[Dict[str, Any]]:
    """odds: {betPickCode: vrednost} → naša lista kvota."""
    out = []
    vidjen = set()
    for bpc, vred in (odds or {}).items():
        try:
            v = float(vred)
        except (TypeError, ValueError):
            continue
        if v <= 1.0 or v > 1000:
            continue
        pick = po_bpc.get(int(bpc))
        if not pick:
            continue
        trz = klasifikuj((betmap.get(str(pick.get("betCode"))) or {}).get("caption") or "", pick)
        if trz is None or trz in vidjen:
            continue
        vidjen.add(trz)
        out.append({"market": trz[0], "ishod": trz[1], "vrednost": v,
                    "opis": _sredi(str(pick.get("label") or ""))})
    return out


# ---------------- prikupljanje ----------------

def _live(rec: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    betmap, _, po_bpc = _indeksi(rec)
    podaci = _get("/live/init/sr")
    meci: Dict[int, Dict[str, Any]] = {}
    for h in podaci.get("liveHeaders") or []:
        mid = int(h.get("id") or 0)
        if not mid:
            continue
        meci[mid] = {
            "id": mid,
            "sport": OZNAKA_U_SPORT.get(h.get("s"), str(h.get("sn") or "?").lower()),
            "liga": f"{h.get('lsh') or ''} {h.get('lg') or ''}".strip() or "?",
            "domacin": h.get("h") or "?",
            "gost": h.get("a") or "?",
            "pocetak": float(h.get("kot") or 0) / 1000.0,
            "status": "LIVE",
            "kvote": [],
            "_po": {},
        }
    for b in podaci.get("liveBets") or []:
        mid = int(b.get("mId") or 0)
        m = meci.get(mid)
        if m is None:
            continue
        bc = str(b.get("bc") or "")
        bet_caption = (betmap.get(bc) or {}).get("caption") or ""
        for _oid, o in (b.get("om") or {}).items():
            bpc = o.get("bpc")
            v = o.get("ov")
            if not bpc or not v:
                continue
            pick = po_bpc.get(int(bpc))
            if not pick:
                continue
            trz = klasifikuj(bet_caption, pick)
            if trz is None:
                continue
            kljuc = (trz[0], trz[1])
            if kljuc in m["_po"] and len(_sredi(str(pick.get("label") or ""))) > 28:
                continue  # varijanta — čistije već upisano
            if kljuc not in m["_po"]:
                m["_po"][kljuc] = True
                m["kvote"].append({"market": trz[0], "ishod": trz[1], "vrednost": float(v),
                                   "opis": _sredi(str(pick.get("label") or ""))})
    return meci


PREMATCH_TERMI = list("abcčćdđefghijklmnopqrsštuvwxyzž") + [
    "man", "real", "city", "united", "zvezda", "partizan", "juventus", "barca",
    "arsenal", "chelsea", "liverpool", "bayern", "dortmund", "ajax", "porto",
    "benfica", "milan", "inter", "roma", "napoli", "psg", "lyon", "sevilla",
    "valencia", "atletico", "sporting", "galatasaray", "fener", "dinamo",
    "crvena", "vojvodina", "čukarički", "spartak", "napredak", "radnički",
]


def _prematch(rec: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    betmap, _, po_bpc = _indeksi(rec)
    meci: Dict[int, Dict[str, Any]] = {}
    for term in PREMATCH_TERMI:
        try:
            d = _get(f"/restapi/offer/sr/search/{urllib.request.quote(term)}/mob",
                     pokusaja=2)
        except Exception:
            continue
        for m in d.get("esMatches") or []:
            mid = int(m.get("id") or 0)
            if not mid or mid in meci or m.get("blocked"):
                continue
            sport = OZNAKA_U_SPORT.get(m.get("sport"), "?")
            if sport not in SPORTOVI:
                continue  # samo fudbal + košarka
            kvote = _obradi_kvote(m.get("odds") or {}, betmap, po_bpc)
            if not kvote:
                continue
            meci[mid] = {
                "id": mid,
                "sport": sport,
                "liga": m.get("leagueName") or "?",
                "domacin": m.get("home") or "?",
                "gost": m.get("away") or "?",
                "pocetak": float(m.get("kickOffTime") or 0) / 1000.0,
                "status": "PRE",
                "kvote": kvote,
                "_po": {(k["market"], k["ishod"]): True for k in kvote},
            }
        time.sleep(0.25)
    return meci


def pokupi(sportovi: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Cela MaxBet ponuda (prematch + live) normalizovana kao i mozzart.pokupi()."""
    rec = recnik()
    svi: Dict[int, Dict[str, Any]] = {}
    svi.update(_prematch(rec))
    svi.update(_live(rec))
    zeljeni = set(sportovi or SPORTOVI)
    out = []
    for m in svi.values():
        m.pop("_po", None)
        if m["sport"] in zeljeni and m["kvote"]:
            out.append(m)
    return out


if __name__ == "__main__":
    meci = pokupi()
    print(f"MaxBet: {len(meci)} mečeva")
    broj = sum(len(m['kvote']) for m in meci)
    print(f"kvota (mapiranih tržišta): {broj}")
    for m in meci[:5]:
        print(f"  [{m['status']}] {m['domacin']} - {m['gost']} ({len(m['kvote'])} kvota)")
    for m in meci:
        if "zvezda" in (m["domacin"] + m["gost"]).lower():
            print(f"\nPRIMER: {m['domacin']} - {m['gost']}")
            for k in m["kvote"]:
                print(f"   {k['market']} {k['ishod']}: {k['vrednost']}")
            break
