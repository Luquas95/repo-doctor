# email-exposure – Osobní e-mail v historii veřejného repa

**Kategorie:** Bezpečnost · **Severity:** MEDIUM · **Automatická oprava:** ano (jen lokálně `.git/config`)

## Co kontrola hledá

U repozitářů, které jsou na hostingu **veřejné** (stejné zjištění jako u `public-sensitive`), projde e-maily autorů a commiterů v publikované historii (remote-tracking větve, nejvýš 20 000 commitů). Hlásí jen **tvoje** adresy: tu z `git config --global user.email`, adresy z volby `my_emails` v konfiguraci a adresy u běžných poskytovatelů pošty (Gmail, Proton, Seznam…) u commitů s tvým jménem (`user.name`). `noreply` adresy hostingů a cizí přispěvatele nehlásí. E-mail je ve výstupu vždy maskovaný (`l***@proton.me`).

## Proč to vadí

Adresa v historii veřejného repa je dostupná komukoli (`git log`, API hostingu) – sbírají ji spammeři a dá se spojit s tvými dalšími účty.

## Postup

1. Na hostingu zapni skrývání e-mailu a použij `noreply` adresu: GitHub → Settings → Emails → *Keep my email addresses private* (adresa `ID+login@users.noreply.github.com`), GitLab → Preferences → *Commit email* → private, Gitea/Forgejo → Nastavení → *Skrýt e-mailovou adresu*.
2. Nastav ji pro nové commity: `git config --global user.email <noreply-adresa>` (všude), nebo jen v tomto repu přes léčbu – repo-doctor zapíše `user.email` do `.git/config`, nic necommituje.
3. Starou historii jde přepsat (`git filter-repo --mailmap mapa.txt` a force push), ale **rozbije to forky, klony ostatních a odkazy na commity**. repo-doctor to nikdy nedělá sám; zvaž, jestli to za to stojí.
