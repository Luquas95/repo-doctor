"""Odeslání oprav z karty repa: push, PR/MR, merge na hostingu a lokální merge.

Každý krok je samostatná akce: v pozadí se připraví náhled (`publish.plan_*`, nic nemění),
ukáže se v potvrzovacím dialogu s výchozí volbou „Zrušit“ a teprve po potvrzení se provede
(`publish.apply_*`, který stav před zápisem ověří znovu).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.style import Style
from rich.text import Text
from textual.screen import Screen

from repo_doctor import czech, publish
from repo_doctor.config import Config
from repo_doctor.forges.base import PullRequestInfo
from repo_doctor.gitwrap import Git, GitError
from repo_doctor.i18n import _
from repo_doctor.tui.screens.dialogs import ConfirmDialog

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

Kind = Literal["push", "push_default", "pr", "merge", "merge_local"]
MAX_PREVIEW_LINES = 14


@dataclass
class Prepared:
    """Připravený krok: náhled pro dialog a funkce, která ho provede (běží ve vlákně)."""

    title: str
    body: Text
    confirm_label: str
    done_title: str
    run: Callable[[], str]  # vrací zprávu o výsledku


class Blocked(Exception):
    """Krok je připravený, ale něco mu brání (např. běžící CI) – ukáže se jako upozornění."""


class PublishFlow:
    def __init__(self, screen: Screen[None], path: str) -> None:
        self.screen = screen
        self.path = path

    @property
    def rd(self) -> RepoDoctorApp:
        return self.screen.app  # type: ignore[return-value]

    # ------------------------------------------------------------------ spuštění
    def start(self, kind: Kind) -> None:
        self.screen.run_worker(
            partial(self._prepare, kind), thread=True, exclusive=True, group="publish"
        )

    def _call(self, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        self.screen.app.call_from_thread(partial(fn, *args, **kwargs))

    def _prepare(self, kind: Kind) -> None:
        config, git = self.rd.config, Git(Path(self.path))
        try:
            prepared = {
                "push": partial(self._push, git, config, default=False),
                "push_default": partial(self._push, git, config, default=True),
                "pr": partial(self._pr, git, config),
                "merge": partial(self._merge, git, config),
                "merge_local": partial(self._merge_local, git, config),
            }[kind]()
        except Blocked as err:
            self._call(
                self.screen.notify,
                str(err),
                title=_("Merge zatím nejde"),
                severity="warning",
                timeout=15,
            )
            return
        except publish.PublishRefused as err:
            self._call(
                self.screen.notify,
                str(err),
                title=_("Odeslání nejde"),
                severity="warning",
                timeout=15,
            )
            return
        except (GitError, OSError) as err:
            self._call(self.screen.notify, str(err), title=_("Odeslání selhalo"), severity="error")
            return
        self._call(self._confirm, prepared)

    def _confirm(self, prepared: Prepared) -> None:
        def decided(ok: bool | None) -> None:
            if ok:
                self.screen.run_worker(
                    partial(self._run, prepared), thread=True, exclusive=True, group="publish-run"
                )
            else:
                self.screen.notify(_("Zrušeno – nic se nezměnilo."))

        self.screen.app.push_screen(
            ConfirmDialog(prepared.title, prepared.body, confirm_label=prepared.confirm_label),
            decided,
        )

    def _run(self, prepared: Prepared) -> None:
        try:
            message = prepared.run()
        except publish.PublishRefused as err:
            self._call(
                self.screen.notify, str(err), title=_("Odeslání se nepovedlo"), severity="error",
                timeout=20,
            )  # fmt: skip
            return
        except (GitError, OSError) as err:
            self._call(self.screen.notify, str(err), title=_("Odeslání selhalo"), severity="error")
            return
        self._call(self.screen.notify, message, title=prepared.done_title, timeout=20)

    # ------------------------------------------------------------------ kroky
    def _text(self, *parts: str) -> Text:
        return Text("\n".join(parts), style=Style(color=self.rd.palette.text))

    def _commit_lines(self, commits: list[publish.CommitInfo]) -> str:
        lines = [f"  {c.short} {c.subject}" for c in commits[:MAX_PREVIEW_LINES]]
        if len(commits) > MAX_PREVIEW_LINES:
            lines.append("  " + czech.more(len(commits) - MAX_PREVIEW_LINES))
        return "\n".join(lines)

    def _hosting[T](
        self, git: Git, config: Config, work: Callable[[publish.Hosting], Awaitable[T]]
    ) -> T:
        transport = self.rd.forge_transport
        return asyncio.run(publish.with_hosting(git, config, work, transport=transport))

    def _push(self, git: Git, config: Config, *, default: bool) -> Prepared:
        plan = publish.plan_push(git, config, default=default)
        body = self._text(
            "",
            _("Pošle větev {branch} na {remote} ({url}), {commits}:").format(
                branch=plan.branch,
                remote=plan.remote,
                url=plan.remote_url,
                commits=czech.commits(len(plan.commits)),
            ),
            self._commit_lines(plan.commits),
            "",
            _("Jen tahle jedna větev, nikdy force ani tagy. Nové commity jsou zkontrolované na tajemství."),
        )  # fmt: skip

        def run() -> str:
            publish.apply_push(git, plan, config)
            return _("Odesláno: {branch} → {remote}.").format(
                branch=plan.branch, remote=plan.remote
            )

        return Prepared(_("Poslat větev (push)"), body, _("Poslat"), _("Push hotový"), run)

    def _pr(self, git: Git, config: Config) -> Prepared:
        async def plan_it(hosting: publish.Hosting) -> publish.PRPlan:
            return await publish.plan_pr(git, hosting, config)

        plan = self._hosting(git, config, plan_it)
        preview = plan.body.splitlines()
        if len(preview) > MAX_PREVIEW_LINES:
            preview = [*preview[:MAX_PREVIEW_LINES], "…"]
        body = self._text(
            "",
            _("PR na {forge} ({owner_path}): {head} → {base}").format(
                forge=plan.forge, owner_path=plan.owner_path, head=plan.branch, base=plan.base
            ),
            "",
            plan.title,
            "",
            *preview,
        )

        def run() -> str:
            async def apply_it(hosting: publish.Hosting) -> PullRequestInfo:
                return await publish.apply_pr(git, hosting, config, plan)

            pr = self._hosting(git, config, apply_it)
            return _("Vytvořen PR #{number}: {url}").format(number=pr.number, url=pr.url)

        return Prepared(_("Vytvořit PR/MR"), body, _("Vytvořit"), _("PR vytvořen"), run)

    def _merge(self, git: Git, config: Config) -> Prepared:
        async def plan_it(hosting: publish.Hosting) -> publish.MergePlan:
            return await publish.plan_merge(git, hosting, config)

        plan = self._hosting(git, config, plan_it)
        head = _("PR #{number} {title}\n{url}\nCI: {ci} · metoda: {method}").format(
            number=plan.pr.number,
            title=plan.pr.title,
            url=plan.pr.url,
            ci=plan.ci.state,
            method=plan.method or _("výchozí hostingu"),
        )
        if not plan.ready:
            raise Blocked(head + "\n" + "\n".join(f"✗ {b}" for b in plan.blockers))
        body = self._text(
            "",
            head,
            "",
            _(
                "CI je zelená a hosting hlásí, že jde mergnout. Merge na hostingu nejde vrátit zpět."
            ),
        )

        def run() -> str:
            async def apply_it(hosting: publish.Hosting) -> PullRequestInfo:
                return await publish.apply_merge(git, hosting, config, plan)

            done = self._hosting(git, config, apply_it)
            if done.state != "merged":
                return _("Hosting merge přijal, PR zatím není mergnutý: {url}").format(url=done.url)
            return _("PR #{number} mergnut. Změny stáhneš v Synchronizaci ({key}).").format(
                number=done.number, key=self.rd.key("screen_sync")
            )

        return Prepared(_("Mergnout PR"), body, _("Mergnout"), _("Merge hotový"), run)

    def _merge_local(self, git: Git, config: Config) -> Prepared:
        plan = publish.plan_merge_local(git, config)
        tree = (
            _("Změní se {files} v pracovním stromě.").format(files=czech.files(len(plan.files)))
            if plan.checked_out
            else _("Pracovní strom se nezmění (větev {target} není checkoutnutá).").format(
                target=plan.target
            )
        )
        body = self._text(
            "",
            _("Posune {target} na {branch} (jen fast-forward, bez merge commitu), {commits}:").format(
                target=plan.target, branch=plan.branch, commits=czech.commits(len(plan.commits))
            ),
            self._commit_lines(plan.commits),
            "",
            tree + " " + _("Nic se nepushne."),
        )  # fmt: skip

        def run() -> str:
            publish.apply_merge_local(git, config, plan)
            return _("{target} posunuta na {branch}. Chceš ji poslat? Klávesa {key}.").format(
                target=plan.target, branch=plan.branch, key=self.rd.key("publish_push_default")
            )

        return Prepared(_("Lokální merge"), body, _("Mergnout"), _("Merge hotový"), run)
