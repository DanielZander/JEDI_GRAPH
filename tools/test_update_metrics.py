import tempfile
import unittest
from pathlib import Path

from update_metrics import (
    build_record,
    choose_title_match,
    csv_rankings,
    normalize_doi,
    normalize_issn,
    read_ranking_csv,
)

EDITIONS = {
    "abdc-a-star": {"edition": "2026-09-22", "maintainer": "ABDC", "url": ""},
    "norway-2": {"edition": "2026-09-18", "maintainer": "HK-dir", "url": ""},
}


def work(title="A study of choices", year=2024, source="Journal of Decisions", issn=("0000-0019",), listed=()):
    return {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1000/example",
        "display_name": title,
        "publication_year": year,
        "cited_by_count": 12,
        "counts_by_year": [{"year": 2025, "cited_by_count": 7}, {"year": 2024, "cited_by_count": 5}],
        "primary_location": {"source": {
            "display_name": source, "issn_l": issn[0], "issn": list(issn), "listed_in": list(listed),
        }},
    }


class NormalizationTests(unittest.TestCase):
    def test_doi_is_bare_and_lower_case(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1093/JCR/ucag022."), "10.1093/jcr/ucag022")
        self.assertEqual(normalize_doi(""), "")

    def test_issn_is_hyphenated(self):
        self.assertEqual(normalize_issn("1537527x"), "1537-527X")
        self.assertEqual(normalize_issn("123"), "")


class TitleMatchTests(unittest.TestCase):
    publication = {"title": "A Study of Choices", "year": 2024, "journal": "Journal of Decisions, 12"}

    def test_accepts_single_exact_title_within_a_year(self):
        match, outcome = choose_title_match(self.publication, [work(year=2025), work(title="Another study")])
        self.assertEqual(outcome, "matched")
        self.assertIsNotNone(match)

    def test_rejects_title_from_a_distant_year(self):
        self.assertEqual(choose_title_match(self.publication, [work(year=2020)]), (None, "unmatched"))

    def test_journal_breaks_tie_between_preprint_and_article(self):
        article = work()
        match, outcome = choose_title_match(self.publication, [work(source="SSRN"), article])
        self.assertEqual(outcome, "matched")
        self.assertIs(match, article)

    def test_duplicate_titles_without_journal_tie_break_are_ambiguous(self):
        self.assertEqual(
            choose_title_match(self.publication, [work(source="SSRN"), work(source="OSF")]),
            (None, "ambiguous"),
        )


class RecordTests(unittest.TestCase):
    def test_record_keeps_citation_and_list_provenance(self):
        record = build_record(
            {"title": "A study of choices", "year": 2024, "journal": ""},
            work(listed=("abdc-a-star", "norway-2", "doaj")), "doi", "2026-10-22", EDITIONS, [],
        )
        self.assertEqual(record["citations"]["total"], 12)
        self.assertEqual(record["citations"]["by_year"], {"2024": 5, "2025": 7})
        self.assertEqual(record["citations"]["retrieved"], "2026-10-22")
        self.assertEqual(
            {(r["system"], r["value"], r["edition"]) for r in record["rankings"]},
            {("abdc", "A*", "2026-09-22"), ("norway", "Level 2", "2026-09-18")},
        )

    def test_unmatched_publication_without_supplied_rankings_has_no_record(self):
        self.assertIsNone(build_record({"title": "x", "year": 2024}, None, "", "2026-10-22", EDITIONS, []))

    def test_supplied_ranking_overrides_openalex_list_for_same_system(self):
        rows = [{"system": "abdc", "value": "A", "edition_year": 2022, "edition": "2022",
                 "issn": "0000-0019", "journal": "", "source": "abdc.csv"}]
        record = build_record(
            {"title": "x", "year": 2024, "journal": ""},
            work(listed=("abdc-a-star",)), "doi", "2026-10-22", EDITIONS, rows,
        )
        self.assertEqual(record["rankings"], [{
            "system": "abdc", "value": "A", "edition": "2022", "matched_by": "issn", "source": "abdc.csv",
        }])


class RankingCsvTests(unittest.TestCase):
    def test_uses_edition_in_force_at_publication_and_prefers_issn(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rankings.csv"
            path.write_text(
                "system,value,edition_year,issn,journal\n"
                "jcr,Q2,2018,00000019,\n"
                "jcr,Q1,2021,0000-0019,\n"
                "jcr,Q3,2019,,Journal of Decisions\n"
                "ajg,3,2024,,Journal of Decisions\n",
                encoding="utf-8",
            )
            rows = read_ranking_csv(path)
        publication = {"year": 2020, "journal": "Journal of Decisions."}
        rankings = {r["system"]: r for r in csv_rankings(publication, {"0000-0019"}, rows)}
        self.assertEqual(rankings["jcr"]["value"], "Q2")
        self.assertEqual(rankings["jcr"]["matched_by"], "issn")
        self.assertEqual(rankings["ajg"]["value"], "3")
        self.assertEqual(rankings["ajg"]["matched_by"], "journal title")

    def test_missing_columns_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rankings.csv"
            path.write_text("system,value\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_ranking_csv(path)


if __name__ == "__main__":
    unittest.main()
