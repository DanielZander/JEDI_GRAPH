#!/usr/bin/env python3
"""Build the static JEDI Lab graph data from its public publications page."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

SOURCE_URL = "https://jedilab.weebly.com/publications.html"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "publications.json"

TOPIC_RULES = {
    "Prosociality & cooperation": (
        "prosocial", "altruis", "donat", "donation", "helping", "generosity",
        "cooperat", "charit", "giving", "sharing", "warm glow",
    ),
    "Fairness & social preferences": (
        "fair", "inequal", "distribut", "envy", "equity", "social preference",
        "allocation", "reciprocity",
    ),
    "Risk & uncertainty": (
        "risk", "uncertaint", "gambl", "lottery", "ambiguit", "risky",
    ),
    "Intertemporal choice": (
        "time preference", "time discount", "discounting", "temporal", "delay",
        "patience", "future", "intertemporal",
    ),
    "Judgment & decision-making": (
        "decision", "choice", "judgment", "judgement", "intuition", "reflection",
        "cognitive", "bias", "heuristic", "framing", "reasoning", "deliberat",
    ),
    "Behavioral economics": (
        "economic", "incentive", "money", "monetary", "cost", "price",
        "consumer", "insurance", "financial", "accounting",
    ),
    "Health & medical decisions": (
        "health", "medical", "patient", "treatment", "healthcare", "clinical",
        "organ", "bioethic", "rationing", "reimbursement",
    ),
    "Social norms & morality": (
        "norm", "moral", "ethic", "politic", "trust", "honest", "corrupt",
        "misconduct", "misinformation", "conspiracy",
    ),
    "Emotion & wellbeing": (
        "affect", "emotion", "happiness", "well-being", "wellbeing", "welfare",
        "empathy", "fear", "disgust", "regret", "warm glow",
    ),
    "Research methods & integrity": (
        "method", "reproduc", "prereg", "registered report", "transparency",
        "replication", "research ethics", "questionable", "randomized",
        "publication bias",
    ),
    "Neuroscience & physiology": (
        "neuro", "brain", "fmri", "skin conductance", "eye tracking",
        "physiolog", "genetic",
    ),
}


class BibliographyParser(HTMLParser):
    """Extract publication text while retaining italic journal names."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._active = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div" and "paragraph" in (attributes.get("class") or "").split():
            self._active = True
        elif self._active and tag == "br":
            self._parts.append("\n")
        elif self._active and tag == "em":
            self._parts.append("\ue000")

    def handle_endtag(self, tag: str) -> None:
        if self._active and tag == "em":
            self._parts.append("\ue001")
        elif self._active and tag == "div":
            self.paragraphs.append("".join(self._parts))
            self._parts = []
            self._active = False

    def handle_data(self, data: str) -> None:
        if self._active:
            self._parts.append(data)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u200b", "").replace("\xa0", " ")).strip()


# A capitalised surname, allowing internal capitals (MacCutcheon), combining
# accents, and hyphenated or multi-word forms (Karlsson-Larsson, Van Bavel).
_SURNAME_PART = r"[A-ZÀ-ÖØ-Þ](?:[^\W\d_]|['’̀-ͯ])+"
SURNAME = rf"{_SURNAME_PART}(?:[- ]{_SURNAME_PART})*"


def parse_authors(value: str) -> list[str]:
    # Ellipses ("...", ". . .", "…") stand for omitted authors; an initial's own
    # full stop ("A.M. ...") is not part of one.
    value = re.sub(r"(?<![^\W\d_])\.\s*\.\s*\.|…", ",", value)
    value = re.sub(r",?\s+and\s+", ", ", value)
    value = re.sub(r"(?:,\s*)+,", ",", value).strip(" ,")
    split_pattern = (
        rf"\s*&\s*|,\s*(?={SURNAME}(?:,\s*[A-Z]|\s+[A-Z]))"
        # A missing comma between names: "Erlandsson, E. Västfjäll, D."
        rf"|(?<=,\s[A-Z]\.)\s+(?={SURNAME},)"
    )
    names = [clean_text(part.strip(" ,")) for part in re.split(split_pattern, value)]
    return [name for name in names if name and name != "..."]


def classify_topics(title: str, journal: str) -> list[str]:
    text = f"{title} {journal}".casefold()
    topics = [
        topic
        for topic, keywords in TOPIC_RULES.items()
        if any(keyword in text for keyword in keywords)
    ]
    return topics or ["Other"]


