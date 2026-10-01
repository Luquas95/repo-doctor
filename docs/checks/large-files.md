# large-files – Velké soubory mimo Git LFS

**Kategorie:** Údržba · **Severity:** MED (binárky LOW) · **Automatická oprava:** ne

## Co kontrola hledá

Hledá soubory nad `limits.large_file_mb` (výchozí 5 MB) a binárky nad `limits.binary_file_kb` (výchozí 1 MB) v aktuálním stromu i v historii (`git rev-list --objects --all` + `git cat-file --batch-check`). Soubory spravované Git LFS se nehlásí.

## Proč to vadí

Velké bloby zpomalují každý klon a fetch a z historie nezmizí smazáním.

## Postup

1. Pro nové binárky použij Git LFS (`git lfs track "*.zip"`).
2. Z historie je odstraníš `git filter-repo --strip-blobs-bigger-than 5M` (přepis historie – rozhodnutí je na tobě).
