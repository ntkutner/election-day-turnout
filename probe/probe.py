"""Fetch each URL in probe/urls.txt and save raw bodies + a summary of
data-looking links (json/csv/xlsx/api/script bundles) for parser development."""
import json, re, sys, pathlib, urllib.parse
import requests

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "raw"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
LINK_RE = re.compile(r"""(?:href|src|data-url|url)\s*[=:]\s*["']([^"']+)["']""", re.I)
DATA_HINT = re.compile(r"(\.json|\.csv|\.xlsx?|\.pdf|/api/|turnout|check-?in|early.?vot|absentee|\.js(\?|$))", re.I)

def lines(path):
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        ident, url = [p.strip() for p in ln.split("|", 1)]
        yield ident, url

def main(list_file):
    summary = {}
    for ident, url in lines(ROOT / list_file):
        rec = {"url": url}
        try:
            r = requests.get(url, headers=UA, timeout=30, allow_redirects=True)
            rec.update(status=r.status_code, final_url=r.url, ctype=r.headers.get("content-type", ""), bytes=len(r.content))
            ext = ".json" if "json" in rec["ctype"] else ".csv" if "csv" in rec["ctype"] else ".pdf" if "pdf" in rec["ctype"] else ".html"
            (OUT / f"{ident}{ext}").write_bytes(r.content[:3_000_000])
            if ext == ".html":
                links = set()
                for m in LINK_RE.findall(r.text):
                    if DATA_HINT.search(m):
                        links.add(urllib.parse.urljoin(r.url, m))
                rec["data_links"] = sorted(links)[:200]
        except Exception as e:  # noqa
            rec["error"] = repr(e)
        summary[ident] = rec
        print(ident, rec.get("status"), rec.get("bytes"), rec.get("error", ""), flush=True)
    (OUT / f"_summary_{pathlib.Path(list_file).stem}.json").write_text(json.dumps(summary, indent=1))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "urls.txt")
