"""Source scrapers. Each @source function fetches one public page/file and returns observations.
Parsers are split out (parse_*) so they can be tested offline against probe/raw captures."""
from __future__ import annotations
import base64, csv, io, json, re, html as htmllib
from common import source, get, num, obs

# ---------------------------------------------------------------- helpers

def clean_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", htmllib.unescape(page)).strip()


# ---------------------------------------------------------------- UF Election Lab (national early vote)
UF_BASE = "https://election.lab.ufl.edu/data-downloads/earlyvote/2026/"


def _n(r, k):
    v = (r.get(k) or "").strip()
    return None if v in ("", "NA", "N/A") else num(v)


def parse_uf_us(text: str):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        st = (r.get("state_abbv") or "").strip()
        if not st:
            continue
        out.append(obs(st, "early_total", _n(r, "voted_all"), as_of=r.get("last_update"), state=st,
                       name=r.get("state"), turnout_2022=_n(r, "turn_2022"),
                       inperson=_n(r, "inperson_all"), mail_returned=_n(r, "accept_all"),
                       mail_requested=_n(r, "request_all"), voted_dem=_n(r, "voted_dem"),
                       voted_rep=_n(r, "voted_rep"), voted_none=_n(r, "voted_none"),
                       updated_today=(r.get("updates_today") or "0").strip() not in ("0", ""),
                       data_source=r.get("data_source")))
    if not out:
        raise ValueError("UF US.csv: no rows")
    return out


@source("uf_states", "UF Election Lab – early vote by state", "US", "early",
        "https://election.lab.ufl.edu/early-vote/2026-early-voting/",
        "Early in-person + returned mail ballots compiled by Dr. Michael McDonald, UF Election Lab (non-commercial use, attribution required). Party = party registration, not vote choice.")
def uf_states():
    return parse_uf_us(get(UF_BASE + "US.csv").text)


def parse_uf_cd(text: str, st: str):
    """Sum county pieces to district totals."""
    agg = {}
    for r in csv.DictReader(io.StringIO(text)):
        cd = (r.get("cd") or "").strip()
        if not cd:
            continue
        key = f"{st}-{int(cd):02d}" if cd.isdigit() else f"{st}-{cd}"
        a = agg.setdefault(key, {})
        for k in ("voted_all", "voted_dem", "voted_rep", "voted_none", "request_all", "accept_all"):
            v = _n(r, k)
            if v is not None:
                a[k] = a.get(k, 0) + v
    return agg


@source("uf_tossups", "UF Election Lab – House toss-up districts", "US", "early",
        "https://election.lab.ufl.edu/early-vote/2026-early-voting/",
        "Early vote in House toss-up districts, from states that report early vote by congressional district. Ratings as compiled by UF Election Lab.")
def uf_tossups():
    rows = list(csv.DictReader(io.StringIO(get(UF_BASE + "house_tossup_races.csv").text)))
    by_state = {}
    for st in sorted({r["state"] for r in rows}):
        try:
            by_state[st] = parse_uf_cd(get(UF_BASE + f"{st}_cd.csv").text, st)
        except Exception:
            by_state[st] = {}
    out = []
    for r in rows:
        key = r["key"]
        d = by_state.get(r["state"], {}).get(key, {})
        ratings = {k: r.get(k) for k in ("cook", "sabato", "ie") if r.get(k)}
        out.append(obs(key, "early_total", d.get("voted_all"), state=r["state"], n_tossup=_n(r, "n_tossup_outlets"),
                       ratings=ratings, voted_dem=d.get("voted_dem"), voted_rep=d.get("voted_rep"),
                       voted_none=d.get("voted_none"), mail_requested=d.get("request_all"), mail_returned=d.get("accept_all")))
    return out


