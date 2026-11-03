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


def parse_uf_us(text: str):
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        st = (r.get("state") or r.get("State") or r.get("abbrv") or r.get("abbv") or "").strip()
        if not st:
            continue
        rec = {k: v for k, v in r.items()}
        def g(*names):
            for n in names:
                if n in r and str(r[n]).strip() not in ("", "NA", "N/A"):
                    return num(r[n])
            return None
        out.append(obs(st, "uf_state_row", None, as_of=r.get("date") or r.get("last_update") or r.get("updated"),
                       state=st,
                       voted_all=g("voted_all", "total_voted", "voted"),
                       voted_inperson=g("voted_inperson", "inperson", "in_person", "voted_ip"),
                       voted_mail=g("voted_mail", "mail_returned", "returned"),
                       requested_mail=g("requested_mail", "mail_requested", "requested"),
                       turnout_2022=g("turnout_2022", "total_2022", "votes_2022", "vep_turnout_2022", "turnout2022"),
                       raw=rec))
    return out


@source("uf_states", "UF Election Lab – early vote by state", "US", "early",
        "https://election.lab.ufl.edu/early-vote/2026-early-voting/",
        "Early in-person + returned mail ballots as compiled by Dr. Michael McDonald, UF Election Lab. Non-commercial use with attribution.")
def uf_states():
    return parse_uf_us(get(UF_BASE + "US.csv").text)


def parse_uf_tossup(text: str):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        key = r.get("key") or r.get("cd") or r.get("district")
        if not key:
            continue
        out.append(obs(key, "uf_tossup_row", None, raw=dict(r), state=(key.split("-")[0] if "-" in key else None)))
    return out


@source("uf_tossups", "UF Election Lab – House toss-up districts", "US", "early",
        "https://election.lab.ufl.edu/early-vote/2026-early-voting/",
        "Early vote in House toss-up districts (where states report by CD).")
def uf_tossups():
    return parse_uf_tossup(get(UF_BASE + "house_tossup_races.csv").text)


# ---------------------------------------------------------------- Texas SOS (civix EVR API)
TX_API = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile"
TX_ELECTION_ID = 53815  # 2026 NOVEMBER GENERAL ELECTION
TX_COUNTIES = ["HARRIS", "DALLAS", "TARRANT", "BEXAR", "TRAVIS", "COLLIN", "DENTON", "FORT BEND", "HIDALGO", "EL PASO", "WILLIAMSON"]


def tx_decode(payload: dict):
    return json.loads(base64.b64decode(payload["upload"]).decode("utf-8", "ignore").strip())


def parse_tx_turnout(d: dict, metric_prefix: str):
    """EVR JSON: {turnout_by_county:[{id,name,registered?,in_person?,mail?, cumulative...}], ...}"""
    out = []
    rows = d.get("turnout_by_county") or d.get("counties") or []
    as_of = d.get("early_voting_date") or d.get("date") or d.get("date_updated")
    tot = {}
    for r in rows:
        name = str(r.get("name") or r.get("county") or "").upper()
        fields = {k: r[k] for k in r if isinstance(r[k], (int, float, str))}
        def pick(*cands):
            for c in cands:
                for k in r:
                    if k.lower() == c:
                        return num(r[k])
            return None
        reg = pick("registered_voters", "reg_voters", "registered", "total_registered_voters")
        ip = pick("cumulative_in_person_voters", "cum_in_person", "in_person_cumulative", "cumulative_in_person", "in_person_voters", "voters")
        mail = pick("cumulative_by_mail_voters", "cum_mail", "mail_cumulative", "cumulative_mail", "by_mail_voters")
        allv = pick("cumulative_in_person_and_mail_voters", "cum_total", "total_cumulative", "cumulative_voters", "total_voters", "total")
        if allv is None and (ip is not None or mail is not None):
            allv = (ip or 0) + (mail or 0)
        for k, v in (("registered", reg), ("inperson", ip), ("mail", mail), ("total", allv)):
            if v is not None:
                tot[k] = tot.get(k, 0) + v
        if name in TX_COUNTIES:
            out.append(obs(name.title() + " County", f"{metric_prefix}_total", allv, as_of=as_of, state="TX",
                           registered=reg, inperson=ip, mail=mail, raw=fields))
    if tot:
        out.insert(0, obs("Texas (statewide)", f"{metric_prefix}_total", tot.get("total"), as_of=as_of, state="TX",
                          registered=tot.get("registered"), inperson=tot.get("inperson"), mail=tot.get("mail")))
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
