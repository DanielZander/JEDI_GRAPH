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

DEFAULT_OVERRIDES = ROOT / "data" / "topic_overrides.json"
MAX_TOPICS = 3

# Theme rules. Each pattern is a case-insensitive regular expression; most start
# with \b so that they match the start of a word ("organ" must not match
# "organization"). Title matches count double. Journal patterns are hints for
# clearly specialised venues and only fill in when the title gives fewer than
# two themes. A paper keeps its MAX_TOPICS highest-scoring themes. Swedish
# stems cover the lab's Swedish-language publications.
TOPIC_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "Prosociality & charitable giving": {
        "title": (
            r"prosocial", r"\baltruis", r"\bdonat", r"\bdonor", r"\bcharit", r"\bhelp(?:ing|ers?|s)?\b",
            r"\bgenero", r"\bcooperat", r"\bgiving\b", r"warm glow", r"\bvolunteer", r"\bsharing\b",
            r"\bphilanthrop", r"identifiable victim", r"\bvictims?\b", r"\bhumanitarian", r"\bhjälp",
        ),
        "journal": (r"nonprofit", r"philanthrop", r"voluntary"),
    },
    "Fairness & social preferences": {
        "title": (
            r"\bfair", r"\binequal", r"\binequit", r"redistribut", r"distributive", r"\benvy\b",
            r"\bequity", r"egalitarian", r"social preference", r"reciproc", r"\bselfish",
            r"ultimatum game", r"\brättvis", r"självisk",
        ),
        "journal": (),
    },
    "Risk & uncertainty": {
        "title": (r"\brisk", r"\buncertain", r"\bgambl", r"\blotter", r"\bprobabilit"),
        "journal": (r"\brisk",),
    },
    "Intertemporal choice": {
        "title": (
            r"intertemporal", r"time preference", r"\bdiscounting\b", r"discounting preferences",
            r"\bdelay(?:ed)? (?:gratification|discount)", r"\bpatience\b",
        ),
        "journal": (),
    },
    "Financial decision-making": {
        "title": (
            r"\bfinanc", r"\bdebt", r"\bsaving", r"\binvestments?\b", r"\binvestors?\b", r"\bpension", r"\bretirement saving",
            r"mental accounting", r"\bwealth", r"\bhousehold financ", r"\bcredit\b", r"\bloans?\b",
        ),
        "journal": (r"\bfinanc", r"family and econom"),
    },
    "Environmental & climate decisions": {
        "title": (
            r"\bclimat", r"\benvironmental", r"pro-environmental", r"\bsustainab", r"\bcarbon",
            r"\bemission", r"\bconservation\b", r"\bconserving\b", r"\bwildlife", r"biodiversit",
            r"\bthe earth\b", r"\bgreen\b", r"\becolog", r"\benergy\b",
        ),
        "journal": (r"\becolog", r"environment", r"sustainab", r"\bclimat"),
    },
    "Health & medical decisions": {
        "title": (
            r"\bhealth", r"\bmedic", r"\bpatient", r"\btreatment", r"\bclinical", r"\bphysician",
            r"\bsurg", r"\bvaccin", r"\bpandemic", r"covid", r"priority setting", r"\brationing",
            r"\borgan donation", r"\btransplant", r"\bfrailty", r"\bdiseases?\b", r"reimbursement",
            r"cost-effectiveness", r"\beq-5d", r"comorbidity", r"\bglucose", r"\bsmittminsk",
        ),
        "journal": (r"\bmedic", r"\bhealth", r"\bclinic", r"bioethic", r"\bbmj\b", r"geriatric", r"orthop"),
    },
    "Judgment & decision-making": {
        "title": (
            r"\bdecision", r"\bjudg(?:e)?ments?\b", r"\bheuristic", r"\bbias(?:es)?\b", r"\bintuiti",
            r"\bdeliberat", r"dual[- ]process", r"\breasoning\b", r"\bframing\b", r"\bframed\b",
            r"\brational", r"\bchoices?\b", r"scope (?:in)?sensitivity", r"\bjoint evaluation",
            r"separate evaluation", r"prominence effect", r"homo (?:ignorans|heuristicus|economicus)",
            r"information (?:avoidance|spotlighting|processing)", r"\bkahneman", r"psychic numbing",
            r"\bbeslut", r"opportunity cost",
        ),
        "journal": (r"decision",),
    },
    "Behavioral economics": {
        "title": (
            r"\beconomic", r"\bincentive", r"\bmarkets?\b", r"\bpric(?:e|es|ing)\b", r"\bconsumer",
            r"\bpurchas", r"\bpublic goods?\b", r"\beconomic games?\b", r"\bpayment", r"\bmonetary",
            r"\bmoney\b", r"\bhiring\b", r"\bemployee", r"\bcustomer", r"coordination",
            r"opportunity cost", r"minimum (?:levels|provision)",
        ),
        "journal": (r"econom",),
    },
    "Social norms & morality": {
        "title": (
            r"\bnorms?\b", r"\bmeta-norms?\b", r"\bnormativ", r"\bmoral", r"\bethic", r"\bhonest",
            r"\bcheat", r"\bcorrupt", r"\bsanction", r"\bpunish", r"\bviolation", r"\bvirtu",
            r"\brepugnan", r"\bprejudice", r"\btoleran", r"\bdiscriminat", r"\breprimand",
        ),
        "journal": (),
    },
    "Politics, ideology & beliefs": {
        "title": (
            r"\bpolitic", r"\bideolog", r"\bvot(?:e|es|ing|ers?)\b", r"\bballot", r"\bpartisan",
            r"\bpolariz", r"\bconservatis", r"\bconservatives?\b", r"\bliberals?\b", r"\bauthoritarian",
            r"\bextremis", r"left-right", r"\bconspira", r"\bmisinformation", r"\bmisperception",
            r"\bbullshit", r"post-truth", r"\brefugee", r"\bprotest", r"\bworldview", r"\breligio",
            r"\bchristian", r"trust in (?:the government|scientists|science)", r"science communication",
            r"perceptions of science", r"\bnational identity", r"\bnuclear weapons",
        ),
        "journal": (r"\bpolitic",),
    },
    "Nudges & public policy": {
        "title": (
            r"\bnudg", r"\bpolic(?:y|ies)\b", r"\bpaternalis", r"\bdefaults?\b", r"choice architecture",
            r"(?<!self-)\bregulatory\b", r"\bdirective\b", r"\binterventions?\b", r"\bgovernment",
            r"offentlig sektor", r"\bpublic sector",
        ),
        "journal": (r"public policy", r"consumer policy"),
    },
    "Emotion & wellbeing": {
        "title": (
            r"\baffect\b(?! (?:coordination|the|how|whether))", r"\baffective", r"\baffect-", r"\bemotion",
            r"\bmood", r"\bfeelings?\b", r"\bempath", r"\bsympath", r"\bcompassion", r"\bfear",
            r"\banger\b", r"\bdisgust", r"\bregret", r"\bguilt", r"\banxiety", r"\bworry", r"\bstress",
            r"\barousal", r"\barousing", r"\bhappiness", r"well-being", r"\bwellbeing", r"life satisfaction",
            r"\bdistress", r"\bwarm glow", r"\bkänslor", r"\bdeath anxiety",
        ),
        "journal": (r"\bemotion", r"affective science", r"\bmusic"),
    },
    "Numeracy & cognitive abilities": {
        "title": (
            r"\bnumera", r"\bnumerical", r"\bnumber (?:processing|abilit|network)", r"\bnumberosity",
            r"\barithmetic\b(?! of (?:emotion|compassion|outcome))", r"\bmathemat", r"\bmath\b",
            r"\bdyscalculia", r"\bmagnitude processing", r"cognitive abilit", r"executive function",
            r"working memory", r"\bphysics achievement", r"\bspatial processing", r"cognitive precursors",
            r"triple code", r"\bpercentage calculation", r"bat-and-ball",
        ),
        "journal": (),
    },
    "Perception & attention": {
        "title": (
            r"\bsounds?\b", r"\bauditory", r"\bmusic", r"visual search", r"\battention", r"\bperceptual",
            r"change deafness", r"\bvisual field",
        ),
        "journal": (r"\bauditory", r"\bperception", r"\bsound\b"),
    },
    "Research methods & integrity": {
        "title": (
            r"\breplicat", r"\breproduc", r"\bpre-?regist", r"registered report", r"registered replication",
            r"meta-analy", r"many teams", r"multi-lab", r"open science", r"\btransparency",
            r"questionable research", r"research ethic", r"scientific norms", r"\bresearchers[\'’]", r"\bmisconduct", r"measurement invariance",
            r"\bvalidation\b", r"\bpsychometric", r"inter-rater reliability", r"\bnoise\b", r"\brobustness",
            r"\bdatasets?\b", r"data collected", r"randomized trials", r"\bcomprehension in economic games",
            r"\bconfusion remains", r"machine learning",
        ),
        "journal": (r"\bmethods\b", r"meta-psychology"),
    },
    "Neuroscience & physiology": {
        "title": (
            r"\bneur", r"\bbrain", r"\bfmri\b", r"functional magnetic", r"\bconnectivity", r"\bconnectome",
            r"\beeg\b", r"\bcortical", r"\bcortex", r"\bcaudate", r"\bphysiolog", r"skin conductance",
            r"\bcortisol", r"\bghrelin", r"\bhormon", r"\boxytocin", r"\bopioid", r"\bgenes?\b", r"\bgenetic",
            r"\balcohol", r"\bacute pain", r"\bpain processing", r"affective touch",
        ),
        "journal": (),
    },
}
_COMPILED_RULES = {
    topic: {kind: [re.compile(pattern, re.I) for pattern in patterns] for kind, patterns in rules.items()}
    for topic, rules in TOPIC_RULES.items()
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
    scores: dict[str, int] = {}
    journal_only: list[str] = []
    for order, (topic, rules) in enumerate(_COMPILED_RULES.items()):
        title_hits = sum(1 for pattern in rules["title"] if pattern.search(title))
        if title_hits:
            scores[topic] = title_hits * 2 + any(pattern.search(journal) for pattern in rules["journal"])
        elif any(pattern.search(journal) for pattern in rules["journal"]):
            journal_only.append(topic)
    ranked = sorted(scores, key=lambda topic: -scores[topic])
    if len(ranked) < 2:
        ranked += journal_only[: 2 - len(ranked)]
    # Keep the rule order for a stable, readable listing.
    order = list(TOPIC_RULES)
    return sorted(ranked[:MAX_TOPICS], key=order.index) or ["Other"]


def apply_topic_overrides(publications: list[dict[str, object]], path: Path) -> int:
    """Replace the suggested themes of listed papers with reviewed ones.

    The overrides file maps a publication id (or DOI URL) to its theme list.
    """
    if not path.exists():
        return 0
    try:
        overrides = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Could not read {path}: {error}") from error
    overrides = {key.casefold(): value for key, value in overrides.items() if not key.startswith("_")}
    known = set(TOPIC_RULES) | {"Other"}
    applied = 0
    for publication in publications:
        topics = overrides.get(str(publication["id"]).casefold())
        if topics is None:
            continue
        unknown = [topic for topic in topics if topic not in known]
        if unknown or not topics:
            raise ValueError(f"{path}: unknown theme(s) {unknown or '(empty list)'} for {publication['id']}")
        publication["topics"] = list(topics)
        applied += 1
    return applied


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
    argument_parser.add_argument(
        "--overrides",
        type=Path,
        default=DEFAULT_OVERRIDES,
        help=f"Reviewed theme assignments by publication id (default: {DEFAULT_OVERRIDES}, used if present).",
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
        overridden = apply_topic_overrides(publications, args.overrides)
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
    detail += f"; applied {overridden} reviewed theme overrides" if overridden else ""
    print(
        f"Wrote {len(publications)} unique publications ({min(years)}–{max(years)})"
        f"{detail} to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