# ---------------------------------------------------------------- Texas SOS (civix EVR API)
TX_API = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile"
TX_ELECTION_ID = 53815  # 2026 NOVEMBER GENERAL ELECTION
TX_COUNTIES = ["HARRIS", "DALLAS", "TARRANT", "BEXAR", "TRAVIS", "COLLIN", "DENTON", "FORT BEND", "HIDALGO", "EL PASO", "WILLIAMSON"]


def tx_decode(payload: dict):
    return json.loads(base64.b64decode(payload["upload"]).decode("utf-8", "ignore").strip())


def parse_tx_turnout(d: dict, kind: str):
    """kind 'early': cumulative EV through date. kind 'eday': in_person_votes_on_date = Election Day in-person."""
    rows = d.get("turnout_by_county") or []
    as_of = d.get("early_voting_date")
    out, tot = [], {"registered": 0, "inperson": 0, "mail": 0, "eday": 0}
    for r in rows:
        reg = num(r.get("registered_voters")) or 0
        ip_cum = num(r.get("total_in_person_votes_for_election")) or 0
        mail = num(r.get("total_mail_votes_for_election")) or 0
        on_date = num(r.get("in_person_votes_on_date")) or 0
        tot["registered"] += reg; tot["inperson"] += ip_cum; tot["mail"] += mail; tot["eday"] += on_date
        name = str(r.get("name", "")).upper()
        if name in TX_COUNTIES:
            if kind == "early":
                out.append(obs(name.title() + " County", "early_total", ip_cum + mail, as_of=as_of, state="TX",
                               registered=reg, inperson=ip_cum, mail=mail))
            else:
                out.append(obs(name.title() + " County", "eday_checkins", on_date, as_of=as_of, state="TX", registered=reg))
    if not rows:
        raise ValueError("TX: no counties")
    if kind == "early":
        out.insert(0, obs("Texas (statewide)", "early_total", tot["inperson"] + tot["mail"], as_of=as_of, state="TX",
                          registered=tot["registered"], inperson=tot["inperson"], mail=tot["mail"]))
    else:
        out.insert(0, obs("Texas (statewide)", "eday_checkins", tot["eday"], as_of=as_of, state="TX",
                          registered=tot["registered"],
                          counties_reporting=sum(1 for r in rows if (num(r.get("in_person_votes_on_date")) or 0) > 0)))
    return out


def tx_fetch(type_, date):
    r = get(TX_API, params={"type": type_, "electionId": TX_ELECTION_ID, "electionDate": date},
            headers={"Content-Type": "application/json"})
    return tx_decode(r.json())


@source("tx_early", "Texas SOS – early vote by county (final)", "TX", "early",
        "https://goelect.txelections.civixapps.com/ivis-evr-ui/evr",
        "Cumulative in-person + mail early votes through the last day of early voting (Oct 30).")
def tx_early():
    return parse_tx_turnout(tx_fetch("EVR_EARLYVOTING", "10/30/2026"), "early")


@source("tx_eday", "Texas SOS – Election Day turnout by county", "TX", "eday",
        "https://goelect.txelections.civixapps.com/ivis-evr-ui/evr",
        "Counties report Election Day turnout to the SOS; often posts after polls close.")
def tx_eday():
    return parse_tx_turnout(tx_fetch("EVR_ELECTIONDAYTURNOUT", "11/03/2026"), "eday")


# ---------------------------------------------------------------- Broward County, FL (live TED widget)

def parse_broward(page: str):
    t = clean_text(page)
    def grab(label):
        m = re.search(label + r"\s*([\d,]+)", t)
        return num(m.group(1)) if m else None
    eligible, cast = grab("Eligible Voters"), grab("Ballots Cast")
    vbm, ev, ed, prov = grab("Vote By Mail"), grab("Early Vote"), grab("Election Day"), grab("Provisional")
    if cast is None:
        raise ValueError("Broward widget: 'Ballots Cast' not found")
    common = dict(state="FL", registered=eligible, mail=vbm, early=ev, eday=ed, provisional=prov)
    return [obs("Broward County", "eday_checkins", ed, **common),
            obs("Broward County", "total_voted", cast, **common)]


