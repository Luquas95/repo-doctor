# docker-hygiene – Hygiena Dockerfile

**Kategorie:** Bezpečnost · **Severity:** MED (tajemství v ENV/ARG HIGH) · **Automatická oprava:** jen `.dockerignore`

## Co kontrola hledá

Kontroluje Dockerfile: `FROM` bez tagu nebo s `:latest`, běh pod rootem (ve finální fázi chybí `USER`), tajemství v `ENV`/`ARG`, `ADD` z URL a chybějící `.dockerignore`.

## Proč to vadí

Plovoucí tagy rozbijí reprodukovatelnost, root v kontejneru zvětšuje dopad průniku, `ENV` s heslem zůstane ve vrstvách image a bez `.dockerignore` se do build contextu dostane `.git` i `.env`.

## Postup

1. Připni verzi image (`python:3.12-slim`, ideálně i digest `@sha256:…`).
2. Přidej neprivilegovaného uživatele (`RUN useradd -r app` + `USER app`).
3. Tajemství předávej za běhu nebo přes `RUN --mount=type=secret`.
4. `ADD https://…` nahraď `RUN curl` s ověřením kontrolního součtu.
5. Oprava (`f`) přidá jen `.dockerignore`; úpravy Dockerfile jsou návrh.
