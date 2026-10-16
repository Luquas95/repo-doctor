#!/bin/sh
# Instalace repo-doctoru z tarballu (pro distribuce bez .deb/.rpm balíčku).
#
#   tar xzf repo-doctor-linux-x86_64.tar.gz && ./repo-doctor/install.sh
#
# Zkopíruje aplikaci do ~/.local/lib/repo-doctor a vytvoří příkaz ~/.local/bin/repo-doctor.
# Nic nespouští jako root. Aktualizace pak obstará `repo-doctor update`.
# Odinstalace: rm -rf ~/.local/lib/repo-doctor ~/.local/bin/repo-doctor
set -eu

src=$(cd "$(dirname "$0")" && pwd)
lib="$HOME/.local/lib/repo-doctor"
bin="$HOME/.local/bin"

if [ "$src" = "$lib" ]; then
    echo "repo-doctor už je nainstalovaný v $lib" >&2
    exit 1
fi
mkdir -p "$bin" "$(dirname "$lib")"
rm -rf "$lib.new"
cp -a "$src" "$lib.new"
rm -f "$lib.new/install.sh"
rm -rf "$lib"
mv "$lib.new" "$lib"
ln -sf "$lib/repo-doctor" "$bin/repo-doctor"

echo "✓ repo-doctor $("$lib/repo-doctor" --version | cut -d' ' -f2) nainstalován do $lib"
case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "Přidej $bin do PATH (např. do ~/.profile: export PATH=\"\$HOME/.local/bin:\$PATH\")." ;;
esac
