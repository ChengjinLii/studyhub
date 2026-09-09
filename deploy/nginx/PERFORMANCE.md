# Upstream connection reuse

Include `studyhub-upstreams.conf` once in the Nginx `http` context.
In the HTTPS server, use HTTP/1.1 and clear the `Connection` header for ordinary
HTTP requests. Point the existing backend/frontend proxy locations at the named
upstreams, keeping their URI suffixes unchanged. SSE does not require an Upgrade
header. If WebSockets are introduced, configure Upgrade only in their location.

Include `studyhub-json-routes.conf` inside that same server. It bounds comment
request bodies to 256 KiB; do not reuse it for multipart upload endpoints.
It intentionally inherits existing authentication-independent abuse controls and
security response headers. Registration limits and CSP are not changed.

For a direct-origin deployment, overwrite `X-Forwarded-For` with `$remote_addr`.
If a CDN is added later, configure trusted `set_real_ip_from` ranges and origin
ingress restrictions first. Never trust arbitrary client forwarding headers.

Before installation, back up the live site configuration outside the repository.
Run `nginx -t` before a graceful reload. If validation fails, restore the old site
file before attempting another reload. Verify public pages, API GETs, oversized
comment rejection, protected metrics, and unchanged security headers afterward.

References:
- https://nginx.org/en/docs/http/ngx_http_upstream_module.html#keepalive
- https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size

# Deployment and measurement boundaries

Atomic release now requires 3 GiB free disk and 1 GiB available memory before
installation. Candidate prewarming has bounded retries and must succeed before
switching. A failed attempt only removes a release created by that attempt.

The service restart remains a restart, not zero-downtime blue/green deployment.
Candidate memory caches do not survive restarting production services; production
ExecStartPost prewarming remains necessary. Retaining candidates and draining old
connections is a separate rollout change, not provided by these guards.

HTTP access logs include `db_query_count` and `db_query_ms`. These measure completed
SQL executions within request context, not pool checkout/connection time, failed
queries or complete streaming response time. SQL text, bind values and user tokens
are never recorded by this instrumentation. Compare identical requests and cache
states before drawing performance conclusions.

Redis middleware calls run off the event loop. On failure, local limits continue
and a five-second retry cooldown prevents repeated connection delays. Fallback
events are counted; local limits are per process and are not equivalent to Redis
global limits. This is degraded protection, not a replacement for healthy Redis.
