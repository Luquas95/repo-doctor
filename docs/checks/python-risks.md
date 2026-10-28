# python-risks – Rizikové vzory v Pythonu

**Kategorie:** Bezpečnost · **Severity:** MED (některá pravidla LOW) · **Automatická oprava:** ne

## Co kontrola hledá

Parsuje `*.py` soubory (`ast.parse`, nic se nespouští ani neimportuje) a hledá: `eval()`/`exec()` s nekonstantním argumentem, `shell=True`, `os.system()`/`os.popen()`, `pickle.load(s)`/`marshal.load(s)`, `yaml.load()` bez `SafeLoader`, `verify=False`, `app.run(debug=True)` (všechno MED) a holé `except:`, `breakpoint()`/`pdb.set_trace()`, `tempfile.mktemp()` a `DEBUG = True` v souboru `settings*.py` (LOW). Testy (`tests/`, `test_*.py`) a vendorovaný kód (`node_modules`, `vendor`, `.venv`) se přeskakují. Jeden nález na soubor a pravidlo, s prvním řádkem a počtem výskytů; nad 50 nálezů se přidá nález „Nekompletní sken“.

## Proč to vadí

Tyhle vzory jsou nejčastější cesta k vstřikování příkazů, spuštění cizího kódu při načtení dat nebo odposlechu přes vypnuté TLS. Ladicí zbytky a holé `except:` schovají chyby, které pak nikdo nevidí.

## Postup

1. Nahraď `shell=True` seznamem argumentů: `subprocess.run(["ls", path], check=True)`.
2. Místo `eval`/`pickle`/`yaml.load` použij `ast.literal_eval`, JSON a `yaml.safe_load`.
3. Je-li použití záměrné a vstup důvěryhodný, dej nález do allowlistu a přidej komentář proč.
