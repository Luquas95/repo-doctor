# public-sensitive – Veřejné repo obsahuje konfiguraci infrastruktury

**Kategorie:** Bezpečnost · **Severity:** HIGH · **Automatická oprava:** ne

## Co kontrola hledá

Pokud je repo na hostingu veřejné (zjištěno přes API připojeného hostingu, u GitHubu i neautentizovaným dotazem), hledá v konfiguračních souborech privátní IP adresy (10/8, 172.16/12, 192.168/16), Tailscale adresy 100.64.0.0/10, hostname `*.ts.net`, inventáře (Ansible `hosts.yml`, `inventory`), `*.tfstate`, kubeconfig a WireGuard konfigurace. Bez znalosti viditelnosti je kontrola přeskočena.

## Proč to vadí

Mapa vnitřní sítě usnadňuje útočníkovi průzkum. Tailscale hostname prozrazuje název tailnetu a stroje.

## Postup

1. Rozhodni, jestli má být repo veřejné. Pokud ne, přepni ho na hostingu na privátní.
2. Jinak přesuň inventář a adresy do privátního repa nebo šablon s proměnnými.
3. Z historie je odstraníš jako u `secrets-history`.
