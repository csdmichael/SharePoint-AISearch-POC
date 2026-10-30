"""Accuracy evaluation for the Foundry knowledge agent.

For every document the agent is allowed to see (Published, authoritative, AI-ready, General in the live index) it asks
a natural question and grades the answer against the authored content:

* the answer must cite the document's own SharePoint link, and
* it must state at least two of the document's key facts (token overlap with the authored "points"),
  or for meeting transcripts, reflect at least one spoken line.

It also asks about documents that are hidden by the filter and fails if the agent cites them.

Usage:  python scripts/evaluate_agent.py [--workers 4] [--threshold 0.9] [--limit N] [--report path.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import site_corpus_data as corpus  # noqa: E402

STATE = json.loads((ROOT / ".state" / "trusted-foundry-agent.json").read_text(encoding="utf-8"))
SEARCH_ENDPOINT = f"https://{STATE['searchServiceName']}.search.windows.net"
SEARCH_VERSION = "2026-08-01-preview"
INDEX = STATE["searchIndexName"]
BASE_FILTER = "lifecycle_status eq 'Published' and authoritative eq true and ai_ready eq true and sensitivity eq 'General'"
STOPWORDS = frozenset("""that this with from have will must shall should their there which into than then them they been being
each over under only also such when where while within without before after other about across between through during
more most some any all not are was were its the and for per via""".split())
COPY_SUFFIX = re.compile(r"\s\((edited\s)?copy\)$")
MAX_FACTS = 2


def az(*args: str) -> str:
    return subprocess.run(["az", *args], capture_output=True, text=True, shell=True, check=True).stdout.strip()


def http(method: str, url: str, headers: dict[str, str], body: object | None = None, timeout: int = 240) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(8):
        request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 7:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) or min(60, 4 * 2 ** attempt)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def search(body: dict) -> dict:
    key = az("search", "admin-key", "show", "--service-name", STATE["searchServiceName"],
             "--resource-group", STATE["resourceGroup"], "--query", "primaryKey", "-o", "tsv")
    return http("POST", f"{SEARCH_ENDPOINT}/indexes/{INDEX}/docs/search?api-version={SEARCH_VERSION}", {"api-key": key}, body)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{4,}", text.lower()) if t not in STOPWORDS}


def fact_hits(answer: str, facts: list[str]) -> int:
    answer_tokens = tokens(answer)
    hits = 0
    for fact in facts:
        wanted = tokens(fact)
        if wanted and len(wanted & answer_tokens) / len(wanted) >= 0.6:
            hits += 1
    return hits


def visible_filenames() -> set[str]:
    facets = search({"search": "*", "top": 0, "facets": ["title,count:500"], "filter": BASE_FILTER})
    return {f["value"] for f in facets["@search.facets"]["title"]}


def all_filenames() -> set[str]:
    facets = search({"search": "*", "top": 0, "facets": ["title,count:500"]})
    return {f["value"] for f in facets["@search.facets"]["title"]}


def build_cases(limit: int | None) -> list[dict]:
    visible, everything = visible_filenames(), all_filenames()
    docs_by_stem: dict[str, tuple[str, dict]] = {}
    for site, data in corpus.SITE_DATA.items():
        for department in data["departments"]:
            for doc in department["documents"]:
                docs_by_stem[slug(doc["title"])] = (site, doc)

    cases: list[dict] = []
    for filename in sorted(visible):
        stem, ext = filename.rsplit(".", 1)
        if COPY_SUFFIX.search(stem):
            continue
        if ext in ("txt", "vtt"):
            hit = next(((s, m) for s, d in corpus.SITE_DATA.items() for m in d["meetings"] if slug(m["title"]) == stem), None)
            if not hit:
                continue
            site, meeting = hit
            folder = ROOT / ".state" / "site-corpora" / site / corpus.SITE_DATA[site]["meetings_folder"]
            text = (folder / f"{stem}.txt").read_text(encoding="utf-8")
            lines = [ln.split(":", 1)[1].strip() for ln in text.splitlines() if ":" in ln and not ln.startswith("Meeting")]
            cases.append({"kind": "meeting", "file": filename, "stem": stem, "site": site, "facts": lines, "min_hits": 1,
                          "question": f"What did the team discuss in the {meeting['title']} meeting? Cite the transcript."})
        elif stem in docs_by_stem:
            site, doc = docs_by_stem[stem]
            cases.append({"kind": "document", "file": filename, "stem": stem, "site": site, "facts": list(doc["points"]),
                          "min_hits": min(2, len(doc["points"])),
                          "question": f"What are the key requirements in the {doc['title']}? Cite the document."})
            for point in doc["points"][:MAX_FACTS]:
                lead = " ".join(point.split()[:6]).rstrip(",.;:")
                cases.append({"kind": "fact", "file": filename, "stem": stem, "site": site, "facts": [point], "min_hits": 1,
                              "question": f"According to the {doc['title']}, what is required regarding \"{lead}\"?"})
    hidden = sorted(f for f in everything - visible if not COPY_SUFFIX.search(f.rsplit(".", 1)[0]) and f.rsplit(".", 1)[1] in ("docx", "pdf", "pptx", "xlsx"))
    for filename in hidden[::max(1, len(hidden) // 6)][:6]:
        stem = filename.rsplit(".", 1)[0]
        if stem in docs_by_stem:
            title = docs_by_stem[stem][1]["title"]
            cases.append({"kind": "hidden", "file": filename, "stem": stem, "site": docs_by_stem[stem][0], "facts": [], "min_hits": 0,
                          "question": f"What does the {title} say?"})
    curated = json.loads((ROOT / "config" / "agent-eval-questions.json").read_text(encoding="utf-8"))["questions"]
    for item in curated:
        cases.append({"kind": "curated", "file": item["cite"] or ",".join(item.get("hidden", [])), "stem": item["cite"] or "",
                      "site": "", "facts": [], "min_hits": 0, "question": item["q"], "curated": item})
    return cases[:limit] if limit else cases


class Foundry:
    def __init__(self) -> None:
        self._token, self._expires = "", 0.0

    def headers(self) -> dict[str, str]:
        if time.time() > self._expires:
            self._token = az("account", "get-access-token", "--resource", "https://ai.azure.com", "--query", "accessToken", "-o", "tsv")
            self._expires = time.time() + 900
        return {"Authorization": f"Bearer {self._token}"}

    def ask(self, question: str) -> tuple[str, list[str]]:
        project = STATE["projectEndpoint"].rstrip("/")
        conversation = http("POST", f"{project}/openai/v1/conversations", self.headers(), {})
        response = http("POST", f"{project}/openai/v1/responses", self.headers(), {
            "conversation": conversation["id"], "input": question,
            "agent_reference": {"type": "agent_reference", "name": STATE["agentName"]},
        })
        text = "\n".join(
            part["text"] for item in response.get("output", []) if isinstance(item.get("content"), list)
            for part in item["content"] if part.get("type") == "output_text"
        )
        retrieved = [item.get("output", "") for item in response.get("output", []) if item.get("type") == "mcp_call"]
        return text, retrieved


def cited(answer: str) -> str:
    urls = re.findall(r"\((https://[^\s)]+)\)", answer) + re.findall(r"https://[^\s)\]]+", answer)
    return urllib.parse.unquote(" ".join(urls)).lower()


def run_case(client: Foundry, case: dict) -> dict:
    started = time.time()
    try:
        answer, retrieved = client.ask(case["question"])
        error = None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        answer, retrieved, error = "", [], str(exc)
    links = cited(answer)
    stem_hit = case["file"].lower() in links or case["stem"] in links.replace("%20", "-")
    hits = fact_hits(answer, case["facts"])
    unknown = bool(re.search(r"\b(i don.t know|couldn.t (find|locate|verify|confirm)|could not (find|locate)|no evidence)\b", answer.lower()))
    if case["kind"] == "curated":
        spec = case["curated"]
        lowered = answer.lower()
        reasons = []
        if error:
            reasons.append("request failed: " + error)
        if spec["cite"] and spec["cite"] not in links.replace("%20", "-"):
            reasons.append(f"did not cite {spec['cite']}")
        reasons += [f"missing '{t}'" for t in spec["expect"] if t.lower() not in lowered]
        reasons += [f"contains '{t}'" for t in spec["forbid"] if t.lower() in lowered]
        reasons += [f"cited hidden {h}" for h in spec.get("hidden", []) if h in links.replace("%20", "-")]
        if spec["cite"] and unknown and not spec["expect"]:
            reasons.append("answered 'not found'")
        return {"kind": "curated", "file": case["file"] or "(hidden)", "question": case["question"], "ok": not reasons,
                "reason": "; ".join(reasons), "factHits": 0, "seconds": round(time.time() - started, 1), "answer": answer}
    if case["kind"] == "hidden":
        ok = error is None and not stem_hit
        reason = "" if ok else ("request failed: " + str(error)) if error else "cited a hidden document"
    else:
        ok = error is None and stem_hit and hits >= case["min_hits"]
        reasons = []
        if error:
            reasons.append("request failed: " + error)
        if not stem_hit:
            reasons.append("did not cite the document")
        if hits < case["min_hits"]:
            reasons.append(f"facts {hits}/{case['min_hits']}")
        if unknown:
            reasons.append("answered 'not found'")
        reason = "; ".join(reasons)
    return {**{k: case[k] for k in ("kind", "file", "question")}, "ok": ok, "reason": reason, "factHits": hits,
            "seconds": round(time.time() - started, 1), "answer": answer}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=0.9)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--report", default=str(ROOT / ".state" / "agent-eval.json"))
    args = parser.parse_args()

    cases = build_cases(args.limit)
    print(f"Evaluating {len(cases)} questions ({sum(c['kind'] == 'hidden' for c in cases)} hidden-document checks)...")
    client = Foundry()
    client.headers()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda case: run_case(client, case), cases))

    for result in results:
        print(f"[{'PASS' if result['ok'] else 'FAIL'}] {result['kind']:<8} {result['file']:<62} {result['seconds']:>5}s  {result['reason']}")
    scored = [r for r in results if r["kind"] != "hidden"]
    passed = sum(r["ok"] for r in scored)
    leaks = [r for r in results if r["kind"] == "hidden" and not r["ok"]]
    rate = passed / len(scored) if scored else 0.0
    print(f"\nAccuracy: {passed}/{len(scored)} = {rate:.0%} (threshold {args.threshold:.0%}); hidden-document leaks: {len(leaks)}")
    Path(args.report).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if rate >= args.threshold and not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
