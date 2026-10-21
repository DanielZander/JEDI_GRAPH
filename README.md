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

The app does not require a server-side database, API key, JavaScript package manager or tracking service. Keep `index.html`, `data/publications.json`, and `data/JEDI_logo.png` together at the deployed URL.

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

## Administrator: update the publication dataset

There is no publication editor in the webpage. The site administrator owns `data/publications.json` and should publish the updated file whenever the bibliography changes.

- To refresh from the lab's published bibliography, run `python tools\update_publications.py`, review the generated JSON, and deploy the updated file with the webpage.
- To add a paper not yet listed on the source page, add a record to the JSON `publications` array. Keep `count` equal to the number of records, use a unique `id` (prefer the DOI URL), and add the authors and one or more themes. Publish the changed JSON file.
- The graph loads the deployed JSON when the page is opened. Browser layout preferences are separate from publication data.

The app supports selecting themes, contributors and search results; filtering by year; scrolling over the graph to zoom around the pointer; and using the `+`, `−` and **Fit** controls. The default layout spaces theme clusters around the graph and reduces author-label clutter. Drag nodes to arrange the graph in the current browser; Shift-drag a theme to move it with its associated contributor cluster. Contributor lists initially show the top eight names, with a **Show all** button for the rest; the contributor section itself can also be collapsed. Layout changes are saved only in that browser. **Reset view** restores the default node positions and zoom. The JSON schema is:

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