@source("fl_broward", "Broward County SOE – live turnout", "FL", "eday",
        "https://my.browardvotes.gov/TEDElectionLink/TurnOutWidget/dashboard/view/turnout-summary")
def fl_broward():
    return parse_broward(get("https://my.browardvotes.gov/TEDElectionLink/TurnOutWidget/dashboard/view/turnout-summary").text)


# ---------------------------------------------------------------- NYC Board of Elections (check-ins page)
NYC_BOROS = ["Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island"]


def parse_nyc(page: str):
    t = clean_text(page)
    # Blocks look like: "October 24, 2026 - Day 1 Manhattan - 24,704 Bronx - 9,994 ... *Unofficial ... 86,215"
    blocks = re.split(r"(?=(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, 2026)", t)
    days = []
    for b in blocks:
        m = re.match(r"((?:October|November) \d{1,2}, 2026)\s*-?\s*([^M]{0,40}?)\s*Manhattan", b)
        if not m:
            continue
        boros = {}
        for bo in NYC_BOROS:
            mm = re.search(bo + r"\s*[-–:]\s*([\d,]+)", b)
            if mm:
                boros[bo] = num(mm.group(1))
        if boros:
            days.append({"date": m.group(1), "label": m.group(2).strip(" -"), "boros": boros, "total": sum(boros.values())})
    if not days:
        raise ValueError("NYC: no check-in blocks found")
    out = []
    ev = [d for d in days if d["date"].startswith("October") or d["date"] in ("November 1, 2026",)]
    ed = [d for d in days if d["date"] == "November 3, 2026" or "election day" in d["label"].lower()]
    if ev:
        last = max(ev, key=lambda d: d["total"])  # cumulative counts; take the largest (final)
        out.append(obs("New York City", "early_inperson", last["total"], as_of=last["date"], state="NY", boroughs=last["boros"]))
    if ed:
        last = ed[-1]
        out.append(obs("New York City", "eday_checkins", last["total"], as_of=last["date"] + " " + last["label"], state="NY", boroughs=last["boros"]))
    return out


@source("ny_nyc", "NYC Board of Elections – voter check-ins", "NY", "eday",
        "https://vote.nyc/page/early-voting-check-ins",
        "BOE posts cumulative check-ins; Election Day updates appear on this page / @BOENYC when released.")
def ny_nyc():
    return parse_nyc(get("https://vote.nyc/page/early-voting-check-ins").text)


# ---------------------------------------------------------------- Clark County, NV (early vote turnout)

def parse_clark_ev(page: str):
    t = clean_text(page)
    m = re.search(r"Accumulated Total\s*([\d,]+)", t)
    if not m:
        raise ValueError("Clark: Accumulated Total not found")
    return [obs("Clark County", "early_inperson", num(m.group(1)), state="NV")]


@source("nv_clark_ev", "Clark County, NV – early in-person turnout", "NV", "early",
        "https://elections.clarkcountynv.gov/ElectionResultsTV/evturnout.aspx")
def nv_clark_ev():
    return parse_clark_ev(get("https://elections.clarkcountynv.gov/ElectionResultsTV/evturnout.aspx").text)


# ---------------------------------------------------------------- Florida ENR (enr.electionsfl.org) – ballots cast once results post
FL_ENR = {
    "Miami-Dade County": "https://enr.electionsfl.org/DAD/4087/Summary/",
    "Duval County": "https://enr.electionsfl.org/DUV/4076/Summary/",
}


