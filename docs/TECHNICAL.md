# Price Lens – technical reference

This is the detailed reference for the command line, the AI-agent workflow, the result files
and the scrapers. For installing and using the app, see the main [README](../README.md).

> **Commands on a Mac.** Examples below use the Windows helper `price_lens.bat`.
> On a Mac, run the same commands as `.venv/bin/python -m price_lens.cli …` from the
> project folder (after `setup_mac.command`). `start_app.bat` is `start_app.command` on a Mac.
>
> The first sections describe the previous Streamlit app, which is kept as a fallback
> (`start_app.bat` / `start_app.command`). The main app is started with
> `start_new_app.bat` / `start_new_app.command`.


## Unified app

Run `start_app.bat` on Windows, or:

```bash
python -m streamlit run apps/unified_app.py
```

The unified app is the only UI; it covers Amazon, eBay, Zalando and MediaMarkt.
Tabs follow the workflow: **① Plan → ② Check & run → ③ Results → ④ Relevance review**,
plus **History** and **Import / export**.

- **Plan:** quick setup (product-type presets and country groups), a warning when a
  country has no local search term, and a warning with "Leave these out" for storefronts
  that failed last time (`output/storefront_status.json`, updated after every run/check).
- **Check & run:** what will be searched, an estimated run time, the latest storefront check.
- **Results:** pick a **product group** (one per search, so sneakers are never averaged with
  hoodies), filters (country, platform, audience, price, text, and relevance confidence /
  review status after a review), headline prices, a price-range chart per storefront (USD),
  a summary table and a one-click **price report** (Excel: Summary + Products + About; text
  such as `=...` in titles is stored as text, never as a formula). CSV/Excel exports always
  include product id, search id, scrape time and relevance confidence. Switch to AI-reviewed
  data once a review is applied; if a retry added listings after the review, the app shows
  "Everything collected" by default and the Review tab offers to review only the new ones.
- **Import / export:** "Describe your research" builds a ready-to-paste LLM prompt; the AI
  first asks clarifying questions (product scope, brands, audiences, local search terms).

**Look and custom screens.** The Results screen and the live-run panel are custom screens
(Streamlit components v2: plain HTML/CSS/JS in `apps/pi_ui/web`, no build step). Filters,
the product-group switch, the chart/table toggle, sorting and paging run in the browser, so
they react instantly; the Excel/CSV buttons send the rows on screen to Python, which builds
the file with `price_report` and hands it back as a download. The dark theme and the Geist
fonts are set in `.streamlit/config.toml` (start the app from the project folder, as
`start_app.bat` does, so Streamlit finds it). Without internet access the fonts fall back to
the system font.

**Connection problems.** If the internet drops during a run, the scraper notices (browser
network errors + the storefront is unreachable), pauses, checks every 30 s for up to 15 min
and then re-collects the interrupted storefront; Cancel still works while it waits. Such
failures are labelled "Network" and never remembered as a shop problem. Every finished
storefront is saved immediately (`checkpoints/`), so after a crash, sleep or shutdown,
opening the run recovers everything collected so far. On the Results tab, **Retry
storefronts** re-runs only the shops that returned nothing and adds them to the same run.

1. **Plan** – build searches in the *Search Builder* (one or more platforms per search, each
   with its own countries; audiences; keyword/price filters; per-language queries), or paste an LLM-generated
   `analyst-v2` plan (prompt: `agent/llmskill.md`) into the *Plan Hub*. `analyst-v1`
   plans are converted automatically.
   **Audiences:** Zalando runs the plain query in its men/women/kids shops. Amazon, eBay and
   MediaMarkt have no audience switch, so each selected audience becomes its own query in
   the storefront language ("men's sneakers", "Herren Sneaker", "baskets femme";
   `orchestrator/audiences.py`). Override any phrase in the *Language & audience query
   overrides* table or via `query.audience_queries`; switch off *One query per audience* to
   run the plain query there instead. Rows carry an `audience` column on every platform.
2. **Exclude words in every language** – keyword filters match listing titles, so
   "case" does nothing on German or Polish titles. *Suggest translations* adds local
   versions (hülle, etui, …) for the selected countries from an offline dictionary
   (`core/term_translations.py`); you can edit them before adding.
