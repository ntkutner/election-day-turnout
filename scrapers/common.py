from __future__ import annotations
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
REGISTRY: list[tuple[dict, callable]] = []

# Metrics used across sources
#   eday_checkins   – in-person voters checked in / ballots cast on Election Day so far
#   early_inperson  – early in-person votes (final)
#   mail_returned   – mail/absentee ballots returned
#   mail_requested  – mail/absentee ballots requested/sent
#   total_voted     – all ballots cast so far (early + mail + election day where reported)
#   registered      – registered voters (denominator)


def source(id, name, state, kind, url, note=""):
    """kind: 'eday' (live election-day), 'early' (pre-election), 'total'"""
    def deco(fn):
        REGISTRY.append(({"id": id, "name": name, "state": state, "kind": kind, "url": url, "note": note}, fn))
        return fn
    return deco


def get(url, **kw):
    kw.setdefault("timeout", 40)
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, **kw)
    r.raise_for_status()
    return r


def num(s) -> int | None:
    if s is None:
        return None
    s = re.sub(r"[^\d]", "", str(s))
    return int(s) if s else None


def obs(jurisdiction, metric, value, as_of=None, **extra):
    d = {"jurisdiction": jurisdiction, "metric": metric, "value": value, "as_of": as_of}
    d.update(extra)
    return d
