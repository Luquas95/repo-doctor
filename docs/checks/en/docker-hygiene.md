# docker-hygiene – Dockerfile hygiene

**Category:** Security · **Severity:** MED (secrets in ENV/ARG HIGH) · **Automatic fix:** `.dockerignore` only

## What the check looks for

Checks Dockerfiles for: `FROM` without a tag or with `:latest`, running as root (no `USER` in the final stage), secrets in `ENV`/`ARG`, `ADD` from a URL and a missing `.dockerignore`.

## Why it matters

Floating tags break reproducibility, root in a container widens the impact of a break-in, an `ENV` with a password stays in the image layers and without `.dockerignore` both `.git` and `.env` end up in the build context.

## Steps

1. Pin the image version (`python:3.12-slim`, ideally with a digest `@sha256:…`).
2. Add an unprivileged user (`RUN useradd -r app` + `USER app`).
3. Pass secrets at runtime or via `RUN --mount=type=secret`.
4. Replace `ADD https://…` with `RUN curl` and a checksum check.
5. The fix (`f`) only adds `.dockerignore`; Dockerfile changes are suggestions.
