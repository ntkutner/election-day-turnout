"""Build docs/data/history_2022_2024.json: county-level 2022 and 2024 general-election
registration and ballots cast for Texas and Florida.

Texas:   Texas Legislative Council VTD election data, *_General_Election_VRTO.csv
         (TotalVR = registered voters, TotalTO = turnout), summed by county.
Florida: Florida Division of Elections precinct-level results (official). Registered =
         sum of precinct "Total Registered Voters"; ballots cast = all rows (candidates +
         OverVotes + UnderVotes) in the top-of-ticket contest (Governor 2022, President 2024).
"""
import csv, io, json, pathlib, zipfile, collections, sys
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
UA = {"User-Agent": "Mozilla/5.0"}
TLC = ("https://data.capitol.texas.gov/dataset/35b16aee-0bb0-4866-b1ec-859f1f044241/resource/"
       "e1cd6332-6a7a-4c78-ad2a-852268f6c7a2/download/2024-general-vtds-election-data.zip")
FL = {"2022": "https://dos.fl.gov/media/706300/2022-gen-outputofficial.zip",
      "2024": "https://dos.fl.gov/media/708761/2024-gen-outputofficial1.zip"}
FL_TOP = {"2022": "governor", "2024": "president"}

out = {"sources": {"TX": "Texas Legislative Council VTD election data (VRTO files)",
                   "FL": "Florida Division of Elections precinct-level results (official)"},
       "TX": {}, "FL": {}}

# ---------------- Texas
z = zipfile.ZipFile(io.BytesIO(requests.get(TLC, timeout=300, headers=UA).content))
for y in ("2022", "2024"):
    name = f"{y}_General_Election_VRTO.csv"
    agg = collections.defaultdict(lambda: {"reg": 0, "ballots": 0})
    with z.open(name) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1")):
            c = r["County"].strip().upper()
            agg[c]["reg"] += int(float(r.get("TotalVR") or 0))
            agg[c]["ballots"] += int(float(r.get("TotalTO") or 0))
    for c, v in agg.items():
        out["TX"].setdefault(c, {})[y] = v
    tot = {k: sum(v[k] for v in agg.values()) for k in ("reg", "ballots")}
    out["TX"].setdefault("_STATE", {})[y] = tot
    print("TX", y, len(agg), "counties", tot, flush=True)

# ---------------- Florida
for y, url in FL.items():
    r = requests.get(url, timeout=300, headers=UA); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = [n for n in z.namelist() if n.lower().endswith(".txt")]
    print("FL", y, len(names), "files; sample", names[:3], flush=True)
    reg = collections.defaultdict(dict)        # county -> precinct -> registered
    ballots = collections.defaultdict(int)
    contests_seen = collections.Counter()
    for n in names:
        with z.open(n) as fh:
            for line in io.TextIOWrapper(fh, encoding="latin-1"):
                f = line.rstrip("\r\n").split("\t")
                if len(f) < 19:
                    continue
                code, prec, contest = f[0].strip(), f[5].strip(), f[11].strip()
                try:
                    reg[code][prec] = int(f[7] or 0)
                except ValueError:
                    continue
                cl = contest.lower()
                if FL_TOP[y] in cl and "lieutenant" in cl or (FL_TOP[y] == "president" and "president" in cl):
                    contests_seen[contest] += 1
                    try:
                        ballots[code] += int(f[18] or 0)
                    except ValueError:
                        pass
    print("FL", y, "top contests:", contests_seen.most_common(3), flush=True)
    for code in reg:
        out["FL"].setdefault(code, {})[y] = {"reg": sum(reg[code].values()), "ballots": ballots.get(code, 0)}
    tot = {"reg": sum(sum(v.values()) for v in reg.values()), "ballots": sum(ballots.values())}
    out["FL"].setdefault("_STATE", {})[y] = tot
    print("FL", y, len(reg), "counties", tot, flush=True)

if len(out["TX"]) < 200 or len(out["FL"]) < 60:
    sys.exit("too few counties parsed")
p = ROOT / "docs" / "data" / "history_2022_2024.json"
json.dump(out, open(p, "w"), separators=(",", ":"))
print("wrote", p, p.stat().st_size)
