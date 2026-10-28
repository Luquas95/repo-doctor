# compose-risks – Risky Docker Compose settings

**Category:** Security · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Parses `docker-compose*.yml` and `compose*.yaml` files (`yaml.safe_load`) and, for each service, looks for: `privileged: true`, a mounted `docker.sock`, `network_mode: host`, `cap_add: ALL` or `SYS_ADMIN`, and a database or cache port (3306, 5432, 6379, 27017, 9200, 11211...) published on all interfaces, i.e. without `127.0.0.1:`. Dockerfiles are covered by the `docker-hygiene` check.

## Why it matters

A privileged container or `docker.sock` effectively gives the container root on the host; whoever breaks the application controls the whole machine. A database open on all interfaces is reachable from the whole internet on a public server.

## Steps

1. Remove `privileged`; if a service needs one capability, add just that `cap_add`.
2. Publish a database port on loopback only: `"127.0.0.1:5432:5432"`, or do not publish it and put the services on a shared network.
3. Mount `docker.sock` only where unavoidable (preferably through a socket proxy).
