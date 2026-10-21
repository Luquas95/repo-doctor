"""Únik osobního e-mailu v historii veřejného repa (`email-exposure`)."""

from __future__ import annotations

from collections import Counter

from repo_doctor import czech
from repo_doctor.checks.base import Check, RepoContext, SkipCheck, register
from repo_doctor.gitwrap import user_identity
from repo_doctor.i18n import N_, _
from repo_doctor.masking import REGISTRY, mask_email
from repo_doctor.models import Category, Finding, LocalAction, Patch, Severity
from repo_doctor.secrets_scan import fingerprint

MAX_COMMITS = 20_000

# Domény běžných poskytovatelů osobní pošty (adresa na nich je skoro jistě osobní).
PERSONAL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "proton.me",
        "protonmail.com",
        "pm.me",
        "tutanota.com",
        "tuta.io",
        "gmx.com",
        "gmx.net",
        "gmx.de",
        "web.de",
        "mail.ru",
        "yandex.ru",
        "yandex.com",
        "aol.com",
        "zoho.com",
        "fastmail.com",
        "hey.com",
        "seznam.cz",
        "email.cz",
        "post.cz",
        "centrum.cz",
        "atlas.cz",
        "volny.cz",
        "azet.sk",
        "zoznam.sk",
        "wp.pl",
        "o2.pl",
        "posteo.de",
        "mailbox.org",
    }
)


def is_noreply(email: str) -> bool:
    """`noreply` adresy hostingů (GitHub, GitLab, Gitea/Forgejo i vlastní instance)."""
    local, _sep, domain = email.casefold().partition("@")
    return (
        "noreply" in domain
        or "no-reply" in domain
        or local in {"noreply", "no-reply"}
        or domain.endswith(".localhost")
        or domain == "localhost"
    )


def is_personal_domain(email: str) -> bool:
    return email.casefold().rpartition("@")[2] in PERSONAL_DOMAINS


@register
class EmailExposure(Check):
    id = "email-exposure"
    title = N_("Osobní e-mail v historii veřejného repa")
    severity = Severity.MEDIUM
    category = Category.SECURITY
    network = True  # viditelnost se zjišťuje z hostingu
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.visibility == "unknown":
            raise SkipCheck(_("viditelnost repa na hostingu neznámá"))
        if repo.visibility != "public":
            return []
        names, emails = user_identity()
        emails = emails | {e.strip().casefold() for e in repo.config.my_emails if e.strip()}
        if not names and not emails:
            raise SkipCheck(
                _("neznám tvůj e-mail – nastav git config --global user.email nebo my_emails")
            )
        # veřejná historie = to, co je na remotu; bez remote-tracking větví aspoň HEAD
        refs = ["--remotes"] if repo.git.run("branch", "-r", check=False).strip() else ["HEAD"]
        out = repo.git.run(
            "log",
            f"--max-count={MAX_COMMITS}",
            "--format=%an%x00%ae%x00%cn%x00%ce",
            *refs,
            "--",
            check=False,
        )
        lines = out.splitlines()
        counts: Counter[str] = Counter()
        originals: dict[str, str] = {}
        for line in lines:
            parts = line.split("\0")
            if len(parts) != 4:
                continue
            seen: set[str] = set()
            for name, email in ((parts[0], parts[1]), (parts[2], parts[3])):
                key = email.strip().casefold()
                if not key or "@" not in key or is_noreply(key) or key in seen:
                    continue
                mine = key in emails or (
                    name.strip().casefold() in names and is_personal_domain(key)
                )
                if mine:
                    seen.add(key)
                    counts[key] += 1
                    originals.setdefault(key, email.strip())
        findings: list[Finding] = []
        noreply = repo.noreply_email or ""
        for key, n in counts.most_common():
            REGISTRY.add(originals[key])  # obrana do hloubky: nikde jinde se neobjeví celý
            masked = mask_email(originals[key])
            findings.append(
                self.finding(
                    _("veřejná historie obsahuje tvůj e-mail {masked} ({commits})").format(
                        masked=masked, commits=czech.commits(n)
                    ),
                    key=fingerprint(key),
                    fixable=bool(noreply),
                    email=masked,
                    commits=n,
                    noreply=noreply,
                )
            )
        if findings and len(lines) >= MAX_COMMITS:
            findings.append(
                self.incomplete(
                    _("prošlo se jen posledních {MAX_COMMITS} commitů").format(
                        MAX_COMMITS=MAX_COMMITS
                    )
                )
            )
        return findings

    def fix(self, repo: RepoContext, findings: list[Finding]) -> Patch | None:
        noreply = next((str(f.data.get("noreply")) for f in findings if f.data.get("noreply")), "")
        if not noreply:
            return None
        current = repo.git.config_get("user.email") or ""
        if current.casefold() == noreply.casefold():
            return None
        return Patch(
            check_id=self.id,
            title=_("noreply e-mail pro nové commity"),
            summary=_(
                "user.email v tomto repu → {noreply} (jen .git/config, historie se nemění)"
            ).format(noreply=noreply),
            local=[
                LocalAction(
                    kind="git_config",
                    key="user.email",
                    value=noreply,
                    description=f"git config --local user.email {noreply}",
                    display_old=mask_email(current) if current else None,
                    display_new=noreply,
                )
            ],
            notes=[
                _(
                    "Mění se jen nové commity v tomto repu. Stará historie zůstává – přepis "
                    "(git filter-repo --mailmap) repo-doctor nedělá, viz repo-doctor explain email-exposure."
                ),
                _(
                    "Na hostingu zapni skrývání e-mailu (GitHub: Settings → Emails → Keep my email "
                    "addresses private)."
                ),
            ],
        )
