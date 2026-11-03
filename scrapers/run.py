"""Run every source scraper, write docs/data/latest.json and append to docs/data/history.jsonl.

Each scraper in sources.py is a function decorated with @source(...) that returns a list of
Observation dicts. A failing scraper never breaks the run: its last good observations are
carried forward and marked stale, so the dashboard always shows the freshest data it has.
"""
from __future__ import annotations
import json, pathlib, traceback, datetime as dt
from zoneinfo import ZoneInfo

import sources  # registers scrapers
from common import REGISTRY

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
DATA.mkdir(parents=True, exist_ok=True)
LATEST = DATA / "latest.json"
HISTORY = DATA / "history.jsonl"
ET = ZoneInfo("America/New_York")


def now_iso():
    return dt.datetime.now(ET).isoformat(timespec="seconds")


def main():
    prev = json.loads(LATEST.read_text()) if LATEST.exists() else {"sources": {}}
    out_sources = {}
    run_at = now_iso()
    for meta, fn in REGISTRY:
        sid = meta["id"]
        entry = dict(meta)
        try:
            obs = fn()
            if not obs:
                raise RuntimeError("scraper returned no observations")
            for o in obs:
                o.setdefault("source", sid)
                o.setdefault("state", meta.get("state"))
            entry.update(status="ok", fetched_at=run_at, observations=obs, error=None)
        except Exception as e:  # keep last good data
            old = prev.get("sources", {}).get(sid, {})
            entry.update(
                status="stale" if old.get("observations") else "error",
                fetched_at=old.get("fetched_at"),
                observations=old.get("observations", []),
                error=f"{type(e).__name__}: {e}"[:300],
                last_attempt=run_at,
            )
            traceback.print_exc()
        out_sources[sid] = entry
        print(f"{sid:28} {entry['status']:6} {len(entry['observations'])} obs  {entry.get('error') or ''}")

    latest = {"generated_at": run_at, "sources": out_sources}
    LATEST.write_text(json.dumps(latest, indent=1))

    # history: one line per fresh observation, only when the value changed since last logged
    last_vals = {}
    if HISTORY.exists():
        for ln in HISTORY.read_text().splitlines():
            try:
                r = json.loads(ln)
                last_vals[r["key"]] = r["value"]
            except Exception:
                pass
    with HISTORY.open("a") as fh:
        for sid, entry in out_sources.items():
            if entry["status"] != "ok":
                continue
            for o in entry["observations"]:
                key = f"{sid}|{o.get('jurisdiction')}|{o.get('metric')}"
                if last_vals.get(key) != o.get("value"):
                    fh.write(json.dumps({"t": run_at, "key": key, "source": sid, "state": o.get("state"),
                                         "jurisdiction": o.get("jurisdiction"), "metric": o.get("metric"),
                                         "value": o.get("value"), "as_of": o.get("as_of")}) + "\n")


if __name__ == "__main__":
    main()
