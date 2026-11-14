# ADR 0004: SQLite catalogue index for the prototype

**Status:** Accepted for the prototype · to be replaced in production

## Context
The mock backend offers only price and availability by product ID: no search. To find "lactose-free milk" we need our own index over the 17.5k-product catalogue, with structured allergens, "free from" claims, labels and pack sizes. Name search alone is wrong: "lactose-free" also matches cocoa drinks and cooking cream.

## Decision
Load the catalogue into a SQLite file at build time. Search filters on structured fields (e.g. `FREE_FROM_LACTOSE`, allergen flags) first, then ranks by text match. Price and availability are always fetched live from the mock APIs, never stored in the index.

## Consequences
- Zero infrastructure, fast, reproducible, easy to reset for demos.
- Single writer, no replication: fine for a demo, not for 20,000 customers.
- Production: Postgres for orders, mandates and audit; a search engine (e.g. OpenSearch) for catalogue search with Finnish and Swedish language analysis; the catalogue fed from Valio Aimo's product information system.
- The raw data files are not committed to the repo; a script builds the index.
