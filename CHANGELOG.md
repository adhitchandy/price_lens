# Changelog

## 1.0.0 (2026-09-30)

First release of the new Price Lens app.

**Research**

- A new app in the browser (`start_new_app.bat` / `start_new_app.command`) with light, dark
  and system themes. The previous Streamlit app stays available as a fallback.
- **Researches** home: every research and draft, with status, listing count, median price and
  price spread.
- **Plan builder**:
  - search words per language, with a warning for countries without a local word
  - audiences (men / women / kids), and words to leave out, with suggested translations
  - price range, and where to search, platform by platform
  - collection size and a time estimate

  Drafts save themselves. Plans can be written by any AI chat and imported.
- **Storefront check** before a large run, and a **Storefront health** page.

**Collecting**

- Live progress per storefront. A **Pause** finishes the current storefront, and
  **Resume collecting** later collects only what is missing, into the same research, even after
  a restart.
- Nothing collected is lost when the computer sleeps, crashes or shuts down, or when you press
  Stop. Every storefront is saved as soon as it finishes and recovered when you open the research.
- Internet drops: the run waits up to 15 minutes and collects the interrupted storefront again.
- **Retry** only the storefronts that returned nothing.

**Review and results**

- **AI relevance review** with Claude (API key) or any AI chat by copy and paste. Any decision
  can be changed by hand.
- **Results**:
  - a plain-language finding and filters
  - a price chart per storefront with the overall median
  - a summary, and an Excel report and CSV of exactly what is shown

**Exchange rates**

- Daily European Central Bank rates, the static fallback table, and your own rates. Your rates
  can be kept for every research or used for the next one only.
- A finished research can be recalculated with today's rates.

**Other**

- Works on Windows and macOS (`setup_windows.bat` / `setup_mac.command`).
- The project folder can be moved, renamed or copied; reviews always use their own files.
