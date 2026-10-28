# js-risks – Risky patterns in JavaScript and TypeScript

**Category:** Security · **Severity:** MED (some rules LOW) · **Automatic fix:** no

## What the check looks for

Reads `*.js`, `*.jsx`, `*.mjs`, `*.cjs`, `*.ts`, `*.tsx` line by line (excluding `*.min.js`, `*.d.ts`, tests and `node_modules`; comments and lines over 1000 characters are skipped). Looks for: `eval()`/`new Function()`, `exec()`/`execSync()` with a composed command (concatenation or a `${}` template), `.innerHTML =` and `document.write()`, `rejectUnauthorized: false` and `NODE_TLS_REJECT_UNAUTHORIZED=0` (MED), `dangerouslySetInnerHTML` and a leftover `debugger` (LOW).

## Why it matters

Building commands and HTML from unchecked text is classic command injection and XSS. Disabled TLS verification lets a server be impersonated. `dangerouslySetInnerHTML` is fine only for content that never comes from a user.

## Steps

1. Run commands through `execFile`/`spawn` with an argument list.
2. Insert `textContent` or sanitized HTML (DOMPurify) into the DOM.
3. Never disable TLS; add your own CA to the trust store instead.
