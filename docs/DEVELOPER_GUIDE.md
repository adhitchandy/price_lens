# Price Lens – developer guide

For whoever takes over Price Lens and wants to change or improve it. It explains how the
program is built, where things are, how to change them safely and how to find out what went
wrong.

| You want to… | Read |
|---|---|
| use the app | [README](../README.md) |
| change or debug the program | **this guide** |
| use the command line / plan format / AI-agent workflow | [TECHNICAL.md](TECHNICAL.md) |
| push to GitHub and publish a release | [MAINTAINING.md](MAINTAINING.md) |

Contents:

1. [Set up a development copy](#1-set-up-a-development-copy)
2. [How the program works](#2-how-the-program-works)
3. [Folder structure and important files](#3-folder-structure-and-important-files)
4. [What a research folder contains](#4-what-a-research-folder-contains)
5. [Debugging](#5-debugging)
6. [Common changes, step by step](#6-common-changes-step-by-step)
7. [Tests](#7-tests)
8. [Rules that keep the program working](#8-rules-that-keep-the-program-working)
9. [Everyday git workflow and releases](#9-everyday-git-workflow-and-releases)
10. [Ideas and known small issues](#10-ideas-and-known-small-issues)

---

## 1. Set up a development copy

You need **Python 3.10+** (3.12 or 3.13 recommended), **Firefox**, **Git** and an editor,
preferably **VS Code** (<https://code.visualstudio.com>) with the *Python* extension.

1. Ask for access to the GitHub repository <https://github.com/adhitchandy/price_lens> (or
   its successor in the company organisation).
2. Download it into a **local** folder, not OneDrive and not the network drive:

   ```bat
   cd %USERPROFILE%\Documents
   git clone https://github.com/adhitchandy/price_lens.git
   cd price_lens
   ```

3. Double-click `setup_windows.bat`. It creates `.venv` and installs the program in
   *editable* mode: changes to files in `src/` take effect without reinstalling.
4. Install the developer tools (pytest, ruff) once:

   ```bat
   .venv\Scripts\python -m pip install -e ".[dev]"
   ```

5. Check that everything works:

   ```bat
   .venv\Scripts\python -m pytest
   ```

   All tests must pass (about 190; they take under a minute and never visit real shops).
6. In VS Code: *File → Open Folder* → the project folder. When asked for an interpreter,
   pick `.venv` (or *Ctrl+Shift+P → Python: Select Interpreter*).

**Use a separate data folder while developing.** The app keeps everything in `output/`. To
experiment without touching real researches, point it at another folder first:

```bat
set PI_OUTPUT_DIR=%USERPROFILE%\Documents\price_lens_dev_output
.venv\Scripts\python -m price_lens.webapp --verbose
```

(On a Mac: `export PI_OUTPUT_DIR=~/price_lens_dev_output` and `.venv/bin/python -m price_lens.webapp --verbose`.)

Useful environment variables:

| Variable | Effect |
|---|---|
| `PI_OUTPUT_DIR` | Data folder of the web app (default: `output` in the project folder). |
| `PI_FX_OFFLINE=1` | Do not download ECB exchange rates (uses the cache / static table). |
| `ANTHROPIC_API_KEY` | Enables *Review with Claude*. |
| `PI_REVIEW_MODEL` | Claude model used for the review. |

Web-app options: `python -m price_lens.webapp --port 8766 --no-browser --verbose`.
`--verbose` prints every request, which is handy for debugging.

---

## 2. How the program works

```text
 Browser (static/index.html + js/)                    you click "Start collecting"
        │  fetch('/api/…')  JSON
        ▼
 webapp/server.py   local web server, 127.0.0.1 only, maps URLs → functions
        ▼
 webapp/api.py      one Python function per screen action (reads/writes output/)
        │
        │  jobs.start_job() creates output/analyst_<time>/ and starts a
        │  SEPARATE PROCESS:  python -m price_lens.orchestrator.jobs <run folder>
        ▼
 orchestrator/jobs.py        run_worker(): status in job.json, log.txt, heartbeat,
        │                    watches cancel.flag / pause.flag
        ▼
 orchestrator/analyst.py     run_analyst_plan(): plan → one search at a time,
        │                    exchange rates, price range, writes the result files
        ▼
 orchestrator/runner.py      run_research(): one search on several platforms
        ▼
 orchestrator/localization.py  collect_localized(): ONE STOREFRONT AT A TIME,
        │                    checkpoint after each, internet-drop handling, pause check
        ▼
 orchestrator/registry.py    platform name → scraper
        ▼
 marketplaces/<platform>/scraper.py   Selenium drives Firefox, pages through results
 marketplaces/<platform>/parser.py    BeautifulSoup turns page HTML into rows
        ▼
 core/  cleaning, fx (USD conversion), export (CSV/Excel), schemas
        ▼
 output/analyst_<time>/final_products.csv …   ← the screens read these again
        ▲
 orchestrator/screens.py, price_report.py, retry.py, history.py  (data for the screens)
```

Key ideas:

- **The collection runs in its own process.** The web server only starts it and then reads
  its files. You can close the browser, or even the server, and the collection continues.
  The page asks `/api/runs/<name>/live` every few seconds, which reads `job.json` and
  `log.txt`.
- **Everything lives in files.** There is no database. Every research is a folder in
  `output/`, and the files in it are the full truth (see section 4). To understand a
  problem, look at the folder.
- **Communication with the worker process is by files.** `cancel.flag` means stop now,
  `pause.flag` means stop after the current storefront. `job.json` holds the status and a
  heartbeat every 5 s. If the heartbeat is old *and* the process no longer exists, the
  research is shown as crashed and recovered from its checkpoints.
- **One storefront at a time.** For example, *amazon.de* for search 1. Each finished
  storefront is saved at once to `checkpoints/`. Pause, resume, retry and crash recovery
  are all built on these checkpoints (`orchestrator/retry.py` explains the rules at the top).
- **Plans.** A research is described by a JSON *plan* in the `analyst-v2` format: searches,
  each with a query, translations, filters and targets (platform + countries). The plan
  builder in the app writes one; `analyst.compile_analyst_plan()` turns it into the
  per-platform plans the scrapers understand.
- **Two front ends, one engine.** The main app is `webapp/`. The previous Streamlit app in
  `apps/` still works and uses the same `orchestrator/` code and the same `output/` folder.
  Changes to `orchestrator/` or `core/` affect both.

---

## 3. Folder structure and important files

```text
price_lens/
├── README.md, CHANGELOG.md          user guide, what changed per version
├── docs/                            TECHNICAL.md, MAINTAINING.md, this guide, images/
├── pyproject.toml                   name, VERSION, dependencies, pytest/ruff settings
├── setup_windows.bat / setup_mac.command        create .venv, install, run the check
├── start_new_app.bat / .command     start the web app  (python -m price_lens.webapp)
├── start_app.bat / .command         previous Streamlit app (fallback)
├── price_lens.bat                   command line on Windows (python -m price_lens.cli …)
├── src/price_lens/                  ← THE PROGRAM
│   ├── __init__.py                  __version__ (keep equal to pyproject.toml)
│   ├── cli.py                       command-line commands (doctor, run-research, checks…)
│   ├── webapp/
│   │   ├── __main__.py              start-up, port, opens the browser
│   │   ├── server.py                URL → function table (ROUTES), security checks
│   │   ├── api.py                   everything the screens can do (biggest file)
│   │   └── static/
│   │       ├── index.html           page frame and sidebar
│   │       ├── app.css              all styling (light/dark via CSS variables)
│   │       └── js/
│   │           ├── app.js           routing (#/…) and theme switch
│   │           ├── api.js           fetch wrapper (adds the X-PI-App header)
│   │           ├── dom.js           helpers: h() builds elements, fmt, dialog, toast
│   │           └── views/           one file per screen (see table below)
│   ├── orchestrator/                running researches (see table below)
│   ├── marketplaces/
│   │   ├── amazon/ ebay/ zalando/ mediamarkt/
│   │   │   ├── constants.py         storefronts (domain → country), URLs, currencies
│   │   │   ├── scraper.py           Selenium: open pages, cookies, paging, retries
│   │   │   ├── parser.py            HTML → rows (CSS selectors live here)
│   │   │   └── health.py            (eBay, Zalando) per-domain check commands
│   ├── core/
│   │   ├── schemas.py, results.py   data classes: search plans, ScrapeReport, ScrapeOutcome
│   │   ├── cleaning.py              remove sponsored/duplicates/filters
│   │   ├── currency.py              currency symbols and the static rate table
│   │   ├── fx.py                    ECB rates, your own rates, USD conversion
│   │   ├── export.py                run folders, CSV/Excel/JSON writing
│   │   ├── network.py               "is the internet gone?" and waiting for it
│   │   ├── localization.py          storefront languages
│   │   ├── term_translations.py     offline dictionary for "words to leave out"
│   │   └── doctor.py                the setup check (Python, Firefox, output folder…)
│   └── agent/
│       ├── assist.py                AI review prompts, parsing answers, calling Claude
│       └── review.py                review batches, decisions, overrides, applying them
├── apps/                            previous Streamlit app (unified_app.py + pi_ui/)
├── agent/                           instructions/schemas for AI agents doing research runs
├── examples/                        example plans
├── tests/                           automated tests + fixtures/ (saved shop pages)
└── output/                          all data (NOT in git)
```

### The `orchestrator/` modules

| File | What it does |
|---|---|
| `jobs.py` | Starts the worker process, `job.json`, heartbeat, pause/cancel/force stop, crash detection. |
| `analyst.py` | Plan format (`CATALOG` of all storefronts, `compile_analyst_plan`), `run_analyst_plan`, writing result files, `recover_run`. |
| `runner.py` | Runs one search on its platforms and combines the results. |
| `localization.py` | Storefront loop: checkpoints, failure markers, reconnect after internet drops, `RunPaused`. |
| `registry.py` | Platform name → scraper function. |
| `retry.py` | Which storefronts are done, remaining (Resume) or failed (Retry); merging a retry into the research. |
| `screens.py` | Data for screens: rows, live status, exports. Shared by both apps. |
| `price_report.py` | Price summary, headline finding, Excel report. |
| `history.py` | List, recover and delete researches (Windows-safe deleting). |
| `planning.py` | Country groups, product presets, missing translations, time estimate. |
| `audiences.py` | "men's sneakers" / "Herren Sneaker" phrases per language. |
| `health.py`, `storefront_status.py` | Storefront check table; remembering which shops failed last time. |
| `validation.py`, `schemas.py` | Validating plans (JSON → data classes). |

### The screens (`webapp/static/js/views/`)

| File | Screen | URL |
|---|---|---|
| `researches.js` | Home: all researches and drafts | `#/` |
| `plan.js` | Plan builder (new research / draft) | `#/draft/<id>` |
| `research.js` | A research with its step tabs | `#/r/<name>/<step>` |
| `collect.js` | Collect step: live progress, pause/resume, retry | (inside research) |
| `review.js` | Review step | (inside research) |
| `results.js` | Results step: filters, chart, tables, exports | (inside research) |
| `check.js` | Storefront check | `#/check/<name>` |
| `storefronts.js` | Storefront health | `#/storefronts` |
| `rates.js` | Exchange rates | `#/fx` |
| `settings.js` | Settings | `#/settings` |
| `shared.js` | Pieces used by several screens | |

There is **no build step**: plain JavaScript modules, no npm, no framework. Edit a file, then
reload the page (the server sends no-cache headers). Elements are built with
`h('tag', {props}, ...children)` from `dom.js`. Each `render()` may return a clean-up
function, which `app.js` calls when you leave the screen (used to stop polling timers).

---

## 4. What a research folder contains

`output/analyst_YYYYMMDD_HHMMSS/`:

| File | Meaning |
|---|---|
| `analyst_plan.json` | The plan as started. |
| `job.json` | Status (`queued/running/pausing/paused/cancelled/completed/partial/failed`), pid, heartbeat, progress, summary, `merge_into` for retries. |
| `log.txt` | Full live log. **Start here.** |
| `worker_output.txt` | Everything the worker process printed, including Python crashes before logging started. |
| `executed_queries.csv` | Every storefront × query that the plan expands to. |
| `fx_rates.json` | Exchange rates used for this research. |
| `raw_products.csv`, `detailed_products.csv` | Everything collected, with all columns. |
| `final_products.csv/.xlsx` | Cleaned listings: what Results shows. |
| `collection_report.json` | Per search: status and the platform reports (pages, failures, events). |
| `search_001/…/<platform>/scrape_report.json` | Detailed per-platform report: every page, failure, blocked page. |
| `search_001/…/<platform>/checkpoints/<domain>.csv` | One file per finished storefront; `<domain>.failed.txt` when it failed. |
| `search_001/…/mediamarkt/diagnostics/` | MediaMarkt only: HTML + screenshot of pages that failed. |
| `retries.json` | Retry/resume runs merged into this research. |
| `ai_review/` | Review batches, answers, `decisions`, overrides and the reviewed result. |
| `cancel.flag`, `pause.flag` | Present only while a stop/pause is being requested. |

Retries and resumes are separate folders (`output/retry_…`) that get merged into the parent
research when they finish. Other files in `output/`: `drafts/`, `app_settings.json`,
`fx_manual.json` (your own rates), `fx_cache.json` (last ECB rates), `storefront_status.json`
(health memory), `check_…/` (storefront checks).

---

## 5. Debugging

### Where to look first

| Symptom | Look at |
|---|---|
| A research failed or stopped | `log.txt`, then the end of `worker_output.txt` (Python traceback), then `job.json` → `error`. |
| A shop returned nothing | `scrape_report.json` of that platform (`failures`, `events`), the `.failed.txt` marker, MediaMarkt `diagnostics/`. Run it with the browser visible (below). |
| A screen shows an error or is empty | Browser developer tools (**F12**): *Console* for JavaScript errors, *Network* for the failing `/api/…` call and its response. The black server window shows Python errors; start with `--verbose` to see every request. |
| Wrong numbers on Results | Open `final_products.csv` and `fx_rates.json`; `price_report.py` computes the summary. |
| The app will not start | Run `price_lens.bat doctor`. "Port in use" means another copy is running (`--port 8766`). |

### Watch the browser

In the plan builder, untick **Hide the browser window** (next to the pauses and retries), or set
`"headless": false` in the plan's `execution` section. Firefox then opens visibly and you
can see cookie banners, bot checks and page changes yourself. For single platforms there
are check commands with `--visible`, e.g.:

```bat
price_lens.bat check-ebay-marketplaces --marketplaces ebay.de --visible
price_lens.bat check-zalando-marketplaces --marketplaces zalando.de --visible
```

### Run things step by step in VS Code

The web app runs collections in a **separate process**, so breakpoints in scraper code are
not hit when you start a collection from the app. Use one of these instead:

- **Run a worker yourself** under the debugger. Start a small research in the app, press
  *Stop*, then debug the module `price_lens.orchestrator.jobs` with the run folder as its
  argument. A `.vscode/launch.json` for that:

  ```json
  {
    "version": "0.2.0",
    "configurations": [
      { "name": "Web app", "type": "debugpy", "request": "launch",
        "module": "price_lens.webapp", "args": ["--no-browser", "--verbose"],
        "env": { "PI_OUTPUT_DIR": "${env:USERPROFILE}\\Documents\\price_lens_dev_output" } },
      { "name": "Worker (one run folder)", "type": "debugpy", "request": "launch",
        "module": "price_lens.orchestrator.jobs",
        "args": ["${input:runFolder}"] },
      { "name": "Current test file", "type": "debugpy", "request": "launch",
        "module": "pytest", "args": ["${file}", "-x", "-q"] }
    ],
    "inputs": [
      { "id": "runFolder", "type": "promptString",
        "description": "Full path of an output\\analyst_… folder" }
    ]
  }
  ```

  Running a worker again on a finished folder rewrites its result files, so use a test
  folder (`PI_OUTPUT_DIR`), not a real research.
- **Test a parser directly**, which is fastest for "a shop changed its page": save the page
  (*Ctrl+S* in Firefox, "Web page, HTML only") and run
  `parse_html(html, "ebay.de", "camera", rules)` in a Python console. See section 6.
- **Web-app functions** are plain Python: `from price_lens.webapp import api;
  api.run_detail("analyst_20260929_094509")` works in a console (with `PI_OUTPUT_DIR`
  set to the folder that contains the research).

---

## 6. Common changes, step by step

Always make the change, run the tests (`python -m pytest`), try it in the app, commit.

### A shop changed its website (most common)

Symptoms: a platform suddenly returns 0 listings everywhere, or prices/titles are empty.

1. Collect one storefront with a visible browser (section 5) and see what happens: cookie
   banner not closed? Bot check? Page loads but nothing is read?
2. **Nothing read:** the HTML changed. Save the search page, open it in Firefox, right-click
   a product → *Inspect*, and find new, stable selectors (prefer `data-…` attributes over
   generated class names). Update `marketplaces/<platform>/parser.py`.
3. **Cookie banner / paging:** that is in `scraper.py` (search for `cookie` or `consent`,
   or for the next-page logic).
4. Replace or add the saved page in `tests/fixtures/` and update the parser test
   (`tests/test_<platform>_parser.py`) to expect the new values.

### Add a country or storefront to an existing platform

1. Add the domain → country to `marketplaces/<platform>/constants.py` (and currency if
   needed). Everything else (plan builder, `CATALOG`, country groups) picks it up.
2. Check the language: `core/localization.py`, and `core/term_translations.py` for
   "words to leave out".
3. Run a storefront check on it in the app before using it for real.

### Add a new platform

1. Create `marketplaces/<name>/` with `constants.py`, `scraper.py`, `parser.py`. Copy the
   structure of the eBay one (the simplest). The scraper must offer `search_with_report(…)`
   returning a `ScrapeOutcome` (rows as a DataFrame with the common columns + a
   `ScrapeReport`).
2. Register it in `orchestrator/registry.py` and add its domains to `CATALOG` in
   `orchestrator/analyst.py` (and to the loop in `cli.py` `marketplace-locales`).
3. Add its display name to `PLATFORM_NAMES` in `webapp/static/js/dom.js`.
4. Add parser tests with a saved page, and a fake-adapter test like those in
   `tests/test_multi_platform.py`.

### Change a screen

1. Find the view in `webapp/static/js/views/`. Reload the browser to see changes.
2. If it needs new data: add a function to `webapp/api.py`, then a line in `ROUTES` in
   `webapp/server.py` (e.g. `route("GET", f"/api/runs/{RUN}/something")(lambda q, b, name:
   api.something(name))`), then call it from the view with `api.get('/api/…')`.
3. Styling goes into `app.css`. Use the existing colour variables (`--bg`, `--surface`,
   `--ink`, `--accent`, …, defined at the top) so light and dark mode both work.
4. Add a test in `tests/test_webapp.py` for the new API function.

### Other frequent spots

| Change | File |
|---|---|
| Excel report layout, summary columns | `orchestrator/price_report.py` |
| Result table columns / what the screens receive | `orchestrator/screens.py` |
| Default settings for new researches | `DEFAULT_EXECUTION` near the top of `webapp/api.py` |
| AI review instruction and answer format | `agent/assist.py` (`default_instruction`, `compact_prompt`) |
| Static exchange rates | `core/currency.py` |
| Country groups, product presets, time estimate | `orchestrator/planning.py` |
| Setup check | `core/doctor.py` |

---

## 7. Tests

```bat
.venv\Scripts\python -m pytest                     :: everything
.venv\Scripts\python -m pytest tests\test_webapp.py :: one file
.venv\Scripts\python -m pytest -k pause -x          :: tests with "pause" in the name, stop at first failure
.venv\Scripts\python -m ruff check src tests        :: style / obvious mistakes
```

- Tests **never open Firefox or visit shops**. Parsers are tested against saved pages in
  `tests/fixtures/`; runs are tested with fake scrapers (see `counting_adapter` in
  `tests/test_pause_resume.py` or `adapter` in `tests/test_new_features.py`).
- Tests write into temporary folders (`tmp_path` + `PI_OUTPUT_DIR`), never into `output/`.
- When you fix a bug, first write a test that fails because of it, then fix it.
- The tests do not prove that live shops work today. Check that in the app with the storefront
  check.

Important test files: `test_webapp.py` (API of the app), `test_pause_resume.py` (pause, stop,
crash recovery), `test_network_resilience.py` (internet drops), `test_*_parser.py`
(reading shop pages), `test_multi_platform.py` (whole runs with fake scrapers).

---

## 8. Rules that keep the program working

- **Never lose collected data.** Every storefront is checkpointed the moment it finishes;
  keep it that way when changing `localization.py` or `analyst.py`.
- `RunCancelled` and `RunPaused` derive from **`BaseException`** on purpose, so that the
  scrapers' `except Exception` blocks cannot swallow a stop. Do not catch
  `BaseException` in scraper code.
- In the stop handler of `run_analyst_plan`, do **not** call `log()`: it raises
  `RunCancelled` again while `cancel.flag` exists.
- Result CSVs are Excel-friendly UTF-8 (with BOM): read them with `encoding="utf-8-sig"`, as
  the existing code does. When you rewrite an existing result file (as *Update USD prices*
  does), change only the columns you mean to; ids and other text must stay exactly as they were.
- Windows: files can be briefly locked (Excel, OneDrive, antivirus). Deleting uses
  `history._rmtree_retrying`; writing JSON goes through a temporary file. Keep paths short
  (MediaMarkt diagnostics already do).
- The server only accepts requests from the same computer, and changes need the
  `X-PI-App: 1` header (set by `api.js`). Keep both checks.
- Both apps share `output/`. A change to a file format in a research folder must still read
  old research folders (`test_old_runs_are_not_offered_a_resume` is an example).
- Never commit `output/`, API keys or `.venv` (the `.gitignore` already excludes them).
- Keep the version in `pyproject.toml` and `src/price_lens/__init__.py` the same.
- Scrape politely: keep the delays, do not remove the retry limits, and stop when a shop
  shows a bot check instead of trying to get around it.

**AI coding assistants** (Copilot, Claude, …) are useful here, but `AGENTS.md`, `CLAUDE.md`
and `agent/SKILL.md` are written for AI agents that *run researches*, and they say not to
change scraper code. When you use an assistant to *develop*, tell it so explicitly ("this is a
development task, read docs/DEVELOPER_GUIDE.md"), and always run the tests afterwards.

---

## 9. Everyday git workflow and releases

```bat
git pull                          :: get the latest version first
:: … change, test …
git status                        :: what changed?
git add .
git commit -m "Zalando: new product card selector"
git push
```

For bigger changes, work on a branch (`git switch -c new-feature`, later merge it on GitHub
with a pull request) so `main` always works.

A **release** for colleagues: raise the version in `pyproject.toml` and
`src/price_lens/__init__.py`, add a section to `CHANGELOG.md`, push, then *Releases → Draft
a new release* on GitHub with tag `v1.1.0`. Details: [MAINTAINING.md](MAINTAINING.md).

---

## 10. Ideas and known small issues

Good first tasks for getting to know the code:

- `webapp/static/js/api.js`: the "server is not running" message still says
  `start_app.bat`. It should say `start_new_app.bat` (or `.command` on a Mac).
- Setup check: when only the output folder fails, the final hint still says "install
  Firefox". It should name the real problem (`setup_mac.command`, `setup_windows.bat`,
  `core/doctor.py`).
- A quick **health check of all storefronts** with one tiny search each, run regularly, so
  broken shops are known before a big research.
- Remove the previous Streamlit app (`apps/`, `start_app.*`, the `streamlit` dependency)
  once nobody uses it any more. Check `screens.py` users first.
- `api.py` is large (~1,250 lines); splitting it by screen (researches, review, fx…) would
  make it easier to work on.
- More platforms (e.g. ABOUT YOU; the plan format is already platform-neutral).

Record what you change in `CHANGELOG.md`, and update this guide when the structure changes.
