#!/usr/bin/env bash
# Sestaví samostatnou aplikaci (vlastní Python + všechny knihovny) do dist/repo-doctor/.
#
# Volání (z kořene repa, v prostředí se závislostmi a skupinou `build`):
#   uv sync --locked --no-dev --group build && uv run packaging/build.sh
#
# Výsledek je složka (PyInstaller onedir) se spustitelným souborem dist/repo-doctor/repo-doctor.
# Značku způsobu instalace (install-kind) do ní přidávají až balíčky – viz packaging/package.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf build/pyinstaller dist/repo-doctor
python -m PyInstaller --noconfirm --clean --onedir --name repo-doctor \
    --distpath dist --workpath build/pyinstaller --specpath build/pyinstaller \
    --collect-submodules repo_doctor --collect-data repo_doctor \
    --add-data "$PWD/docs/checks:repo_doctor/_checkdocs" \
    --collect-submodules textual --collect-data textual \
    --collect-submodules rich \
    --collect-submodules keyring.backends --copy-metadata keyring \
    --copy-metadata repo-doctor \
    --strip --exclude-module tkinter \
    packaging/pyinstaller/entry.py

# Rychlá kontrola, že sestavená aplikace startuje a má svá data.
app=dist/repo-doctor/repo-doctor
"$app" --version
"$app" checks >/dev/null
"$app" explain secrets-history >/dev/null
REPO_DOCTOR_LANG=en "$app" --help | grep -q "Audit and maintenance" \
    || { echo "✗ chybí anglický překlad (locale/en.po)" >&2; exit 1; }
echo "✓ Sestaveno: dist/repo-doctor ($(du -sh dist/repo-doctor | cut -f1))"
