---
name: product-research
description: Plan and run local product research with this repository's Amazon, eBay, Zalando, and MediaMarkt scrapers; validate research plans, collect Selenium listings, perform evidence-based relevance review, and produce compact forecasting-ready data with a complete audit trail. Use for marketplace product collection, comparison, filtering, price research, forecasting inputs, or dataset QC.
---

# Product research

Operate through the repository CLI. Do not edit scraper selectors, marketplace constants, or
collection code during a research run.

## Workflow

For analysts using a standalone LLM instead of an editor agent, use the portable planning
instructions in `agent/llmskill.md`. They create analyst-v1 uploads for `apps/unified_app.py`
(`start_app.bat`). This app keeps country/website scope separate per search and exports CSV
and Excel candidates. It does not perform AI review; confidence remains blank. Do not confuse
analyst-v1 with the CLI research-plan schema used below.

1. Convert the analyst request into `research_plan.json` using
   `agent/research_plan.schema.json` and `examples/unified_research_plan.json`.
2. Ask only for choices that materially change scope: product definition, audience, condition,
   countries, marketplaces, and explicit brand restrictions. Do not expand a generic request
   into a brand whitelist. Generic means branded and unbranded products are eligible.
3. Use conservative defaults: one page, two retries, headless browsing, and 30 rows per review
   batch. For Zalando, always specify `men`, `women`, or `kids`. For MediaMarkt, use
   the requested country domain; enable detail enrichment only when structured condition, availability, colour,
   shipping, or exact brand evidence is needed.
4. Validate before opening a browser:

   ```bat
   price_lens.bat validate-research research_plan.json
   ```

5. Show the user the exact scope and obtain confirmation before unusually large runs.
6. Run the approved plan:

   ```bat
   price_lens.bat run-research research_plan.json
   ```

7. Read `research_report.json`. Report failed or missing marketplaces before reviewing data.
8. Read `ai_review/INSTRUCTIONS.md` and review every unfinished `batch_*.json`. Write decisions
   only to each batch's `output_file`, following `agent/relevance_decision.schema.json`.
9. Check progress when useful:

   ```bat
   price_lens.bat review-status output\research_<timestamp>\ai_review
   ```

10. Apply the decisions:

   ```bat
   price_lens.bat apply-ai-review output\research_<timestamp>\ai_review
   ```

11. Validate the final candidate count, marketplace coverage, confidence distribution, obvious
    product-type conflicts, duplicates, currencies, and price ranges before reporting results.

## Local-language query planning

- Run `price_lens.bat marketplace-locales` to inspect domain/language defaults.
  Choose one storefront language per domain/run; multilingual countries require an explicit choice.
- For every new agent-generated plan, set `require_localized_queries` to `true`. For each
  search, populate `localized_queries` for every applicable selected domain, with `language`
  and the translated `search_term`. Include mappings even when the query stays unchanged.
- Translate descriptive terms across Amazon, eBay, Zalando, and MediaMarkt. Preserve brands,
  model numbers, units, and the research intent. Translate include/exclude keywords as well,
  or omit them; untranslated base rules are intentionally not inherited. Never broaden scope
  or add brands during translation. The editor agent supplies translations without an extra API.
- See `examples/mediamarkt_international_research_plan.json` for the structure. Display actual
  localized queries in the plan. Use `run-research` to execute them. Standalone Streamlit and
  `scrape-*` inputs run verbatim. Other adapters may retain the site's current interface language;
  check it instead of inventing locale routes. MediaMarkt supports configured locale paths.
- Original terms and query languages remain in the full audit. Search context, including a
  translated query, is never evidence that a listing satisfies the requested attributes.

## MediaMarkt coverage checks

- Country domains are configured for DE, AT, CH, ES, NL, BE, PL, HU, TR, and Italy's
  `mediaworld.it`. Configuration is not proof that every live storefront passes collection.
  `mediamarkt.pt` is registered as unavailable because it redirects to Darty; do not collect
  or label Darty products as MediaMarkt.
