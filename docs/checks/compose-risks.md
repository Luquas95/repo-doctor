# compose-risks – Rizikové nastavení Docker Compose

**Kategorie:** Bezpečnost · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Parsuje soubory `docker-compose*.yml`, `compose*.yaml` (`yaml.safe_load`) a u každé služby hledá: `privileged: true`, připojený `docker.sock`, `network_mode: host`, `cap_add: ALL` nebo `SYS_ADMIN` a port databáze či cache (3306, 5432, 6379, 27017, 9200, 11211…) zveřejněný na všech rozhraních, tedy bez `127.0.0.1:`. Dockerfile řeší kontrola `docker-hygiene`.

## Proč to vadí

Privilegovaný kontejner nebo `docker.sock` dávají kontejneru v praxi root na hostiteli; kdo prolomí aplikaci, ovládne celý stroj. Databáze otevřená na všech rozhraních je na veřejném serveru dostupná celému internetu.

## Postup

1. Odeber `privileged`; potřebuje-li služba jedno právo, dej jen konkrétní `cap_add`.
2. Port databáze zveřejni jen na loopbacku: `"127.0.0.1:5432:5432"`, nebo ho nezveřejňuj a připoj služby do společné sítě.
3. `docker.sock` připojuj jen tam, kde je to nezbytné (a raději přes socket-proxy).
