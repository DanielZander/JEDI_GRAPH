# JEDI Lab research map

A dependency-free, static web app that turns the JEDI Lab bibliography into an interactive map of research themes, named contributors and publications. It is designed to run as a small standalone site and to be embedded in the existing Weebly site.

## Run locally

Requires Python 3.10 or later. From this folder, run:

```powershell
python -m http.server 8000
```

Then open `http://localhost:8000`. The graph loads `data/publications.json`; opening `index.html` directly as a `file://` URL will not load that data.

## Deploy on the JEDI Lab website

Host this folder on a static web host (for example, GitHub Pages) and add an HTML embed element to the Weebly page. Replace the URL with the deployed address:

```html
<iframe
  src="https://YOUR-STATIC-HOST.example/"
  title="JEDI Lab research map"
  style="width:100%;height:900px;border:0"
  loading="lazy"
  allowfullscreen>
</iframe>
```

The app does not require a server-side database, API key, JavaScript package manager or tracking service. Keep `index.html`, `data/publications.json`, `data/metrics.json`, `data/members.json`, and `data/JEDI_logo.png` together at the deployed URL.

## Refresh the bibliography

The data refresh tool reads the public JEDI Lab publications page, extracts the references and generates the JSON graph data:

```powershell
python tools\update_publications.py
```

On refresh, papers already on the public list are rebuilt from that page; manually added records that do not appear there are retained from the existing JSON. Manual topic corrections to listed papers should be made after a source refresh (or in the source bibliography), because refresh recalculates those suggested themes.

To parse an HTML copy of the source page instead of fetching it:

```powershell
python tools\update_publications.py --input path\to\publications.html
```

The page lists references, not structured author records. The tool preserves the cited author spellings (including initials), DOI, publication year, journal where marked up, and full citation text. Author ellipses are not expanded, and listed coauthors are not necessarily JEDI Lab members; historical lab affiliation is not identified by the source. Themes are assigned by documented title/journal keyword rules in `tools/update_publications.py`, so treat them as suggested browsing categories and correct them where needed.

## JEDI Lab people

`data/members.json` lists the lab's directors, members, alumni and affiliated researchers (from <https://jedilab.weebly.com/people.html>). The page highlights them wherever they appear:

- **Graph:** current directors and members are solid red nodes with bold labels; alumni and affiliated researchers are red rings; other coauthors are gray. Every lab person in the current selection gets a node. Other coauthors with fewer than three papers are named on hover only.
- **Side panel:** a theme lists its **JEDI Lab** people first, with their role, then the other coauthors. A lab person's page shows their role and every spelling the bibliography uses for them.
- **Publications:** lab people are marked and bold in the author list; click a name to open that person.
- **Search:** accepts first or last names, without accents, in any order (`gustav`, `vastfjall daniel`).

Cited names are matched to people by surname and first initial (for example `Tinghög, G.`, `Tinghög G` and `TInghög, G.` all become Gustav Tinghög), and each person's spellings are merged into one node. A name that matches two people is left unmatched. Add an `aliases` entry for spellings the rule cannot catch, such as an earlier surname or a typo in the source:

```json
{
  "name": "Hulda Karlsson-Larsson",
  "group": "member",
  "role": "Ph.D. student in psychology",
  "aliases": ["Karlsson, H."]
}
```

`group` is one of `director`, `member`, `alumni` or `affiliated`. When someone joins, leaves or graduates, edit this file and deploy it with the page. The page works without it.

The rule cannot tell apart two people who share a surname and first initial. If an unrelated coauthor with the same initial appears, they will be counted as the lab person; check a person's "Cited in the bibliography as" line when in doubt.

## Refresh citations and journal rankings

Publication metrics live in `data/metrics.json`, separate from the bibliography. Regenerate them after refreshing the bibliography:

```powershell
python tools\update_metrics.py
```

