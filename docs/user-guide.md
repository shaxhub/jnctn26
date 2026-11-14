# Agent Dairy user guide

Agent Dairy turns a kitchen’s product request or recipe into a quote the buyer can check before sending it to Aimo. Start the shared portal using the [local setup](../README.md#run-locally).

## Client workspace

Open [the client app](http://127.0.0.1:8000/) and choose **Hotel kitchen** or **Hospital kitchen** in the Workspace selector. Each demo buyer has a separate mandate, drafts, orders, settings, and request conversations.

| Page | What you can do |
| --- | --- |
| **Dashboard** | See draft and submitted-request counts and how requests are distributed across fulfillment stages. |
| **Product Search** | Ask for a product, paste a recipe, compare live offers, or browse seasonal Finnish produce for a delivery date. |
| **Draft Tickets** | Reopen saved quotes, adjust quantities or delivery dates, and review a draft before submitting. |
| **Submitted Requests** | Track an order, inspect its policy and audit history, and exchange messages with Aimo. |
| **Analytics** | View orders and net spend by delivery year, observed availability by month and SKU, frequently ordered items, and average fulfillment times. |
| **Settings** | Set theme and default language, record client and invoice details, control agent ordering, and configure next-day order reminders. |

The sidebar includes **EN** and **FI**, help and FAQs, and demo sign-out. Finnish covers navigation, key headings, and fulfillment stages. Some secondary text remains in English.

### Find a product or paste a recipe

1. Open **Product Search** and use the **Ask Agent Dairy** box. Try `I need 200 litres of lactose-free milk by Monday`. You can also enter a delivery date explicitly to override the interpreted date.
2. To source a recipe, paste a name with its yield followed by measured ingredients. Select a delivery date for stock and price results. Without a date, the recipe flow compiles quantities.

   ```text
   Tomato salad (4)
   500 g tomato
   80 g red onion
   12 g basil
   ```

   The guided parser accepts `g`, `kg`, `ml`, `dl`, `l`, and `pcs`. Put a blank line between recipes. Gemini 4 Hydrogen can interpret less structured input when configured. Review the interpreted quantities and units.

3. Choose **Check offers**. Check net prices, sales units, stock, earliest dates, and alternatives. Where available, the offers include origin, delivery reliability, and a carbon intensity estimate. Enter a Finnish postcode to include an estimated travel time from Rautatientori.
4. Choose **Create ticket draft**, or **Draft this plan** on a ranked product plan. A recipe draft needs all ingredients sourced for the selected date. Review proposed culinary substitutions before using them in the recipe.

### How the travel estimate works

The estimator takes a five-digit postcode or extracts one from an address. It looks up a point in that postcode area, computes the straight-line distance from Rautatientori in Helsinki, and multiplies by 1.3 to approximate road distance. It assumes 30 km/h, adds 10–20 minutes for stops, and rounds both ends of the range up to the next five minutes.

The estimate is independent of Aimo's price and stock data. It ignores actual routes, traffic and ferry schedules. Delivery coverage and the exact address require separate verification. When a postcode has no geographic area in the dataset, the estimator returns `estimate_unavailable`.

The bundled [postcode coordinates](../app/gateway/finnish_postcode_areas.csv) are derived from Statistics Finland's [Paavo 2026 postcode areas](https://stat.fi/en/services/statistical-data-services/geographic-data/geographic-data-by-postal-code-area), downloaded on 15 November 2026 under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). To refresh them, export `postialue:pno_2026` or its replacement from the [Paavo WFS](https://geo.stat.fi/geoserver/postialue/wfs) as EPSG:4326 GeoJSON. For each `posti_alue`, use the polygon centroid if it lies within the area, or an interior representative point otherwise. Save the results in postcode order as `postcode,latitude,longitude` with coordinates rounded to five decimal places.

### Review and submit a draft

1. Open **Draft Tickets** and pick a saved draft, or use **Ticket review** directly after creating it.
2. Check the line quantities, net total, delivery date, policy preview, and quote expiry. **AI Helper** can propose changes to existing items and their quantities. The local guided helper accepts a correction such as `Set 464306 to 12`. Review the proposed values and choose **Save revised draft** to refresh prices and stock.
3. Choose **Review and submit**, then **Submit ticket to Aimo**. An expired draft needs a fresh quote. Repeating the submit request for the same quote returns the existing ticket.
4. Check **Submitted Requests**. Routine orders register automatically. Exceptions remain pending until Aimo reviews them. Registered orders progress through **Retrieving goods**, **On delivery**, **Almost there**, and **Arrived**. Rejected and expired requests have separate outcomes.
5. Open a request to see its timeline and conversation. Use **Refresh conversation** to load updates. A buyer’s authenticated MCP agent can read or post to the same thread. The request also displays its policy decision and audit trail.
6. To reorder, open a confirmed ticket and use **Create repeat draft** with the new delivery date. Check the recurring comparison before submitting. This obtains a fresh quote for the existing lines.

### Control agent access and plan recurring orders

Under **Settings**, clear **Allow agents to place orders** to block ordering by that buyer’s external agents. Product and status lookups remain available. The browser still gives the buyer a separate draft review and submission step.

A daily reminder appears in the signed-in workspace from the chosen Helsinki time onward and refers to the next day. It creates no ticket on its own. Billing settings store a payment method, billing email, and invoice reference for the demo. Orders are simulated locally.

Analytics use available observations. Monthly product availability is based on recorded quote-independent offer checks and counts products that were orderable at those checks. Months with no observations have no percentage. Submission-to-arrival averages use requests marked **Arrived**.

## Aimo operations

Sign in at [the workspace](http://127.0.0.1:8000/) with an admin account, then choose **Admin panel** in the sidebar. The panel shares your login; buyer accounts do not see this button and cannot access operations. Admin accounts also have the complete buyer workspace, with a Workspace selector for hotel and hospital kitchens. Returning from operations keeps the selected kitchen. For local API-key demos, open `/admin/` and enter `AIMO_ADMIN_API_KEY`.

1. In **Review queue**, filter by client, status, product, or ticket. Open a request to inspect policy reasons, order details, and the audit trail.
2. Approve or reject a pending exception. Approval checks expiry and rechecks current orderability. A request can expire or fail that recheck before registration.
3. Advance a registered request one fulfillment stage at a time. Use its conversation to tell the buyer or their agent about changes.
4. Use **Activity log** to search across clients and **Analytics** to compare order volumes, spend, estimated product emissions, and the most active sectors, buyers, and products over a selected period.

See the [architecture and decisions](architecture.md) for the rules behind approvals, quote signing, and audit evidence.