def parse_fl_enr(page: str, county: str):
    t = clean_text(page)
    def grab(label):
        m = re.search(label + r":\s*([\d,]+|Not Reported)", t)
        return None if not m or m.group(1) == "Not Reported" else num(m.group(1))
    upd = re.search(r"last updated at:\s*([0-9/]+ [0-9:]+ [ap]m)", t)
    reg, cast = grab("Registered Voters"), grab("Ballots Cast")
    if reg is None:
        raise ValueError("ENR: header not found")
    return [obs(county, "total_voted", cast, as_of=upd.group(1) if upd else None, state="FL", registered=reg,
                eday=grab("Election Day"), early=grab("Early Votes"), mail=grab("Vote By Mail"))]


def _mk_enr(county, url):
    sid = "fl_enr_" + re.sub(r"[^a-z]", "", county.lower().replace("county", ""))
    @source(sid, f"{county} – FL ENR ballots cast", "FL", "total", url,
            "Ballots cast by method from the official results site; populates after polls close (7pm ET).")
    def _f():
        return parse_fl_enr(get(url).text, county)
    return _f


for _c, _u in FL_ENR.items():
    _mk_enr(_c, _u)


# ---------------------------------------------------------------- Florida: VR Systems Turnout Quick View (S3 JSON, ~60 counties)
TQV = "https://s3.amazonaws.com/turnoutquickview.electionsfl.org/"
FL_NAMES = {"ALA": "Alachua", "BAK": "Baker", "BAY": "Bay", "BRA": "Bradford", "BRE": "Brevard", "BRO": "Broward", "CAL": "Calhoun",
    "CHA": "Charlotte", "CIT": "Citrus", "CLA": "Clay", "CLL": "Collier", "CLM": "Columbia", "DAD": "Miami-Dade", "DES": "DeSoto",
    "DIX": "Dixie", "DUV": "Duval", "ESC": "Escambia", "FLA": "Flagler", "FRA": "Franklin", "GAD": "Gadsden", "GIL": "Gilchrist",
    "GLA": "Glades", "GUL": "Gulf", "HAM": "Hamilton", "HAR": "Hardee", "HEN": "Hendry", "HER": "Hernando", "HIG": "Highlands",
    "HIL": "Hillsborough", "HOL": "Holmes", "IND": "Indian River", "JAC": "Jackson", "JEF": "Jefferson", "LAF": "Lafayette",
    "LAK": "Lake", "LEE": "Lee", "LEO": "Leon", "LEV": "Levy", "LIB": "Liberty", "MAD": "Madison", "MAN": "Manatee", "MON": "Monroe",
    "MRN": "Marion", "MRT": "Martin", "NAS": "Nassau", "OKA": "Okaloosa", "OKE": "Okeechobee", "ORA": "Orange", "OSC": "Osceola",
    "PAL": "Palm Beach", "PAS": "Pasco", "PIN": "Pinellas", "POL": "Polk", "PUT": "Putnam", "SAN": "Santa Rosa", "SAR": "Sarasota",
    "SEM": "Seminole", "STJ": "St. Johns", "STL": "St. Lucie", "SUM": "Sumter", "SUW": "Suwannee", "TAY": "Taylor", "UNI": "Union",
    "VOL": "Volusia", "WAK": "Wakulla", "WAL": "Walton", "WAS": "Washington"}
METHODS = ("Mail", "EarlyVoting", "ElectionDay")


def parse_tqv(d: dict, code: str):
    s = d.get("Summary", {})
    party = d.get("Turnout", {}).get("PartyType", {}) or {}
    by_m = {m: 0 for m in METHODS}
    by_p = {}
    for p, v in party.items():
        grp = p if p in ("DEM", "REP", "NPA") else "OTH"
        for m in METHODS:
            n = v.get(m) or 0
            by_m[m] += n
            by_p.setdefault(grp, {mm: 0 for mm in METHODS})[m] += n
    total = sum(by_m.values())
    name = (FL_NAMES.get(code) or s.get("CountyName", code).title()) + " County"
    return obs(name, "eday_checkins", by_m["ElectionDay"], as_of=s.get("LastUpdatedTime"), state="FL",
               county_code=code, registered=s.get("TotalRegisteredVoters"), mail=by_m["Mail"], early=by_m["EarlyVoting"],
               eday=by_m["ElectionDay"], total=total, party=by_p)