The tool looks up every DOI in [OpenAlex](https://openalex.org/) and records, per publication, the OpenAlex citation count and citations per calendar year, the journal's name and ISSNs, and the journal's level in the **ABDC Journal Quality List** and the **Norwegian Register** (Kanalregisteret). The rankings come from the journal lists OpenAlex loads from each maintainer's published file and matches by ISSN; the loaded edition is stored with every ranking and shown on the page. They are the *current* edition, applied to all publication years.

- No API key is needed for a DOI refresh (a handful of requests). Without a key, requests share a small free daily budget per IP address; set a free key from <https://openalex.org/settings/api> in `OPENALEX_API_KEY` if refreshes fail with HTTP 429.
- `--match-titles` also looks up publications without a DOI by title. A match is accepted only for an identical normalised title within one year of the cited year; preprint/article duplicates are resolved by journal name or else listed for review. This costs about $0.001 per lookup, which exceeds the keyless budget for the current bibliography, so use an API key.
- Publications that could not be matched have no entry in `works`: the page shows no citation data for them rather than zero. DOIs that OpenAlex does not know, and ambiguous title matches, are listed in the file's `review` array. Fix the DOI in the bibliography or add the paper manually.
- Citation counts are OpenAlex estimates. They will differ from Google Scholar, Scopus and Web of Science, and per-year counts cover roughly the last ten years.

### Licensed or historical rankings

JCR quartiles and AJG/ABS ratings are licensed products and are not fetched automatically. If the lab has the right to publish them, or wants the Norwegian level that applied in an earlier year, put them in `data/journal_rankings.csv` (copy `data/journal_rankings.example.csv`):

| Column | Meaning |
|---|---|
| `system` | Short id, e.g. `jcr`, `ajg`, `norway` |
| `value` | Level as displayed, e.g. `Q1`, `4*`, `Level 2` |
| `edition_year` | Year the edition applies from |
| `edition` | Optional label (defaults to the year) |
| `issn` | Journal ISSN (preferred match key) |
| `journal` | Exact journal name, used only for rows without an ISSN |
| `source` | Where the value came from |

For each paper and system, the tool uses the latest edition at or before the publication year (or the earliest edition if all are later). A CSV ranking replaces the OpenAlex value for the same system. Rows are matched to papers through the ISSNs found in OpenAlex, so only DOI-matched papers can be matched by ISSN.

### Metrics schema

```json
{
  "generated": "YYYY-MM-DD",
  "sources": { "openalex": { "retrieved": "YYYY-MM-DD" }, "abdc": { "edition": "YYYY-MM-DD" } },
  "summary": { "matched_by_doi": 0, "matched_by_title": 0, "ambiguous": 0, "unmatched": 0 },
  "works": {
    "<publication id>": {
      "match": { "method": "doi", "openalex": "https://openalex.org/W…" },
      "source": { "name": "Journal name", "issn_l": "0000-0000", "issn": ["0000-0000"] },
      "citations": { "provider": "OpenAlex", "total": 12, "by_year": { "2025": 7 }, "retrieved": "YYYY-MM-DD" },
      "rankings": [{ "system": "abdc", "value": "A*", "edition": "YYYY-MM-DD", "matched_by": "issn", "source": "OpenAlex source lists" }]
    }
  },
  "review": [{ "id": "…", "title": "…", "reason": "DOI not found in OpenAlex" }]
}
```

The page works without `metrics.json`; the metric filters and charts appear only when it is present. Deploy it alongside `publications.json`.

## Administrator: update the publication dataset

There is no publication editor in the webpage. The site administrator owns `data/publications.json` and should publish the updated file whenever the bibliography changes.

- To refresh from the lab's published bibliography, run `python tools\update_publications.py`, review the generated JSON, and deploy the updated file with the webpage.
- To add a paper not yet listed on the source page, add a record to the JSON `publications` array. Keep `count` equal to the number of records, use a unique `id` (prefer the DOI URL), and add the authors and one or more themes. Publish the changed JSON file.
- The graph loads the deployed JSON when the page is opened. Browser layout preferences are separate from publication data.

The app supports selecting themes, contributors and search results; filtering by year, journal ranking and citation count; viewing publication and citation trends and ranking distributions; dragging the graph background to pan; scrolling over the graph to zoom around the pointer; and using the `+`, `−` and **Fit** controls. The default layout spaces theme clusters around the graph and reduces author-label clutter. Drag nodes to arrange the graph in the current browser; Shift-drag a theme to move it with its associated contributor cluster. Contributor lists initially show the top eight names, with a **Show all** button for the rest; the contributor section itself can also be collapsed. Layout changes are saved only in that browser. **Reset view** restores the default node positions and zoom. The JSON schema is:

```json
{
  "source": "https://jedilab.weebly.com/publications.html",
  "updated": "YYYY-MM-DD",
  "count": 1,
  "publications": [
    {
      "id": "https://doi.org/10.xxxx/example",
      "title": "Publication title",
      "year": 2025,
      "authors": ["Surname, A.", "Surname, B."],
      "journal": "Journal name",
      "doi": "https://doi.org/10.xxxx/example",
      "citation": "Full citation as listed by the lab",
      "topics": ["Judgment & decision-making"]
    }
  ]
}
```

## Tests

```powershell
python -m unittest discover -s tools -v
```