3. **Collection size** – choose *Products per storefront* (e.g. 100: the scraper keeps
   paging, up to 20 pages, and stops once a storefront has delivered that many; Zalando
   splits the target across audiences) or a fixed *Pages per query*.
4. **Test storefronts** – opens one result page per selected storefront and reports
   OK / Partial / Cookie wall / Redirect / Bot check / No products loaded. Use it before a
   large multi-country run. Results: `output/check_*/storefront_check.csv`.
5. **Run Scraper** – runs in a separate background process
   (`price_lens.orchestrator.jobs`). The live log and progress stay visible;
   you can refresh or close the tab and the app reconnects. *Cancel* stops after the
   current step and keeps finished searches; *Force stop* appears if the browser hangs.
6. **Relevance review** – on the *Relevance Review* tab, prepare batches, then either
   review automatically with Claude (set an `ANTHROPIC_API_KEY` environment variable
   before starting the app; optional `PI_REVIEW_MODEL`) or copy each batch prompt into
   any AI chat and paste the JSON answer back. *Apply review* writes
   `ai_review/final_products.csv/.xlsx` (accepted + uncertain rows) and
   `ai_classified_products.csv` (every row with the AI's reason).
7. **Run History** – lists every run with status, listing counts and review state;
   reopen a run in Results/Review, delete it, or clean up failed/empty runs in one go.

Each run folder (`output/analyst_*`) contains `final_products.csv/.xlsx`,
`detailed_products.csv`, raw data, executed queries, per-search reports, `job.json`
and `log.txt`. Original prices and currencies are kept; USD prices use the European Central
Bank's daily reference rates fetched at the start of the run and saved in `fx_rates.json`
(date and source are shown on the Results tab and in the Excel report). Offline, the last
cached ECB rates (`output/fx_cache.json`) are used, and as a last resort the static table in
`core/currency.py` (also used for currencies the ECB does not publish, e.g. AED, SAR).
Rates you set yourself on the *Exchange rates* page (`output/fx_manual.json`) win over
both: either kept for every new research, or used by the next research only. A finished
research can be recalculated with today's rates (*More → Update USD prices*).

### MediaMarkt international pagination update

Cookie handling now checks that the consent dialog has actually disappeared, including
open shadow-root dialogs, and recognises Austrian/German "Ablehnen" and "Alles ablehnen"
variants. An unrecognised blocking cookie dialog is reported explicitly rather than being
misreported as a missing pagination control. It does not dismiss verification challenges.

The supplied Austrian search snapshots confirm distinct products at `page=2`, without a
`rel=next` link. Austria's `/de/search.html` now has a verified page-parameter fallback that
preserves the search query and filters, after consent has been handled. Other countries
continue to use their actual controls/next links.

The grid wait now scrolls through the result list and collects successive snapshots until
the product IDs/prices settle and the explicit loaded-product counter is met (when present).
It no longer treats the first three lazy-loaded cards as an entire batch. Homepage
recommendations cannot satisfy the search-grid wait. A timed-out partial batch is retained
with `collection_complete=false` in the audit and reported as incomplete.

When an explicit loaded-products counter has been reached and the rows have settled, the
batch is complete even if a sticky overlay or shifting layout prevents reaching the computed
scroll position. Diagnostic filenames are short for Windows paths; unusually deep output
folders use the system temporary `pi-diagnostics` folder, with exact paths in the report.

Visible verification challenges stop collection with an explicit message. For failures in
the unified app/CLI, the report links to HTML and screenshot files under the MediaMarkt
`diagnostics` directory. A timeout alone does not establish that Cloudflare caused it.

Pagination now waits for footer controls, recognises localized load-more and next buttons,
and follows the site's next link if a client-side click stalls. It supports observed next
links using `page`, `p`, or `pageNumber`, retaining the query and filters. It never counts
unchanged product IDs as a successful batch. Missing controls are reported as incomplete
coverage (the catalogue may be exhausted), not silently marked fully successful.

Reports include detected control labels and next URLs to diagnose country-specific failures.
Automated tests simulate international controls and stalled clicks; they do not certify all
live country storefronts. Test a previously failing country with two or three pages, and use
its `scrape_report.json` if it still stops. Germany does not need another full collection.


A reusable Amazon, eBay, Zalando, and MediaMarkt collection system with two interfaces:

- Streamlit for analysts
- A validated JSON/CLI workflow for AI agents and automated research

All adapters return the same core product schema. ABOUT YOU can be added without
changing the agent-facing contract.

## 1. Install on Windows

The easiest setup is:

```bat
setup_windows.bat
```

For manual installation, open Command Prompt in this folder:

```bat
py -m venv .venv
.venv\Scripts\activate
py -m pip install --upgrade pip
py -m pip install -e ".[dev]"
```

Firefox must be installed. Selenium Manager normally locates or installs
Geckodriver automatically.

Check the local installation at any time with:

```bat
price_lens.bat doctor
```

## Local AI-agent research

Open the repository in an AI-enabled editor and ask the agent to read
`agent/SKILL.md`. The agent converts a natural-language request into the unified
plan format and operates the local CLI; no scraper API or cloud deployment is
required.

Validate the included example without opening Firefox:

```bat
price_lens.bat validate-research examples\unified_research_plan.json
```

Run all selected marketplaces from that one plan:

```bat
price_lens.bat run-research examples\unified_research_plan.json
```

The run creates platform-specific audit folders, combined raw and cleaned
datasets, a research report, and compact `ai_review` JSON batches. After the
agent writes all batch decision files, validate and merge them with:

```bat
price_lens.bat apply-ai-review output\research_<timestamp>\ai_review
```

Use `price_lens.bat review-status output\research_<timestamp>\ai_review`
to see which batches remain. The final review folder contains
`ai_classified_products.csv` (the complete audit trail), a compact
`final_products.csv`, a formatted `final_products.xlsx`, and the JSON review/coverage
reports. Both final datasets contain the same accepted and uncertain candidates.
They include `review_status` and `relevance_confidence_pct`, so analysts can choose
their own QC threshold without joining a separate manual-review file. The Excel
workbook provides a filterable table, frozen identifiers, numeric formats and visual
confidence/status cues. High-confidence exclusions remain available in the detailed
audit but do not enter the final candidate dataset.

Set `review.allowed_brands` only for an explicit brand restriction; leave it empty
for generic market research. `review.minimum_keep_confidence` controls whether a
decision is accepted or retained as uncertain.

All CSV artifacts use Excel-friendly UTF-8. `currency_code` contains the ISO
code (for example `EUR`) while `currency_symbol` contains the canonical display
symbol (for example `€`). The Windows launcher forces UTF-8 console I/O so
localized marketplace text cannot crash a run on a `cp1252` terminal.

## 2. Run the app

```bat
start_new_app.bat
```

This starts the new app (the "Ledger" design, light and dark) and opens it in your
browser at http://127.0.0.1:8765. Keep the black window open while you use it; closing it
stops the app (a collection that is already running keeps going and shows up again when
you restart). The app only listens on your own computer.

- **Researches** (home): every research with status, listings, median price and price
  spread; drafts you have not run yet; storefront health at a glance.
- **A research** has five steps: *Plan* → *Storefront check* (optional) → *Collect*
  (live progress, then what each storefront returned, with a retry for the ones that
  returned nothing) → *Review* (Claude API or any AI chat by copy and paste; change any
  decision by hand) → *Results* (plain-language finding, filters, chart with the overall
  median, summary, listings, Excel report and CSV of exactly what is shown).
- **New research** opens the plan builder: search words per language, audiences,
  words to leave out (with suggested translations), price range, where to search
  (platform by platform, with last-check warnings), collection size. Drafts save
  themselves. *Plan with an AI chat* and *Import plan* take an `analyst-v2` plan.
- **Exchange rates**: today's ECB rates next to the static table, and your own rates
  (with a note, kept for every research or for the next one only). Each research keeps the
  rates it started with; *More → Update USD prices* on a research recalculates it.
- **Settings**: defaults for new researches, Claude API status, clean-up of failed runs.

### Long collections: pause and resume

- **Pause** (on the Collect step) finishes the storefront in progress, then stops. Every
  finished storefront is in the results right away (you can review and compare them).
  **Resume collecting** later - after a restart too - collects only the storefronts not
  collected yet, with the same settings and exchange rates, and adds them to the same
  research. Pause and resume as often as needed; the research shows *Paused · 412 of
  1,960 storefront searches done* and the time left.
- **Stop** ends right away (the storefront in progress is dropped); the research can be
  resumed the same way.
- **Shutdown, sleep or crash**: each storefront is saved the moment it finishes. When you
  open the research again, what was collected is added (also for a resume that was cut
  off) and *Resume collecting* continues from there. A computer that was only asleep keeps
  collecting when it wakes up.
- **Internet drops**: the run waits (checking every 30 s, up to 15 min) and collects the
  interrupted storefront again when the connection is back. After 15 min it moves on;
  storefronts that could not be reached are listed under *Retry*. Retry is for storefronts
  that were tried and returned nothing; Resume is for storefronts not tried yet.

The previous Streamlit app still works as a fallback: `start_app.bat`. Both read and
write the same `output` folder, so runs are visible in either.

The former single-site apps (`amazon_app.py`, `ebay_app.py`, `zalando_app.py`,
`mediamarkt_app.py`) have been removed; everything they did is in the apps above.

The project folder can be moved, renamed or copied (for example to a new OneDrive folder):
reviews always use the files in their own run folder.

## 3. Validate an agent request

Edit `examples/amazon_search_plan.json`, then validate it without opening a
browser:

```bat
py -m price_lens.cli validate-amazon examples\amazon_search_plan.json
```

For eBay:

```bat
py -m price_lens.cli validate-ebay examples\ebay_search_plan.json
```

For Zalando:

```bat
py -m price_lens.cli validate-zalando examples\zalando_search_plan.json
```

For MediaMarkt Germany:

```bat
py -m price_lens.cli validate-mediamarkt examples\mediamarkt_search_plan.json
```

## Check every eBay domain

Use the dedicated health check before a large international collection:

```bat
py -m price_lens.cli check-ebay-marketplaces
```

It tests all 11 eBay domains configured in the app using one conservative query
and reports:

- whether the page loaded;
- whether listing cards were parsed;
- whether the site redirected to a different eBay domain;
- the expected and observed currencies; and
- the error returned by failed marketplaces.

The command creates:

```text
output\ebay_marketplace_check_<timestamp>\
├── marketplace_health.csv
└── marketplace_health.json
```

To watch the checks in Firefox, add `--visible`:

```bat
py -m price_lens.cli check-ebay-marketplaces --visible
```

To recheck only one or more failed domains:

```bat
py -m price_lens.cli check-ebay-marketplaces --marketplaces ebay.de
```

The same check is available in the eBay Streamlit app under **Domain Check**.

## Check every Zalando domain

The equivalent command checks all 28 configured Zalando domains. By default it
checks the men's route for backwards compatibility:

```bat
py -m price_lens.cli check-zalando-marketplaces
```

To check all three product audiences, use:

```bat
py -m price_lens.cli check-zalando-marketplaces --audience all
```

To avoid repeating audiences that already passed, select only the remaining
ones. For example, this checks women and kids across all domains (56 checks):

```bat
py -m price_lens.cli check-zalando-marketplaces --query shoes --audiences women kids --visible --retries 3
```

For a visible or targeted check:

```bat
py -m price_lens.cli check-zalando-marketplaces --visible
py -m price_lens.cli check-zalando-marketplaces --marketplaces zalando.de zalando.fr
```

The validation checks required searches, supported marketplaces, delays,
pagination limits, retries, postcodes, and cleaning configuration.

## 4. Run from JSON

```bat
py -m price_lens.cli scrape-amazon examples\amazon_search_plan.json
```

Or collect from eBay:

```bat
py -m price_lens.cli scrape-ebay examples\ebay_search_plan.json
```

Or collect from Zalando:

```bat
py -m price_lens.cli scrape-zalando examples\zalando_search_plan.json
```

Or collect from MediaMarkt:

```bat
py -m price_lens.cli scrape-mediamarkt examples\mediamarkt_search_plan.json
```

MediaMarkt parsing prefers rendered product cards identified by stable data-test attributes,
using structured JSON-LD only as matching metadata or a fallback without cards. The collector
rejects optional cookies using localized consent buttons; it does not automatically accept
tracking if a reject control cannot be found. Optional detail
enrichment adds explicit brand, SKU, condition, availability, colour, shipping price, and the
product-page price.

### MediaMarkt international collection and pagination

Configured domains: DE, AT, CH, ES, NL, BE, PL, HU, PT, TR and Italy's mediaworld.it.
Portugal is registered but deliberately unavailable: mediamarkt.pt redirected to darty.pt
when checked on 2026-09-25. Darty is not collected or labelled as MediaMarkt.
The other international configurations require a local browser health check; configuration
and offline tests do not certify live collection in every country.

The scraper submits the storefront search form, retaining category redirects. A page now means
one result batch: it clicks the actual load-more button, or follows a same-host next-page link.
It waits for unseen product IDs and records new_products and unique_products_so_far per batch.
Repeated results are a pagination failure, not a successful page. Missing next controls stop
collection with a no_next_control event, not a promise that the entire catalogue was exhausted.
Three batches can yield 36 products when the site's batch size is 12 and enough matches exist.

Use this visible-browser check for Germany first (no other domains will be collected):

```bat
price_lens.bat check-mediamarkt-marketplaces examples\mediamarkt_international_research_plan.json --marketplaces mediamarkt.de
```

Select further countries with --marketplaces; omit it to check the full plan.
Each run writes marketplace_health.csv plus detailed per-page events in the scrape report.
The existing Streamlit country selector now includes all configured domains.

### Agent-generated local-language queries (all marketplaces)

Run price_lens.bat marketplace-locales for language-planning defaults.
The local editor agent translates before scraping; Python makes no translation API calls.
Use require_localized_queries=true on new agent research plans, and supply localized_queries
per search, keyed by every applicable domain:

```json
{
  "search_term": "wireless headphones",
  "product_type": "Headphones",
  "localized_queries": {
    "amazon.de": {"language": "de", "search_term": "kabellose Kopfhörer"},
    "ebay.fr": {"language": "fr", "search_term": "casque sans fil"},
    "mediamarkt.es": {"language": "es", "search_term": "auriculares inalámbricos"}
  }
}
```

Keep brands/model numbers unchanged. Translate include/exclude keywords too, or omit them;
untranslated base rules are not inherited for localized searches. Original terms and language
remain in the full audit as source_search_term and query_language. Final compact CSV/Excel
keep search_term as the actual executed query. Legacy plans still run verbatim.
Localization is applied by the unified run-research workflow, not by standalone Streamlit text
inputs or scrape-* commands. Those accept the query you type, without an AI translator.
For multilingual markets choose one language per storefront/run and state it in the plan.
MediaMarkt supports French in Belgium/Switzerland and Italian in Switzerland via locale paths.
Other adapters translate query text but do not automatically change the site's language setting;
verify the storefront language and report mismatches rather than inventing locale routes.

Set `enrich_details` to `false` for the fast search-card mode. Set it to `true`
and use `max_detail_products` to cap the number of product pages opened. Detail
enrichment adds the product-page price, color, availability, and canonical ID.

Every Zalando search must specify one or more audiences. The scraper expands
them into Zalando's audience-specific routes:

```json
"audiences": ["men", "women", "kids"]
```

Only the three shopping audiences are used. Extra shop-selector actions, such
as Italy's `Vendi` (Sell) link, are intentionally ignored.

Before searching a domain, the scraper reads Zalando's shop selector and discovers
the localized audience routes. For example, an English storefront may use
`/men/`, while Austria may use `/herren/`. The detected storefront host and route
are preserved, and the audience is recorded in every output row. The health report
includes one row per marketplace and audience, plus `requested_paths` for
diagnosing locale-specific routing.

Some storefronts use a separate catalog route for search. The adapter applies
the domain's catalog convention after discovery, such as `/katalog-muskarci/`
for Croatia, `/kataloog-mehed/` for Estonia, and `/catalogo-homem/` for Portugal.

The configured output directory receives a timestamped folder:

```text
output/
└── amazon_YYYYMMDD_HHMMSS/, ebay_YYYYMMDD_HHMMSS/, or zalando_YYYYMMDD_HHMMSS/
    ├── raw_products.csv
    ├── cleaned_products.csv
    ├── request.json
    └── scrape_report.json
```

The report records page successes and failures, blocked/time-out pages, raw and
unique listing counts, missing prices, duplicates, and cleaning decisions.

## Result fields

New agent-ready fields:

- `platform`
- `marketplace`
- `product_id` (Amazon ASIN or eBay item ID)
- `sponsored`
- `review_count`
- `product_url`
- `scraped_at`

eBay also populates `seller`, `condition`, `shipping_price_text`,
`shipping_price_value`, and `buying_format` where available.

Zalando populates `brand`, `image_url`, and the current price from search cards.
With enrichment enabled it also populates `color`, `availability`, and
`detail_enriched` from the product page's Schema.org `ProductGroup` data.

Legacy fields such as `link`, `price`, and `currency` are retained so the
existing Streamlit app remains compatible.

## Project structure

```text
price_lens/
├── agent/
│   ├── SKILL.md
│   └── research_plan.schema.json
├── start_new_app.bat         # the web app (python -m price_lens.webapp)
├── apps/                     # the previous Streamlit app (start_app.bat)
│   ├── unified_app.py        # entry point: page setup + tabs
│   └── pi_ui/                # one module per screen
│       ├── common.py  sidebar.py  plan_tab.py  run_tab.py  monitor.py
│       ├── results_tab.py  review_tab.py  history_tab.py  io_tab.py
│       ├── components.py     # custom screens: registration + the data they get
│       └── web/              # their HTML/CSS/JS (Results, live run, copy button)
├── .streamlit/config.toml    # dark theme and fonts
├── examples/
│   ├── amazon_search_plan.json
│   ├── unified_research_plan.json
│   ├── ebay_search_plan.json
│   ├── ebay_all_domains_search_plan.json
│   ├── zalando_search_plan.json
│   └── zalando_all_domains_search_plan.json
├── src/price_lens/
│   ├── cli.py
│   ├── webapp/               # web app: server.py (stdlib HTTP), api.py, static/ (HTML/CSS/JS)
│   ├── agent/
│   │   └── review.py
│   ├── orchestrator/
│   │   ├── schemas.py
│   │   ├── validation.py
│   │   ├── registry.py
│   │   └── runner.py
│   ├── core/
│   │   ├── schemas.py
│   │   ├── validation.py
│   │   ├── cleaning.py
│   │   ├── export.py
│   │   └── charts.py
│   └── marketplaces/
│       ├── amazon/
│           ├── constants.py
│           ├── parser.py
│           ├── locations.py
│           └── scraper.py
│       ├── ebay/
│           ├── constants.py
│           ├── parser.py
│           └── scraper.py
│       └── zalando/
│           ├── constants.py
│           ├── parser.py
│           ├── scraper.py
│           └── health.py
├── tests/
├── price_lens.bat
├── setup_windows.bat
├── pyproject.toml
└── README.md
```

## Tests

```bat
py -m pytest
```

Parser tests use saved HTML fixtures and therefore do not open Firefox or make
requests to Amazon, eBay, or Zalando.

## Production note

The eBay adapter currently reads public search-result pages so it can work
without developer credentials. Search markup and automated-traffic controls can
change. Keep the fixture tests, use conservative delays, and record failures in
the scrape report. A future production deployment can add eBay's official API as
an alternative acquisition backend without changing the output schema.

## Design boundary

Marketplace adapters collect deterministic records. Shared code owns schemas,
validation, cleaning, and exports. The AI skill calls the CLI and exchanges
small validated JSON files; it does not contain Selenium implementation details.
