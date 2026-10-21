# public-sensitive – Public repo contains infrastructure configuration

**Category:** Security · **Severity:** HIGH · **Automatic fix:** no

## What the check looks for

If the repo is public on the hosting (detected through the connected hosting's API, for GitHub also with an unauthenticated request), it looks in configuration files for private IP addresses (10/8, 172.16/12, 192.168/16), Tailscale addresses 100.64.0.0/10, `*.ts.net` hostnames, inventories (Ansible `hosts.yml`, `inventory`), `*.tfstate`, kubeconfig and WireGuard configurations. Without knowing the visibility, the check is skipped.

## Why it matters

A map of the internal network makes reconnaissance easier for an attacker. A Tailscale hostname reveals the name of the tailnet and the machine.

## Steps

1. Decide whether the repo should be public. If not, make it private on the hosting.
2. Otherwise move the inventory and addresses to a private repo or to templates with variables.
3. Remove them from history as for `secrets-history`.
