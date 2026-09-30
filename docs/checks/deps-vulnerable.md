# deps-vulnerable – Zranitelné závislosti

**Kategorie:** Bezpečnost · **Severity:** HIGH (podle závažnosti z OSV) · **Automatická oprava:** ne

## Co kontrola hledá

Parsuje lockfily (`uv.lock`, `poetry.lock`, `requirements*.txt` s `==`, `pyproject.toml` s pinem, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Cargo.lock`, `go.sum`) a dávkově se ptá **OSV.dev** (`/v1/querybatch`, bez klíče). Závažnost bere z databáze (GHSA: CRITICAL/HIGH → HIGH, MODERATE → MED, LOW → LOW). V offline režimu je přeskočena. Výsledky se cachují.

## Proč to vadí

Známé zranitelnosti mají veřejné exploity; aktualizace bývá nejlevnější obrana.

## Postup

1. Podívej se na ID zranitelnosti (GHSA/CVE/PYSEC) a zjisti opravenou verzi.
2. Aktualizuj závislost (`uv lock --upgrade-package X`, `npm update X`, `cargo update -p X`, `go get X@latest`).
3. Pokud aktualizace nejde, zvaž dopad a přidej nález do allowlistu s důvodem.
