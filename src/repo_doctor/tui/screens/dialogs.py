"""Modální dialogy. Potvrzovací dialog má vždy výchozí volbu „Zrušit“."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ConfirmDialog(ModalScreen[bool]):
    """Ano/ne dialog. Esc i výchozí tlačítko = Zrušit."""

    BINDINGS = [
        Binding("escape", "cancel", "zrušit", key_display="esc"),
        Binding("left,h", "focus_previous", show=False),
        Binding("right,l", "focus_next", show=False),
    ]

    def __init__(
        self, title: str, body: str | Text, *, confirm_label: str = "Potvrdit", danger: bool = False
    ) -> None:
        super().__init__()
        self.title_text = title
        self.body = body
        self.confirm_label = confirm_label
        self.danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog", id="confirm") as box:
            box.border_title = f" {self.title_text} "
            yield Static(self.body, id="confirm-body")
            with Horizontal(classes="buttons"):
                yield Button("Zrušit", id="cancel")
                yield Button(
                    self.confirm_label, id="ok", variant="error" if self.danger else "primary"
                )
            yield Static("tab přepnout · enter potvrdit · esc zrušit", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputDialog(ModalScreen[str | None]):
    """Dotaz na text (např. důvod pro allowlist). Prázdná hodnota se nepřijme."""

    BINDINGS = [Binding("escape", "cancel", "zrušit", key_display="esc")]

    def __init__(
        self,
        title: str,
        prompt: str,
        *,
        placeholder: str = "",
        value: str = "",
        confirm_label: str = "Uložit",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.prompt = prompt
        self.placeholder = placeholder
        self.value = value
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as box:
            box.border_title = f" {self.title_text} "
            yield Label(self.prompt)
            yield Input(compact=True, value=self.value, placeholder=self.placeholder, id="value")
            yield Static("", classes="error", id="error")
            with Horizontal(classes="buttons"):
                yield Button("Zrušit", id="cancel")
                yield Button(self.confirm_label, id="ok", variant="primary")
            yield Static("enter uložit · esc zrušit", classes="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def _submit(self) -> None:
        value = self.query_one(Input).value.strip()
        if not value:
            self.query_one("#error", Static).update("Vyplň hodnotu.")
            return
        self.dismiss(value)

    @on(Input.Submitted)
    def _submitted(self) -> None:
        self._submit()

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self._submit()

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
