# forge-security-alerts – Open security alerts

**Category:** Hosting · **Severity:** HIGH (secret scanning), MED (Dependabot) · **Automatic fix:** no

## What the check looks for

The number of open Dependabot and secret scanning alerts on GitHub (if the token has access to them). Other hostings do not provide alerts through the API – the check is skipped.

## Why it matters

The hosting has already found the problem; an unresolved alert is a known hole.

## Steps

1. Go through the alerts on the hosting's website and resolve them (update the dependency, rotate the secret).
