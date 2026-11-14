# ADR 0007: Share the buyer and admin portal origin

**Status:** Accepted · Supersedes the host split in ADR 0006

## Decision

Serve the buyer workspace at `/` and operations at `/admin/` from `gateway.api:app` on port 8000. The common login accepts existing buyer and admin accounts and issues a revocable, HTTP-only session cookie scoped to the deployment prefix. Session status includes the account role. Only admin accounts see the admin panel sidebar entry; operations endpoints continue to enforce `require_admin`.

Admin accounts can use the full buyer workspace and select the hotel or hospital kitchen. Each buyer request carries the selected workspace in `X-Workspace-Buyer`; the server permits this selection only for an authenticated admin account and applies the selected kitchen’s mandate. The resulting buyer principal records the admin username in its actor identity. Buyer accounts retain their assigned buyer scope regardless of that header and cannot open the admin page. Same-origin checks remain required for cookie-authenticated writes.

The default local launcher and private deployment run one server. The old `gateway.admin_app:app` entry point and its role-scoped login remain available for compatibility. Existing deployments should disable their old admin service and route when switching to the shared portal.
