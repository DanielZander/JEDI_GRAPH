import json
import tempfile
import unittest
from pathlib import Path

from update_publications import (
    apply_topic_overrides,
    classify_topics,
    merge_existing,
    parse_authors,
    parse_bibliography,
    unify_spellings,
)


class BibliographyParsingTests(unittest.TestCase):
    def test_parses_authors_and_citation_fields(self):
        html = """
        <div class="paragraph">
          2024<br /><br />
          Tinghög, G., Västfjäll, D., & Koppel, L. (2024). Helping and giving in choices.
          <em>Journal of Decisions</em>. https://doi.org/10.1000/example
        </div>
        """
        publication = parse_bibliography(html)[0]
        self.assertEqual(publication["year"], 2024)
        self.assertEqual(publication["title"], "Helping and giving in choices")
        self.assertEqual(publication["journal"], "Journal of Decisions")
        self.assertEqual(publication["doi"], "https://doi.org/10.1000/example")
        self.assertEqual(
            publication["authors"],
            ["Tinghög, G.", "Västfjäll, D.", "Koppel, L."],
        )
        self.assertIn("Prosociality & charitable giving", publication["topics"])

    def test_author_parser_ignores_ellipsis(self):
        self.assertEqual(
            parse_authors("Simpson, B., Eriksson, K., ... & Tinghög, G."),
            ["Simpson, B.", "Eriksson, K.", "Tinghög, G."],
        )

    def test_author_parser_splits_irregular_separators(self):
        cases = {
            "Doell, K. C., Vlasceanu M., … Koppel, L., … & Van Bavel, J. J.":
                ["Doell, K. C.", "Vlasceanu, M.", "Koppel, L.", "Van Bavel, J. J."],
            "Barrafrem, K., Tinghög, G., and Västfjäll, D.":
                ["Barrafrem, K.", "Tinghög, G.", "Västfjäll, D."],
            "Nilsson, A., Erlandsson, E. Västfjäll, D., & Tinghög, G.":
                ["Nilsson, A.", "Erlandsson, E.", "Västfjäll, D.", "Tinghög, G."],
            "Asutay, E., Karlsson-Larsson, H., & Sörqvist, P., MacCutcheon, D.":
                ["Asutay, E.", "Karlsson-Larsson, H.", "Sörqvist, P.", "MacCutcheon, D."],
            "Koppel, L., ... Lindkvist, A.M. ... & Zwaan, R.A.":
                ["Koppel, L.", "Lindkvist, A.M.", "Zwaan, R.A."],
            "Birt, A., . . . Zwienenberg, M.": ["Birt, A.", "Zwienenberg, M."],
            "Asutay. E. & Västfjäll. D.": ["Asutay, E.", "Västfjäll, D."],
            "Tinghög G, Persson E, Västfjäll D.": ["Tinghög, G", "Persson, E", "Västfjäll, D."],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_authors(text), expected)

    def test_splits_references_separated_by_a_zero_width_line(self):
        html = """
        <div class="paragraph">
          2017<br /><br />
          Koppel, L. (2017). First paper. <em>Journal A</em>. DOI: 10.1000/first<br />​<br />
          Kirchler, M. (2017). Second paper. <em>Journal B</em>. doi: 10.1000/second
        </div>
        """
        publications = parse_bibliography(html)
        self.assertEqual([p["title"] for p in publications], ["First paper", "Second paper"])
        self.assertEqual([p["doi"] for p in publications], ["https://doi.org/10.1000/first", "https://doi.org/10.1000/second"])
        self.assertEqual(publications[0]["citation"].count("10.1000/first"), 1)

    def test_recognises_doi_spellings(self):
        for cited in ["https://doi.org/10.1000/x", "doi.org/10.1000/x", "DOI: 10.1000/x.",
                      "doi: http://dx.doi.org/10.1000/x", "https://doi.org/https://doi.org/10.1000/x"]:
            with self.subTest(cited=cited):
                html = f'<div class="paragraph">2020<br /><br />Persson, E. (2020). Title. <em>J</em>. {cited}</div>'
                self.assertEqual(parse_bibliography(html)[0]["doi"], "https://doi.org/10.1000/x")

    def test_unifies_author_spellings(self):
        publications = [
            {"authors": ["Juslin, P.", "Jagers, S. C."]},
            {"authors": ["Juslin, P.N.", "Sverker C. Jagers", "TInghög, G."]},
            {"authors": ["Tinghög, G.", "Tinghög, G"]},
            # "Nilsson, A." could be either of two people, so it is left alone.
            {"authors": ["Nilsson, A.", "Nilsson, A. B.", "Nilsson, A. C."]},
        ]
        unify_spellings(publications)
        self.assertEqual(publications[0]["authors"], ["Juslin, P.N.", "Jagers, S. C."])
        self.assertEqual(publications[1]["authors"], ["Juslin, P.N.", "Jagers, S. C.", "Tinghög, G."])
        self.assertEqual(publications[2]["authors"], ["Tinghög, G."])
        self.assertEqual(publications[3]["authors"], ["Nilsson, A.", "Nilsson, A. B.", "Nilsson, A. C."])

    def test_unmatched_titles_remain_in_other(self):
        self.assertEqual(classify_topics("A title without a mapped keyword", ""), ["Other"])

    def test_keywords_match_word_starts_not_substrings(self):
        # "organ" in the journal name and "Investigating" must not imply health or finance.
        topics = classify_topics(
            "Investigating the role of cognitive cost in empathy choices",
            "Journal of Economic Behavior & Organization",
        )
        self.assertNotIn("Health & medical decisions", topics)
        self.assertNotIn("Financial decision-making", topics)
        self.assertIn("Judgment & decision-making", topics)

    def test_new_financial_and_environmental_themes(self):
        self.assertEqual(
            classify_topics("Mitigating climate change with financial investments", ""),
            ["Financial decision-making", "Environmental & climate decisions"],
        )

    def test_journal_hint_only_fills_in_when_title_is_sparse(self):
        self.assertIn(
            "Health & medical decisions",
            classify_topics("Prioritizing rare options", "Medical Decision Making"),
        )
        self.assertNotIn(
            "Health & medical decisions",
            classify_topics("Politically motivated reasoning about risk", "Medical Decision Making"),
        )

    def test_keeps_at_most_three_themes(self):
        title = "Affect, risk and charitable giving: neural and financial decisions under norms"
        self.assertEqual(len(classify_topics(title, "")), 3)

    def test_overrides_replace_suggested_topics_and_reject_unknown_themes(self):
        publications = [{"id": "https://doi.org/10.1000/A", "topics": ["Other"]}, {"id": "x", "topics": ["Other"]}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "overrides.json"
            path.write_text(json.dumps({"_comment": "", "https://doi.org/10.1000/a": ["Risk & uncertainty"]}), encoding="utf-8")
            self.assertEqual(apply_topic_overrides(publications, path), 1)
            self.assertEqual(publications[0]["topics"], ["Risk & uncertainty"])
            path.write_text(json.dumps({"x": ["Not a theme"]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                apply_topic_overrides(publications, path)

    def test_parses_years_without_parentheses(self):
        html = """
        <div class="paragraph">
          2020<br /><br />
          Slovic, P., Mertz, C.K., & Västfjäll, D., 2020. Virtuous violence.
          <em>Research Journal</em>. https://doi.org/10.1000/violence
        </div>
        """
        publication = parse_bibliography(html)[0]
        self.assertEqual(publication["year"], 2020)
        self.assertEqual(publication["title"], "Virtuous violence")

    def test_deduplicates_same_doi_and_keeps_fuller_authorship(self):
        html = """
        <div class="paragraph">
          2025<br /><br />
          Lauren Yehle, Patrik Michaelsen, & Sverker C. Jagers (2025). A study of choices.
          <em>Journal of Decisions</em>. https://doi.org/10.1000/shared
          <br /><br />
          2024<br /><br />
          Yehle, L., Michaelsen, P., & Jagers, S. C. (2024). A study of choices.
          <em>Journal of Decisions</em>. https://doi.org/10.1000/shared
        </div>
        """
        publications = parse_bibliography(html)
        self.assertEqual(len(publications), 1)
        self.assertEqual(publications[0]["year"], 2025)
        self.assertEqual(publications[0]["authors"][0], "Lauren Yehle")

    def test_refresh_preserves_manual_records_not_in_the_public_bibliography(self):
        current = [{
            "id": "doi:10.1000/existing",
            "doi": "https://doi.org/10.1000/existing",
            "title": "Existing source paper",
            "year": 2024,
        }]
        existing = {
            "publications": [
                {
                    "id": "manual-paper",
                    "title": "Manually added paper",
                    "year": 2025,
                    "authors": ["Researcher, A."],
                    "doi": "",
                },
                {
                    "id": "old-doi-id",
                    "title": "Duplicate source paper",
                    "year": 2024,
                    "doi": "https://doi.org/10.1000/existing",
                },
            ]
        }
        merged, preserved = merge_existing(current, existing)
        self.assertEqual(preserved, 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[-1]["title"], "Manually added paper")


if __name__ == "__main__":
    unittest.main()
