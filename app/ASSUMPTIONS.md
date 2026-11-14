# Assumptions

Everything the gateway assumes, so judges and teammates can challenge it. Update this file when code changes.
See also [README.md](README.md), [Architecture Decision Records](../docs/adr/), and the [production roadmap](../docs/roadmap.md).

## Valio mock API
1. **Order cutoff.** `closingTime` is the last moment to order for the requested delivery date. If it is at or
   before *now* (the later of the API's `timeNow` and `store.now()`, unless `DEMO_NOW` is configured), the product is
   **not orderable** for that date, even though `scheduleLines` still show stock. Reason `cutoff_passed`. Observed:
   Terminal products for a Monday delivery close the previous Thursday 15:00; Stock products close Sunday 17:00.
2. **Unlimited stock.** `availableAmount >= 999999` means effectively unlimited. Terminal products always report
   999999 (Valio does not know the supplier's stock); some Stock products report 9999999999.
3. **Limited stock.** A positive amount below that is a hard cap in sales units; the planner caps the line and
   splits the rest onto other products. `0` means not available (`insufficient_stock`). Between quote and order,
   `place_order` re-checks live availability and rejects with `quote_invalid` if stock dropped below the quoted qty.
4. **Unknown availability.** No `closingTime` / `logisticModel` and empty `scheduleLines` (about 18 % of products)
   means unknown: not offered by the planner; if an agent quotes it anyway the mandate's `unknown_availability`
   rule sends it to a human.
5. **Later date.** If `availableDate` is after the requested date, the product is not orderable for that date
   (`later_date`). We include `available_date` in the excluded metadata; automatic re-planning for a later date is
   on the roadmap.
6. **Sales block.** `salesBlock` on the product or the schedule line means not orderable.
7. **Customer id is ignored** by the mock (documented); we send `VALIO_CUSTOMER_ID` (default `123`) for every buyer,
   and include `customer` in the client cache key so multi-customer caches never mix in production.
   In production the buyer's Valio customer number would come from the mandate/credential, never from the agent.
8. **Prices** are per sales unit. We use `catalogPrice.value` (net, without VAT) for totals and limits;
   VAT-inclusive totals are shown for information. `comparisonPrice` is per L or KG. If `catalogPrice.validTo` is
   already at or before *now*, the offer is treated as `no_price` (not orderable).
9. **Rate limits and transient errors.** Rate limits are undisclosed: we only query prices/availability for a search
   shortlist, cache results for 60 s (`VALIO_CACHE_TTL_S`), retry transient timeouts/429/5xx up to 2 times with short
   backoff, and fall back to stale cache entries if available before returning HTTP 502 / MCP tool errors.

## Units and quantities
10. Quantities in quotes and orders are in **sales units** (`salesUnit`: ST, KI, PAK...). `units[].sizeInBaseUnits`
    gives base units per sales unit. For `PCS`/`ST`/`KPL` needs, `amount_per_sales_unit` rejects weight/volume-backed
    products (`base_unit` in `KG`, `L`, `LTR`, `KGM`) rather than treating kg-per-box as piece counts.
11. **Litres/kg per sales unit**: from GS1 Synkka `unitConversions` (`BASE_UNIT_OR_EACH`, or `CASE` fallback when
    `BASE_UNIT_OR_EACH` lacks measurements — including volume conversions even when `baseUnit == "KG"`), otherwise
    parsed from the Finnish name (`"1 l"`, `"2,5 dl"`, `"100x2 cl"`, `"96kpl 80g"`, `"13g x 110 kpl"`, `"6KPL/20CL"`).
    Cross-checked live with `catalogPrice / comparisonPrice` (rounded to 4 decimals); if they agree within 5 % on the
    same unit the catalog wins, otherwise the price-API ratio wins (`price_api`). `volume.unit` is sometimes `GRM` or
    `H87` in the data; we ignore those.
12. Orders are rounded **up** to `allowedLotSize` (with a minimum lot of 1 whole pack whenever `sales_unit != "KG"`).
    When limited stock caps a line, quantity is rounded **down** to what is available. Coverage can therefore exceed 100 %.
13. A litre need is not filled with kg products (no density conversion).

## Products, claims, allergens and sustainability
14. "Lactose-free" = `FREE_FROM_LACTOSE` from `nutritionalClaim` or `nonAllergen` (`ML` `FREE_FROM`, mapped into search
    claims). Name search alone also returns cocoa drinks, coffee milk and cooking cream. Lactose-free dairy milk still
    CONTAINS milk protein (`AM`).
15. Allergen codes are GS1 AllergenTypeCode values. The schema does not define them; our code→name map is in
    `gateway/models.py` (including dataset codes `ABD`, `ADQ`, `BP`, `CM`, `NP`, with inferred entries marked `(?)`).
    Groups: `milk` = `AM, ML`; `gluten` = `AW, UW, GB, NR, GS, GK` (oats `GO` is a separate `"oats"` group);
    `nuts` = `AN, PN, SA, SC, SH, SM, SP, SR, ST, SW`. `expand_allergens` also normalizes plurals and common aliases
    (e.g. `dairy`, `eggs`, `peanuts`).
16. `CONTAINS` of a forbidden allergen → `reject` (no override). `MAY_CONTAIN` → per mandate (hospital: `needs_approval`).
    `UNDECLARED` is ignored.
17. Data quality: some products contradict themselves (e.g. a `FREE_FROM_GLUTEN` claim plus an `AW` allergen), and some
    of Valio's listed substitutes contain allergens the original did not. The gateway trusts the allergen list over claims
    and filters mandate-forbidden items in the planner when safe alternatives exist.
18. Substitutes: Valio's `substitutions` list exists for **189 products** (250 substitution entries in the 17,546-product
    dataset). `plan_need` automatically fetches live offers for listed substitutes when preferred products are not
    orderable, and `policy.py` evaluates `substitution_preference` whenever a line differs from `preferred_product_ids`.
19. Delivery reliability (0–1) is known for **4,425** products (default `0.95` when missing); CO2 category averages
    (`kg CO2e/kg`) are known for **11,033** products. The planner's `balanced` strategy uses reliability and a small
    CO2 tie-breaker factor, and plans expose `avg_reliability` and `estimated_co2_kg`.

## Mandates, approvals, audit and demo clock
20. The **mandate is issued by the buyer organisation** (e.g. F&B manager, clinical dietitian) and stored with the gateway.
    The agent's credential selects it; no tool or endpoint takes a buyer id or limit from the agent. Approver keys
    cannot call MCP tools, quote, or order (`require_agent`), and agent keys cannot approve (`require_approver`).
21. Limits are on **net** (VAT-free) totals. The weekly limit counts the current ISO week (Mon–Sun, Helsinki time) of
    orders that are confirmed or pending approval, by creation time.
22. `hard_cap` defaults to 5 × the per-order limit and to 5 × the requested quantity; above it (or outside
    `allowed_categories`) the order is rejected outright (a human cannot approve it through this channel).
23. Policy runs at quote time (preview) and again at order time (binding), after re-checking live availability.
24. Only approver keys can decide approvals, and only for their own buyer. Approving after the quote expired marks the
    order `expired` and the approval `rejected` (prices/cutoff no longer guaranteed).
25. Quote expiry = earliest of price `validTo` and line order cutoffs; when no line has a cutoff (e.g. `no_availability_data`),
    expiry is capped at `min(price validTo, now + 2 h)`.
26. "Confirmed" means accepted by the gateway. The mock has no order endpoint, so nothing is sent to Valio.
27. The audit log is append-only (SQLite triggers) and hash-chained (SHA-256 over the previous hash plus canonical
    JSON), verified with contiguous `seq` starting at 1. This detects tampering unless a DB admin rewrites the whole
    chain; anchoring the head externally is on the roadmap.
28. Time zone: `Europe/Helsinki` for all timestamps and week boundaries. `DEMO_NOW` (env var) or `POST /demo/reset`
    can pin a fixed demo clock for reproducible cutoff demonstrations.
# Aimo catalog source files

The SQLite importer reads the Aimo product JSON and joins the delivery reliability and carbon footprint CSVs by product code. A separate `data_schema` file is optional for this application. The importer defines the database schema in `gateway/load_catalog.py`.
