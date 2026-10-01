# env-committed – Commitnutý citlivý soubor

**Kategorie:** Bezpečnost · **Severity:** HIGH · **Automatická oprava:** ano

## Co kontrola hledá

Hledá ve verzovaných souborech `.env`, `.env.*` (kromě `.env.example`/`.sample`/`.template`), `*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519`, `credentials.json`, `.netrc`, `.pgpass`, `terraform.tfvars` a podobné.

## Proč to vadí

Tyto soubory téměř vždy obsahují hesla nebo privátní klíče. Verzování je rozšíří všude, kam repo putuje.

## Postup

1. Oprava (`f`) přidá soubory do `.gitignore` a odebere je z gitu (`git rm --cached`) – na disku zůstanou.
2. Tajemství z nich považuj za prozrazená a rotuj je.
3. Pro odstranění z historie postupuj jako u `secrets-history`.
