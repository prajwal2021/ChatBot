# KB Curation

Keeps each chatbot's knowledge base in step with the official TTU websites, with a reviewer approving every change.

```
Sources ─► Crawl ─► Pages + change detection ─► Entries (categorised, labelled)
        ─► Review (edit / comment / approve / reject) ─► Publish (numbered, read-only version)
        ─► Document (Word / Google Doc) + JSON feed for the chatbot
```

## Run

Needs PostgreSQL (database `kb_curation`), Python 3.11 and Node 20+.

```bash
createdb kb_curation
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt && cp .env.example .env
.venv/bin/uvicorn app.main:app --port 8010 --reload --reload-dir app     # API  http://localhost:8010
cd ../web && npm install && npm run dev -- -p 3010                       # UI   http://localhost:3010
```

Tables are created on first start, with two chatbots (TTU K-12, TTU Online), their source URLs and starter categories.

## How it works

| Step | Code | Notes |
|---|---|---|
| Find pages | `backend/app/crawler.py` | Two passes per source: follow every link from the home page, then pages listed only in `sitemap.xml`. Stays on the source's own site. PDFs, images and other files are counted, never read. Dead sitemap addresses and leftover copies (`old-index.php`, `test.php`, `/_dev/`) are dropped. |
| Verify every page | `verify.py` | Runs on every crawl; a page is re-verified only when its content changes. It must load, not be an error page, have real text, not be a list of links, not be a copy of another page, and (with `OPENAI_API_KEY`) be judged useful for the chatbot's audience. Failed pages never reach Review. A reviewer can overrule a verdict. |
| Choose pages | Pages screen, `main.py` | Reviewers can leave pages out, put them back, add a page by hand (also from another site), or exclude whole paths per source. New pages found by a crawl are added automatically and flagged. |
| Read content | `extract.py` | One entry per heading. Text is copied as written (bullets, steps, tables, links). Navigation, footers and "last updated" lines are ignored. |
| Detect changes | `pipeline.py`, `diffing.py` | A page is re-processed only when its text hash changes; only the sections that changed create review items. A page counts as removed after two "not found" crawls in a row; timeouts never count. |
| Categorise | `categorize.py` | One primary category plus up to two "also answers" categories and labels. An AI model files new entries when `OPENAI_API_KEY` is set; keyword rules are the fallback. Identical text on two pages is flagged as a duplicate. |
| Review | `review.py` | Approve, reject, edit, comment. A rejected change is not proposed again; a reviewer's own edit is not overwritten by the next crawl. |
| Publish | `publish.py` | Approved entries become an immutable version with a per-entry diff against the previous one. |
| Deliver | `docgen.py`, `gdocs.py` | Word, Markdown and JSON per version. With `GOOGLE_SERVICE_ACCOUNT_FILE` set, each publish is written into the linked Google Doc. |
| History | `activity` table, History screen | Every crawl, page change, review decision, edit, publish and settings change, with who and when. |

The chatbot should index the JSON feed (`GET /api/chatbots/{key}/export?format=json`): one entry per record with
category, labels and source URL. Wiring that into `vectors/` is the next phase.

There is no login yet: the reviewer name is typed in the sidebar and recorded with each action.
