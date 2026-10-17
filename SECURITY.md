# Security policy

This initial 0.1.x release is the supported development line; no formal security SLA
or third-party audit is promised. Do not expose hostile-code execution publicly
without independently reviewing docs/SECURITY_MODEL.md and validating your isolation.

Use the repository's GitHub **Security → Report a vulnerability** if private reporting
is enabled. Otherwise contact the repository owner privately through their published
GitHub contact mechanism; if unavailable, open a minimal issue requesting a private
reporting channel without exploit details. Never post tokens, signing keys, private
source or a live exploit against deployed servers in public issues.

Include affected version, impact, reproducible steps in a disposable test environment,
and suggested mitigations. Coordinate disclosure with maintainers; allow reasonable
time to investigate. No bug bounty or response-time guarantee is offered.

Rotate exposed credentials immediately. Keep Docker/kernel/worker images updated,
restrict ingress/egress, use TLS and least-privilege publication tokens. Containers
are not a complete VM security boundary. API controllers with Docker access are
host-administrative; untrusted workers must never receive the Docker socket.