def tqv_county(code):
    idx = get(TQV + f"data/FL/{code}/index.json").json()
    for eid in sorted(idx, reverse=True):
        d = get(TQV + f"data/FL/{code}/{eid}/data.json").json()
        if d.get("Summary", {}).get("ElectionDate") == "11/03/2026":
            return parse_tqv(d, code)
    return None


@source("fl_tqv", "Florida counties – VR Systems Turnout Quick View", "FL", "eday",
        "https://tqv.vrswebapps.com/?state=FL&county=ORA&election=301",
        "Live ballots cast by method and party registration, published by each county Supervisor of Elections via VR Systems. Party = registration, not vote choice.")
def fl_tqv():
    from concurrent.futures import ThreadPoolExecutor
    listing = get(TQV, params={"prefix": "data/FL/", "delimiter": "/"}).text
    codes = re.findall(r"<Prefix>data/FL/([A-Z]{3})/</Prefix>", listing) or list(FL_NAMES)
    def safe(c):
        try:
            return tqv_county(c)
        except Exception:
            return None
    with ThreadPoolExecutor(12) as ex:
        rows = [r for r in ex.map(safe, codes) if r]
    if not rows:
        raise RuntimeError("no TQV counties returned 11/03/2026 data")
    agg = {k: sum((r.get(k) or 0) for r in rows) for k in ("registered", "mail", "early", "eday", "total")}
    party = {}
    for r in rows:
        for p, v in r["party"].items():
            for m, n in v.items():
                party.setdefault(p, {mm: 0 for mm in METHODS})[m] += n
    latest = max((r["as_of"] or "") for r in rows)
    rows.sort(key=lambda r: -(r["registered"] or 0))
    return [obs(f"Florida ({len(rows)} counties)", "eday_checkins", agg["eday"], as_of=latest, state="FL",
                counties=len(rows), party=party, **agg)] + rows


# ---------------------------------------------------------------- Texas counties: live Election Day check-ins from county dashboards
DALLAS_FS = "https://services3.arcgis.com/zqe2kwz79KUqUvxC/arcgis/rest/services/Vote_Center_Finder_view/FeatureServer/4/query"


def parse_dallas(d: dict):
    feats = d.get("features") or []
    if not feats:
        raise ValueError("Dallas: no vote centers")
    a = [f["attributes"] for f in feats]
    a = [x for x in a if (x.get("L_Crnt_Sta") == "Active") and str(x.get("L_Poll_VC") or "").startswith("V")]
    today = sum((x.get("C_Daily_Tot") or 0) for x in a)
    reporting = sum(1 for x in a if (x.get("C_Daily_Tot") or 0) > 0)
    waits = [x.get("C_Wait_Tim") for x in a if isinstance(x.get("C_Wait_Tim"), (int, float))]
    return [obs("Dallas County", "eday_checkins", today, state="TX", vote_centers=len(a), centers_reporting=reporting,
                max_wait=max(waits) if waits else None)]


@source("tx_dallas", "Dallas County Elections – live vote center counts", "TX", "eday",
        "https://experience.arcgis.com/experience/8204fc2e36cd4fac8729efcedd4fda7f/page/Page?views=Election-Day",
        "Sum of today's voter counts at every active Election Day vote center (IDs V*), same filter as the county's wait-time map.")
def tx_dallas():
    d = get(DALLAS_FS, params={"where": "L_Crnt_Sta = 'Active' AND L_Poll_VC LIKE 'V%'", "outFields": "L_Crnt_Sta,L_Poll_VC,C_Daily_Tot,C_Wait_Tim",
                                "returnGeometry": "false", "resultRecordCount": 2000, "f": "json"}).json()
    return parse_dallas(d)