- Preserve the user's page budget. Pages count distinct loaded batches, including load-more
  clicks. Inspect per-page new-product counts and failures; repeated IDs do not prove pagination.
  A `no_next_control` event means collection stopped, not verified catalogue exhaustion.
- Use `check-mediamarkt-marketplaces` with the plan path and `--marketplaces` to check only
  untested or failing domains. Do not repeat successful checks unless a related change requires it.
- Cookie handling rejects optional cookies. Report unresolved consent, redirects, and access
  challenges; do not claim successful collection after these failures.

## Review policy

Apply this section to every listing. Edit these rules when the team's policy changes.

### Evidence rules

- Review each listing semantically. Never generate decisions with keyword lists, regular
  expressions, shell scripts, Python scripts, or bulk rule classifiers.
- Copy every `row_id` exactly once. Do not change the batch, manifest, or review source files.
- Use only supplied fields. Prefer explicit structured `brand`, `condition`, `audience`, and
  `product_type` evidence, then the product title. The search term is collection context, not
  proof of an attribute.
- Treat missing evidence as uncertainty, not as proof that the listing is irrelevant.
- Use a high-confidence exclusion only for explicit contradictory evidence, such as a jacket
  in a T-shirt study, a used listing in a new-only study, a children's product in a men-only
  study, an accessory, or a clearly disallowed brand.
- Apply `review.allowed_brands` only when the user explicitly restricts brands. Leave it empty
  for generic or market-wide research.
- Do not reject a listing merely because one marketplace provides fewer structured fields.
- Keep product boundaries consistent across marketplaces. For example, decide explicitly
  whether polos, jerseys, multipacks, refurbished goods, or marketplace auctions belong in the
  research population.

### Decision format

```json
{
  "decisions": [
    {
      "row_id": "product_...",
      "keep": true,
      "category": "short normalized category",
      "confidence": 0.92,
      "reason": "Concise explanation tied to supplied listing evidence"
    }
  ]
}
```

`confidence` measures confidence in the keep/exclude decision:

- `0.90–1.00`: explicit, decisive evidence.
- `0.80–0.89`: strong evidence with no material conflict.
- `0.50–0.79`: incomplete or ambiguous evidence; retain as an uncertain candidate.
- Below `0.50`: use only when the proposed decision itself is highly unstable.

The merger converts decision confidence into `relevance_confidence_pct`:

- keep decision: `confidence × 100`
- exclude decision: `(1 − confidence) × 100`

Every decision below `review.minimum_keep_confidence` remains in `final_products.csv` with
`review_status=uncertain`, whether the tentative decision was keep or exclude. This prevents
low-confidence exclusions from disappearing silently.

## Output contract

- `final_products.csv`: compact forecasting/QC dataset containing accepted and uncertain
  candidates. Filter with `review_status` or `relevance_confidence_pct`; do not expect a separate
  manual-review CSV.
- `final_products.xlsx`: formatted Excel version of the same compact candidate dataset, with a
  filterable table, frozen identifying columns, numeric formats, and uncertainty highlighting.
- `ai_classified_products.csv`: complete audit dataset containing every reviewed row, original
  scraper fields, AI decision, reason, quality-gate evidence, confidence, and excluded rows.
- `coverage_report.json`: candidate and accepted coverage by marketplace and brand.
- `ai_review_report.json`: reviewed, accepted, uncertain, and excluded counts.

Do not describe uncertain candidates as accepted. Do not describe a multi-marketplace run as a
cross-marketplace result if the candidate file lacks one or more requested marketplaces.

## Guardrails

- Never attempt CAPTCHA bypass, credential extraction, access-control circumvention, or
  unapproved proxy rotation.
- Never invent marketplace domains. Use only plan-validator-supported domains.
- Keep raw HTML, credentials, cookies, and browser profiles out of AI-review files.
- Do not run unbounded retries or autonomous collection loops.
- Preserve raw, cleaned, detailed-audit, and compact final outputs.
