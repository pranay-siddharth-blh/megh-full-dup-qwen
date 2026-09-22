## Purpose

Throttles request volume per caller on the endpoints that need it
(`/api/query` for normal traffic shaping, `/api/auth/login` for
brute-force resistance), keyed by a stable caller identity rather than
client IP alone, so shared IPs (an office NAT, a mobile carrier) don't
share one throttle bucket for authenticated traffic.

## ADDED Requirements

### Requirement: An authenticated caller is rate-limited by identity, not shared IP
When a request carries a valid, unexpired bearer token, the system SHALL
key that request's rate-limit bucket by the token's authenticated
identity, not by client IP — two different users behind the same IP
(a shared office network, a corporate VPN, a mobile carrier NAT) SHALL
NOT share a rate-limit bucket, and the same user SHALL share one bucket
across different IPs (e.g. switching networks mid-session).

#### Scenario: Two authenticated users behind the same IP get independent limits
- **WHEN** two different authenticated users send requests to `/api/query`
  from the same client IP, each within their own limit
- **THEN** neither is rate-limited by the other's request volume

#### Scenario: The same authenticated user keeps one limit across IPs
- **WHEN** the same authenticated user sends requests to `/api/query` from
  two different client IPs within one rate-limit window
- **THEN** both requests count against the same bucket, not two separate
  per-IP buckets

### Requirement: An unauthenticated or invalid-token request falls back to IP-based limiting
When a request carries no bearer token, or a token that fails validation
(bad signature, wrong issuer, expired) for any reason, the system SHALL
fall back to the existing IP-based rate-limit key — this SHALL NOT reject
the request for the invalid token (that is a downstream authorization
concern, not this layer's), and SHALL NOT crash or 500 the request.

#### Scenario: An expired token still gets a rate-limit decision via IP fallback
- **WHEN** a request to `/api/query` carries an expired or otherwise
  invalid bearer token
- **THEN** the rate limiter falls back to that request's client IP for its
  bucket key and returns a normal allow/deny decision — it does not error

#### Scenario: /api/auth/login is always IP-keyed
- **WHEN** a request to `/api/auth/login` is evaluated (a caller
  authenticating for the first time has no token yet by definition)
- **THEN** the rate-limit bucket is keyed by client IP, matching current
  behavior — this endpoint's brute-force throttle is unaffected by this
  capability

### Requirement: Identity extraction for rate limiting adds no new failure mode or authorization side effect
Determining the rate-limit identity SHALL be a cheap, local operation
(signature/issuer/expiry validation only) that never performs a database
lookup and never itself authorizes or denies the request on the token's
validity — a request with a well-formed but otherwise-invalid token is
rate-limited via IP fallback and then proceeds to the route's own
authentication/authorization checks unaffected.

#### Scenario: Rate-limit identity extraction does not duplicate or replace route-level authentication
- **WHEN** a request reaches its route after passing the rate limiter
- **THEN** the route's own authentication dependency independently
  validates the token and rejects it if invalid, exactly as it did before
  this capability existed — the rate limiter's own token check has no
  bearing on whether the request is ultimately authenticated
