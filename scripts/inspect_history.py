"""One-off: download TLC general-election VTD datasets and print their structure."""
import io, zipfile, requests, csv
URLS = {
 "2024": "https://data.capitol.texas.gov/dataset/35b16aee-0bb0-4866-b1ec-859f1f044241/resource/e1cd6332-6a7a-4c78-ad2a-852268f6c7a2/download/2024-general-vtds-election-data.zip",
 "2022": "https://data.capitol.texas.gov/dataset/35b16aee-0bb0-4866-b1ec-859f1f044241/resource/b9ebdbdb-3e31-4c98-b158-0e2993b05efc/download/2022-general-vtds-election-data.zip",
}
out = open("probe/raw/_tlc_inspect.txt", "w")
for y, u in URLS.items():
    r = requests.get(u, timeout=300, headers={"User-Agent": "Mozilla/5.0"}); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    print(f"## {y} {len(r.content)} bytes", file=out)
    for n in z.namelist():
        print("  ", n, z.getinfo(n).file_size, file=out)
    for n in z.namelist():
        if n.lower().endswith((".csv", ".txt")) and any(k in n.lower() for k in ("turnout", "returns", "president", "governor", "_vr", "total")):
            with z.open(n) as fh:
                head = [next(fh, b"").decode("latin-1").rstrip() for _ in range(4)]
            print(f"--- {n}", *head, sep="\n", file=out)
    # first 3 csvs regardless
    for n in [x for x in z.namelist() if x.lower().endswith(".csv")][:3]:
        with z.open(n) as fh:
            head = [next(fh, b"").decode("latin-1").rstrip() for _ in range(3)]
        print(f"--- {n}", *head, sep="\n", file=out)
out.close()