def parse_bibliography(html: str) -> list[dict[str, object]]:
    parser = BibliographyParser()
    parser.feed(html)
    if not parser.paragraphs:
        raise ValueError("The publications page did not contain a bibliography paragraph.")

    raw = parser.paragraphs[0]
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n+", raw)
        if clean_text(block.replace("\ue000", "").replace("\ue001", ""))
    ]
    year: int | None = None
    publications: list[dict[str, object]] = []

    for block in blocks:
        plain = clean_text(block.replace("\ue000", "").replace("\ue001", ""))
        year_match = re.fullmatch(r"20\d{2}", plain)
        if year_match:
            year = int(plain)
            continue
        if year is None:
            continue

        author_match = re.match(r"^(.*?)\s*\((20\d{2})\)[.,]?\s*(.*)$", plain)
        if not author_match:
            in_press = re.match(r"^(.*?)\s*\((?:in press|working paper)\)\.\s*(.*)$", plain, re.I)
            unparenthesized_year = re.match(r"^(.*?)\s+(20\d{2})\.\s*(.*)$", plain)
            if in_press:
                author_text, remainder = in_press.groups()
                cited_year = str(year)
            elif unparenthesized_year:
                author_text, cited_year, remainder = unparenthesized_year.groups()
            else:
                continue
        else:
            author_text, cited_year, remainder = author_match.groups()
        doi_match = re.search(r"https?://doi\.org/\S+", remainder, flags=re.IGNORECASE)
        doi = doi_match.group(0).rstrip(".,;") if doi_match else ""
        if doi:
            doi = re.sub(r"^https?://doi\.org/https?://doi\.org/", "https://doi.org/", doi, flags=re.I)
            remainder = remainder[: doi_match.start()].strip()

        journal_match = re.search(r"\ue000(.*?)\ue001", block)
        journal = clean_text(journal_match.group(1)) if journal_match else ""
        citation_remainder = clean_text(remainder)
        if journal and journal in citation_remainder:
            title = citation_remainder.split(journal, 1)[0].rstrip(" .")
        else:
            title = re.split(r"\.\s+(?=[A-Z])", citation_remainder, maxsplit=1)[0].rstrip(" .")
        if not title:
            title = citation_remainder or plain

        citation = clean_text(plain)
        if doi and doi not in citation:
            citation = f"{citation} {doi}"
        identifier = doi or hashlib.sha256(
            f"{cited_year}|{title}|{author_text}".encode("utf-8")
        ).hexdigest()[:16]
        publications.append({
            "id": identifier,
            "title": title,
            "year": int(cited_year),
            "authors": parse_authors(author_text),
            "journal": journal,
            "doi": doi,
            "citation": citation,
            "topics": classify_topics(title, journal),
        })

    if not publications:
        raise ValueError("No publication entries could be parsed from the JEDI bibliography.")
    unique: dict[str, dict[str, object]] = {}
    for publication in publications:
        doi = str(publication["doi"]).casefold()
        key = doi or str(publication["id"])
        existing = unique.get(key)
        completeness = (
            sum(len(str(author)) for author in publication["authors"]),
            int(publication["year"]),
        )
        existing_completeness = (
            sum(len(str(author)) for author in existing["authors"]),
            int(existing["year"]),
        ) if existing else None
        if existing is None or completeness > existing_completeness:
            unique[key] = publication
    return list(unique.values())


def merge_existing(
    publications: list[dict[str, object]],
    existing: object,
) -> tuple[list[dict[str, object]], int]:
    if not isinstance(existing, dict) or not isinstance(existing.get("publications"), list):
        return publications, 0

    source_keys: set[str] = set()
    for publication in publications:
        source_keys.add(f"id:{str(publication['id']).casefold()}")
        if publication["doi"]:
            source_keys.add(f"doi:{str(publication['doi']).casefold()}")
        source_keys.add(
            f"title-year:{publication['year']}:{str(publication['title']).casefold()}"
        )

    merged = list(publications)
    preserved = 0
    for record in existing["publications"]:
        if not isinstance(record, dict) or not record.get("title"):
            continue
        doi = str(record.get("doi", "")).casefold()
        identifier = str(record.get("id", "")).casefold()
        title_key = f"title-year:{record.get('year')}:{str(record['title']).casefold()}"
        keys = {f"id:{identifier}", title_key}
        if doi:
            keys.add(f"doi:{doi}")
        if keys.isdisjoint(source_keys):
            merged.append(record)
            source_keys.update(keys)
            preserved += 1
    return merged, preserved


def fetch_source() -> str:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "JEDI-Lab-Knowledge-Graph/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"JEDI publications page returned HTTP {response.status}.")
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not fetch {SOURCE_URL}: {error}") from error


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--input",
        type=Path,
        help="Parse a saved HTML copy instead of downloading the JEDI publications page.",
    )
    argument_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination JSON file (default: {DEFAULT_OUTPUT}).",
    )
    args = argument_parser.parse_args()

    try:
        html = args.input.read_text(encoding="utf-8") if args.input else fetch_source()
        publications = parse_bibliography(html)
        preserved = 0
        if args.output.exists():
            try:
                existing = json.loads(args.output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError(f"Could not read existing dataset {args.output}: {error}") from error
            publications, preserved = merge_existing(publications, existing)
        output = {
            "source": SOURCE_URL,
            "updated": date.today().isoformat(),
            "count": len(publications),
            "publications": publications,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    years = [publication["year"] for publication in publications]
    detail = f"; preserved {preserved} manually added records" if preserved else ""
    print(
        f"Wrote {len(publications)} unique publications ({min(years)}–{max(years)})"
        f"{detail} to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
