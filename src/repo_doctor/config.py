"""Konfigurace: pydantic modely + načítání/ukládání přes tomlkit (zachová komentáře)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from tomlkit.items import AoT, Table
from tomlkit.toml_document import TOMLDocument

from repo_doctor import paths
from repo_doctor.models import Severity

ForgeType = Literal["github", "gitea", "forgejo", "gitlab"]
TokenSource = Literal["keyring", "env", "cmd", "none"]
LicenseId = Literal["MIT", "ISC", "BSD-2-Clause", "Unlicense"]

DEFAULT_FORGE_URLS: dict[str, str] = {
    "github": "https://api.github.com",
    "gitlab": "https://gitlab.com",
}


class ConfigError(Exception):
    """Neplatná konfigurace – zpráva je určená přímo uživateli."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RootConfig(_Model):
    path: str
    depth: int = Field(default=3, ge=0, le=12)
    exclude: list[str] = Field(default_factory=list)
    enabled: bool = True
    follow_symlinks: bool = False

    @field_validator("path")
    @classmethod
    def _path_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("cesta nesmí být prázdná")
        return value.strip()

    @property
    def expanded(self) -> Path:
        return paths.expand_path(self.path)


class ForgeConfig(_Model):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    type: ForgeType
    url: str | None = None
    user: str | None = None
    org: str | None = None
    token_source: TokenSource | None = None
    token_env: str | None = None
    token_cmd: str | None = None
    verify_tls: bool = True
    ca_bundle: str | None = None
    clone_protocol: Literal["ssh", "https"] = "ssh"
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _no_plaintext_token(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("token", "password", "api_key", "secret"):
                if key in data:
                    raise ValueError(
                        f"klíč `{key}` není povolený: token nepatří do config.toml jako prostý text. "
                        'Použij token_env, token_cmd nebo token_source = "keyring".'
                    )
        return data

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL instance musí začínat http:// nebo https://")
        if "@" in value.split("//", 1)[1].split("/", 1)[0]:
            raise ValueError("URL nesmí obsahovat přihlašovací údaje")
        return value

    @model_validator(mode="after")
    def _source(self) -> ForgeConfig:
        if self.token_source is None:
            if self.token_env:
                self.token_source = "env"
            elif self.token_cmd:
                self.token_source = "cmd"
            else:
                self.token_source = "none"
        if self.token_source == "env" and not self.token_env:
            raise ValueError('token_source = "env" vyžaduje token_env (název proměnné)')
        if self.token_source == "cmd" and not self.token_cmd:
            raise ValueError('token_source = "cmd" vyžaduje token_cmd')
        if self.type in ("gitea", "forgejo") and not self.url:
            raise ValueError(f"hosting typu {self.type} vyžaduje url instance")
        return self

    @property
    def base_url(self) -> str:
        return self.url or DEFAULT_FORGE_URLS.get(self.type, "")


class ChecksConfig(_Model):
    disabled: list[str] = Field(default_factory=list)
    fail_on: Severity = Severity.HIGH


class LimitsConfig(_Model):
    large_file_mb: float = Field(default=5.0, gt=0, le=10_000)
    binary_file_kb: int = Field(default=1024, gt=0)
    stale_branch_days: int = Field(default=90, ge=1)
    stash_days: int = Field(default=30, ge=1)
    no_pulse_days: int = Field(default=90, ge=1)
    stale_pr_days: int = Field(default=30, ge=1)
    history_timeout_s: float = Field(default=60.0, gt=0)
    git_timeout_s: float = Field(default=30.0, gt=0)
    history_size: int = Field(default=30, ge=1, le=1000)
    http_cache_minutes: int = Field(default=15, ge=0)
    registry_cache_hours: int = Field(default=24, ge=0)
    max_file_kb: int = Field(default=1024, gt=0)  # větší soubory skener tajemství přeskočí


class AllowEntry(_Model):
    hash: str = Field(pattern=r"^[0-9a-f]{16}$")
    reason: str = Field(min_length=1)
    check: str | None = None
    repo: str | None = None


class UIConfig(_Model):
    theme: Literal["dark", "light"] = "dark"
    editor: str | None = None
    group_by: Literal["triage", "root", "forge"] = "triage"
    show_sidebar: bool = True


class Config(_Model):
    roots: list[RootConfig] = Field(default_factory=list)
    forges: list[ForgeConfig] = Field(default_factory=list)
    keys: dict[str, str] = Field(default_factory=dict)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    allowlist: list[AllowEntry] = Field(default_factory=list)
    ignore_paths: list[str] = Field(default_factory=list)
    ignore_repos: list[str] = Field(default_factory=list)
    license: LicenseId = "MIT"
    templates_dir: str | None = None
    # false = nepřipojovat `-o BatchMode=yes` (pro wrapper v core.sshCommand, který argumenty nepředá)
    ssh_batch_mode: bool = True
    ui: UIConfig = Field(default_factory=UIConfig)

    @model_validator(mode="after")
    def _unique_forges(self) -> Config:
        names = [f.name for f in self.forges]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicitní názvy hostingů: {', '.join(sorted(dupes))}")
        return self

    def forge(self, name: str) -> ForgeConfig | None:
        return next((f for f in self.forges if f.name == name), None)


class RepoOverrides(_Model):
    """`.repo-doctor.toml` v repozitáři – přepisuje globální nastavení pro dané repo."""

    checks: ChecksConfig | None = None
    limits: dict[str, Any] | None = None
    allowlist: list[AllowEntry] = Field(default_factory=list)
    ignore_paths: list[str] = Field(default_factory=list)
    license: LicenseId | None = None


def format_validation_error(err: ValidationError, source: str) -> str:
    lines = [f"Neplatná konfigurace ({source}):"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(kořen)"
        msg = str(e["msg"]).removeprefix("Value error, ")
        lines.append(f"  • {loc}: {msg}")
    return "\n".join(lines)


def parse_config(data: dict[str, Any], source: str = "config.toml") -> Config:
    try:
        return Config.model_validate(data)
    except ValidationError as err:
        raise ConfigError(format_validation_error(err, source)) from err


def load_repo_overrides(repo_path: Path) -> RepoOverrides | None:
    file = repo_path / ".repo-doctor.toml"
    if not file.is_file():
        return None
    try:
        data = tomlkit.parse(file.read_text("utf-8")).unwrap()
        return RepoOverrides.model_validate(data)
    except (ValidationError, tomlkit.exceptions.TOMLKitError, OSError) as err:
        raise ConfigError(f"Neplatný {file}: {err}") from err


def effective_for_repo(config: Config, overrides: RepoOverrides | None) -> Config:
    if overrides is None:
        return config
    update: dict[str, Any] = {}
    if overrides.checks is not None:
        update["checks"] = overrides.checks
    if overrides.limits:
        merged = config.limits.model_dump() | overrides.limits
        update["limits"] = LimitsConfig.model_validate(merged)
    if overrides.allowlist:
        update["allowlist"] = [*config.allowlist, *overrides.allowlist]
    if overrides.ignore_paths:
        update["ignore_paths"] = [*config.ignore_paths, *overrides.ignore_paths]
    if overrides.license:
        update["license"] = overrides.license
    return config.model_copy(update=update)


DEFAULT_HEADER = """\
# repo-doctor – konfigurace
# Dokumentace: README.md, sekce Konfigurace. Tokeny sem nepatří (použij token_env,
# token_cmd nebo token_source = "keyring").
"""


class ConfigStore:
    """Načítá a ukládá config.toml. Úpravy jdou přes tomlkit dokument, takže komentáře zůstanou."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.config_file()
        self.doc: TOMLDocument = tomlkit.document()
        self.config = Config()

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> Config:
        if not self.exists:
            self.doc = tomlkit.parse(DEFAULT_HEADER)
            self.config = Config()
            return self.config
        try:
            text = self.path.read_text("utf-8")
            self.doc = tomlkit.parse(text)
        except (OSError, tomlkit.exceptions.TOMLKitError) as err:
            raise ConfigError(f"Nelze načíst {self.path}: {err}") from err
        self.config = parse_config(self.doc.unwrap(), str(self.path))
        return self.config

    # -- zápis -------------------------------------------------------------
    def _validate_doc(self) -> Config:
        return parse_config(self.doc.unwrap(), str(self.path))

    def save(self) -> Config:
        """Zvaliduje dokument a atomicky ho zapíše. Při chybě se nic nezapíše."""
        config = self._validate_doc()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".toml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(tomlkit.dumps(self.doc))
            Path(tmp).replace(self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.config = config
        return config

    def _aot(self, key: str) -> AoT:
        if key not in self.doc:
            self.doc[key] = tomlkit.aot()
        item = self.doc[key]
        if not isinstance(item, AoT):
            raise ConfigError(f"`{key}` musí být pole tabulek ([[{key}]])")
        return item

    def _table(self, key: str) -> Table:
        if key not in self.doc:
            self.doc[key] = tomlkit.table()
        item = self.doc[key]
        if not isinstance(item, Table):
            raise ConfigError(f"`{key}` musí být tabulka ([{key}])")
        return item

    def _transaction(self, mutate: Any) -> Config:
        backup = tomlkit.dumps(self.doc)
        try:
            mutate()
            return self.save()
        except Exception:
            self.doc = tomlkit.parse(backup)
            raise

    @staticmethod
    def _clean(values: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in values.items() if v is not None}

    # roots
    def upsert_root(self, root: RootConfig, index: int | None = None) -> Config:
        def mutate() -> None:
            aot = self._aot("roots")
            data = self._clean(root.model_dump(exclude_defaults=True) | {"path": root.path})
            if index is None:
                aot.append(tomlkit.item(data))
            else:
                table = aot[index]
                for key in list(table.keys()):
                    if key not in data:
                        del table[key]
                for key, value in data.items():
                    table[key] = value

        return self._transaction(mutate)

    def remove_root(self, index: int) -> Config:
        def mutate() -> None:
            aot = self._aot("roots")
            del aot[index]
            if len(aot) == 0:
                del self.doc["roots"]

        return self._transaction(mutate)

    # forges
    def upsert_forge(self, forge: ForgeConfig, index: int | None = None) -> Config:
        def mutate() -> None:
            aot = self._aot("forges")
            data = self._clean(
                forge.model_dump(exclude_defaults=True) | {"name": forge.name, "type": forge.type}
            )
            if index is None:
                aot.append(tomlkit.item(data))
            else:
                table = aot[index]
                for key in list(table.keys()):
                    if key not in data:
                        del table[key]
                for key, value in data.items():
                    table[key] = value

        return self._transaction(mutate)

    def remove_forge(self, index: int) -> Config:
        def mutate() -> None:
            aot = self._aot("forges")
            del aot[index]
            if len(aot) == 0:
                del self.doc["forges"]

        return self._transaction(mutate)

    # obecné sekce
    def set_value(self, section: str, key: str, value: Any) -> Config:
        def mutate() -> None:
            table = self._table(section)
            if value is None:
                if key in table:
                    del table[key]
            else:
                table[key] = value

        return self._transaction(mutate)

    def set_top(self, key: str, value: Any) -> Config:
        def mutate() -> None:
            if value is None:
                if key in self.doc:
                    del self.doc[key]
            else:
                self.doc[key] = value

        return self._transaction(mutate)

    def add_allow(self, entry: AllowEntry) -> Config:
        def mutate() -> None:
            aot = self._aot("allowlist")
            aot.append(tomlkit.item(self._clean(entry.model_dump())))

        return self._transaction(mutate)

    def remove_allow(self, fingerprint: str) -> Config:
        def mutate() -> None:
            aot = self._aot("allowlist")
            for i in reversed(range(len(aot))):
                if aot[i].get("hash") == fingerprint:
                    del aot[i]
            if len(aot) == 0:
                del self.doc["allowlist"]

        return self._transaction(mutate)
