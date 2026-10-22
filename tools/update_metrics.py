#!/usr/bin/env python3
"""Enrich the JEDI Lab bibliography with citation counts and journal rankings.

Citations, journal identity (ISSN) and the ABDC and Norwegian Register levels
come from OpenAlex. The rankings are the journal lists OpenAlex loads from each
maintainer's published file, matched by ISSN; the loaded edition is recorded.
Licensed or historical rankings (for example JCR quartiles, AJG ratings or an
earlier Norwegian Register edition) can be supplied in an administrator-
maintained CSV file. The output is a separate data file; publications.json is
never modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "publications.json"
DEFAULT_OUTPUT = ROOT / "data" / "metrics.json"
DEFAULT_RANKINGS = ROOT / "data" / "journal_rankings.csv"
API = "https://api.openalex.org"
USER_AGENT = "JEDI-Lab-Knowledge-Graph/1.0"
DOI_BATCH = 50

# OpenAlex source-list ids mapped to (ranking system, displayed value).
LIST_RANKINGS = {
    "abdc-a-star": ("abdc", "A*"),
    "abdc-a": ("abdc", "A"),
    "abdc-b": ("abdc", "B"),
    "abdc-c": ("abdc", "C"),
    "norway-2": ("norway", "Level 2"),
    "norway-1": ("norway", "Level 1"),
}
SYSTEM_NAMES = {
    "abdc": "ABDC Journal Quality List",
    "norway": "Norwegian Register",
}


def normalize_doi(value: str) -> str:
    """Return a bare, lower-case DOI (10.xxxx/...) or an empty string."""
    match = re.search(r"10\.\d{4,9}/\S+", str(value or ""))
    return match.group(0).rstrip(".,;)").casefold() if match else ""


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"&", " and ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_issn(value: str) -> str:
    text = re.sub(r"[^0-9Xx]", "", str(value or "")).upper()
    return f"{text[:4]}-{text[4:]}" if len(text) == 8 else ""


def normalize_journal(value: str) -> str:
    """Journal name without trailing volume numbers or punctuation from the citation."""
    text = re.sub(r",\s*\d.*$", "", str(value or ""))
    return normalize_title(text)


class OpenAlex:
    def __init__(self, api_key: str = "", delay: float = 0.15) -> None:
        self.api_key = api_key
        self.delay = delay
        self.cost = 0.0

    def get(self, path: str, params: dict[str, str]) -> dict[str, object]:
        query = dict(params)
        if self.api_key:
            query["api_key"] = self.api_key
        url = f"{API}{path}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.cost += float(payload.get("meta", {}).get("cost_usd") or 0)
                    time.sleep(self.delay)
                    return payload
            except urllib.error.HTTPError as error:
                if error.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                detail = error.read().decode("utf-8", "replace")[:300]
                raise RuntimeError(f"OpenAlex returned HTTP {error.code}: {detail}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"Could not reach OpenAlex: {error}") from error
        raise RuntimeError("OpenAlex request failed.")


WORK_FIELDS = "id,doi,display_name,publication_year,cited_by_count,counts_by_year,primary_location"


def fetch_works_by_doi(client: OpenAlex, dois: list[str]) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    usable = [doi for doi in dois if "|" not in doi and "," not in doi]
    for start in range(0, len(usable), DOI_BATCH):
        batch = usable[start:start + DOI_BATCH]
        payload = client.get("/works", {
            "filter": f"doi:{'|'.join(batch)}",
            "select": WORK_FIELDS,
            "per-page": "100",
        })
        for work in payload.get("results", []):
            doi = normalize_doi(work.get("doi") or "")
            if doi:
                found[doi] = work
    return found


def choose_title_match(
    publication: dict[str, object],
    candidates: list[dict[str, object]],
) -> tuple[dict[str, object] | None, str]:
    """Accept a title search result only when it is unambiguous.

    A candidate must have the same normalised title and a publication year
    within one year. If several remain (for example a preprint and the journal
    version), the journal name breaks the tie; otherwise it is left for review.
    """
    title = normalize_title(str(publication.get("title", "")))
    year = int(publication.get("year") or 0)
    exact = [
        work for work in candidates
        if normalize_title(str(work.get("display_name") or "")) == title
        and abs(int(work.get("publication_year") or 0) - year) <= 1
    ]
    if len(exact) == 1:
        return exact[0], "matched"
    if not exact:
        return None, "unmatched"
    journal = normalize_journal(str(publication.get("journal", "")))
    same_journal = [
        work for work in exact
        if journal and normalize_title(source_of(work).get("display_name") or "") == journal
    ]
    if len(same_journal) == 1:
        return same_journal[0], "matched"
    return None, "ambiguous"


def search_by_title(client: OpenAlex, publication: dict[str, object]) -> list[dict[str, object]]:
    year = int(publication.get("year") or 0)
    payload = client.get("/works", {
        # OpenAlex reads * and ? as wildcards, which the stemmed search rejects.
        "search": re.sub(r"[*?]", " ", str(publication.get("title", "")))[:250],
        "filter": f"publication_year:{year - 1}-{year + 1}",
        "select": WORK_FIELDS,
        "per-page": "10",
    })
    return list(payload.get("results", []))


def source_of(work: dict[str, object]) -> dict[str, object]:
    location = work.get("primary_location") or {}
    return (location.get("source") or {}) if isinstance(location, dict) else {}


def fetch_list_editions(client: OpenAlex) -> dict[str, dict[str, str]]:
    payload = client.get("/source-lists", {"per-page": "200"})
    editions: dict[str, dict[str, str]] = {}
    for record in payload.get("results", []):
        list_id = str(record.get("id", "")).rsplit("/", 1)[-1]
        if list_id in LIST_RANKINGS:
            editions[list_id] = {
                "edition": str(record.get("list_version") or ""),
                "maintainer": str(record.get("maintainer") or ""),
                "url": str(record.get("url") or ""),
            }
    return editions


def list_rankings(source: dict[str, object], editions: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rankings = []
    for list_id in source.get("listed_in") or []:
        if list_id not in LIST_RANKINGS:
            continue
        system, value = LIST_RANKINGS[list_id]
        rankings.append({
            "system": system,
            "value": value,
            "edition": editions.get(list_id, {}).get("edition", ""),
            "matched_by": "issn",
            "source": "OpenAlex source lists",
        })
    return rankings


def read_ranking_csv(path: Path) -> list[dict[str, str]]:
    """Read administrator-supplied rankings.

    Required columns: system, value, edition_year, and issn and/or journal.
    Optional: edition (label), source.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"system", "value", "edition_year"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, start=2):
            system = (row.get("system") or "").strip()
            value = (row.get("value") or "").strip()
            issn = normalize_issn(row.get("issn") or "")
            journal = normalize_journal(row.get("journal") or "")
            if not system or not value or not (issn or journal):
                continue
            try:
                edition_year = int(str(row.get("edition_year")).strip())
            except ValueError as error:
                raise ValueError(f"{path}:{line}: edition_year must be a year.") from error
            rows.append({
                "system": system,
                "value": value,
                "edition_year": edition_year,
                "edition": (row.get("edition") or "").strip() or str(edition_year),
                "issn": issn,
                "journal": journal,
                "source": (row.get("source") or "").strip() or path.name,
            })
        return rows


