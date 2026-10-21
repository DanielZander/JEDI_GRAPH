import unittest

from update_publications import classify_topics, merge_existing, parse_authors, parse_bibliography


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
        self.assertIn("Prosociality & cooperation", publication["topics"])

    def test_author_parser_ignores_ellipsis(self):
        self.assertEqual(
            parse_authors("Simpson, B., Eriksson, K., ... & Tinghög, G."),
            ["Simpson, B.", "Eriksson, K.", "Tinghög, G."],
        )

    def test_unmatched_titles_remain_in_other(self):
        self.assertEqual(classify_topics("A title without a mapped keyword", ""), ["Other"])

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