def csv_rankings(
    publication: dict[str, object],
    issns: set[str],
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Pick, per system, the edition in force when the paper was published.

    That is the latest edition at or before the publication year; if every
    edition is later, the earliest one is used. ISSN matches take precedence
    over exact journal-name matches.
    """
    journal = normalize_journal(str(publication.get("journal", "")))
    year = int(publication.get("year") or 0)
    by_system: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for row in rows:
        if row["issn"] and row["issn"] in issns:
            method = "issn"
        elif not row["issn"] and journal and row["journal"] == journal:
            method = "journal title"
        else:
            continue
        by_system.setdefault(row["system"], []).append((method, row))
    rankings = []
    for system, matches in by_system.items():
        if any(method == "issn" for method, _ in matches):
            matches = [match for match in matches if match[0] == "issn"]
        earlier = [match for match in matches if match[1]["edition_year"] <= year]
        method, row = (
            max(earlier, key=lambda match: match[1]["edition_year"]) if earlier
            else min(matches, key=lambda match: match[1]["edition_year"])
        )
        rankings.append({
            "system": system,
            "value": row["value"],
            "edition": row["edition"],
            "matched_by": method,
            "source": row["source"],
        })
    return rankings


def build_record(
    publication: dict[str, object],
    work: dict[str, object] | None,
    method: str,
    retrieved: str,
    editions: dict[str, dict[str, str]],
    ranking_rows: list[dict[str, str]],
) -> dict[str, object] | None:
    record: dict[str, object] = {}
    issns: set[str] = set()
    if work:
        source = source_of(work)
        issns = {normalize_issn(issn) for issn in (source.get("issn") or [])} - {""}
        record["match"] = {"method": method, "openalex": work.get("id")}
        if source:
            record["source"] = {
                "name": source.get("display_name") or "",
                "issn_l": source.get("issn_l") or "",
                "issn": sorted(issns),
            }
        record["citations"] = {
            "provider": "OpenAlex",
            "total": int(work.get("cited_by_count") or 0),
            "by_year": {
                str(entry["year"]): int(entry["cited_by_count"])
                for entry in sorted(work.get("counts_by_year") or [], key=lambda entry: entry["year"])
                if entry.get("cited_by_count")
            },
            "retrieved": retrieved,
        }
    rankings = list_rankings(source_of(work), editions) if work else []
    supplied = csv_rankings(publication, issns, ranking_rows)
    supplied_systems = {ranking["system"] for ranking in supplied}
    rankings = [ranking for ranking in rankings if ranking["system"] not in supplied_systems] + supplied
    if rankings:
        record["rankings"] = rankings
    return record or None


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argument_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Bibliography JSON.")
    argument_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Metrics JSON to write.")
    argument_parser.add_argument(
        "--rankings", type=Path, default=DEFAULT_RANKINGS,
        help="Optional administrator-maintained rankings CSV (used if it exists).",
    )
    argument_parser.add_argument(
        "--match-titles", action="store_true",
        help="Also look up publications without a DOI by exact title and year (about $0.001 per lookup).",
    )
    args = argument_parser.parse_args()
    client = OpenAlex(api_key=os.environ.get("OPENALEX_API_KEY", ""))
    retrieved = date.today().isoformat()

    try:
        dataset = json.loads(args.input.read_text(encoding="utf-8"))
        publications = dataset["publications"]
        ranking_rows = read_ranking_csv(args.rankings) if args.rankings.exists() else []
        editions = fetch_list_editions(client)
        dois = sorted({normalize_doi(str(p.get("doi", ""))) for p in publications} - {""})
        by_doi = fetch_works_by_doi(client, dois)

        works: dict[str, dict[str, object]] = {}
        review: list[dict[str, object]] = []
        counts = {"doi": 0, "title": 0, "unmatched": 0, "ambiguous": 0}
        match_titles = args.match_titles
        for publication in publications:
            doi = normalize_doi(str(publication.get("doi", "")))
            work, method, outcome = None, "", "unmatched"
            if doi:
                work, method = by_doi.get(doi), "doi"
                if work:
                    outcome = "doi"
                else:
                    review.append({"id": publication["id"], "title": publication["title"], "reason": "DOI not found in OpenAlex"})
            elif match_titles:
                try:
                    candidates = search_by_title(client, publication)
                except RuntimeError as error:
                    # Keep the DOI results if the daily budget runs out part-way.
                    print(f"Warning: title matching stopped: {error}", file=sys.stderr)
                    match_titles = False
                    candidates = []
                work, outcome = choose_title_match(publication, candidates)
                method = "title"
                if outcome == "matched":
                    outcome = "title"
                elif outcome == "ambiguous":
                    review.append({"id": publication["id"], "title": publication["title"], "reason": "Several OpenAlex works share this title"})
            counts[outcome] += 1
            record = build_record(publication, work, method, retrieved, editions, ranking_rows)
            if record:
                works[str(publication["id"])] = record

        sources = {
            "openalex": {
                "name": "OpenAlex",
                "url": "https://openalex.org/",
                "retrieved": retrieved,
                "note": "Citation counts are OpenAlex estimates; per-year counts cover roughly the last ten years.",
            },
        }
        for list_id, edition in editions.items():
            system = LIST_RANKINGS[list_id][0]
            sources.setdefault(system, {
                "name": SYSTEM_NAMES[system],
                "maintainer": edition["maintainer"],
                "url": edition["url"],
                "edition": edition["edition"],
                "via": "OpenAlex source lists (current edition, matched by ISSN)",
            })
        for row in ranking_rows:
            sources.setdefault(row["system"], {"name": row["system"], "via": row["source"]})
        output = {
            "generated": retrieved,
            "bibliography_updated": dataset.get("updated", ""),
            "sources": sources,
            "summary": {
                "publications": len(publications),
                "matched_by_doi": counts["doi"],
                "matched_by_title": counts["title"],
                "ambiguous": counts["ambiguous"],
                "unmatched": counts["unmatched"],
                "with_rankings": sum(1 for record in works.values() if record.get("rankings")),
            },
            "works": works,
            "review": review,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, KeyError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    summary = output["summary"]
    print(
        f"Wrote metrics for {len(works)} of {summary['publications']} publications to {args.output}: "
        f"{summary['matched_by_doi']} matched by DOI, {summary['matched_by_title']} by title, "
        f"{summary['ambiguous']} ambiguous, {summary['unmatched']} unmatched, "
        f"{summary['with_rankings']} with a journal ranking; {len(review)} records to review. "
        f"OpenAlex cost ${client.cost:.4f}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
