#!/usr/bin/env python3
"""
Wbudowuje ustawienia Sertum w źródła RustDesk przed kompilacją.

Użycie (w katalogu głównym repozytorium RustDesk):
    python3 sertum/sertum_configure.py --host pomoc.sertum.pl --key "<klucz z id_ed25519.pub>"
    python3 sertum/sertum_configure.py --host ... --key ... --branding sertum/branding

Co zmienia:
  * libs/hbb_common/src/config.rs – domyślny serwer ID/relay i klucz publiczny,
    więc klient od razu łączy się z serwerem Sertum, bez żadnej konfiguracji.
  * flutter/windows/runner/Runner.rc – nazwa produktu i firmy we właściwościach rustdesk.exe.
  * Cargo.toml, libs/portable/Cargo.toml – to samo dla librustdesk.dll
    i zewnętrznego SertumPomoc.exe (sekcja [package.metadata.winres]).
  * (opcjonalnie) ikony i logo z katalogu --branding:
        icon.ico  -> ikona pliku .exe, okna, zasobnika i skrótów
        icon.png  -> ikona w pasku kart i oknie połączenia (128x128 px)
        logo.png  -> logo w oknie programu (maks. 300x60, przezroczyste tło)

Skrypt jest idempotentny: można go uruchomić wielokrotnie.
"""
import argparse
import base64
import re
import shutil
import sys
from pathlib import Path

CONFIG_RS = Path("libs/hbb_common/src/config.rs")
RUNNER_RC = Path("flutter/windows/runner/Runner.rc")
# Cargo.toml -> właściwości pliku (OriginalFilename; None = bez zmian)
CARGO_WINRES = {
    Path("Cargo.toml"): None,                              # librustdesk.dll
    Path("libs/portable/Cargo.toml"): "SertumPomoc.exe",   # zewnętrzny plik dla klienta
}

ICON_TARGETS = [
    Path("res/icon.ico"),                                   # ikona samorozpakowującego .exe
    Path("res/tray-icon.ico"),                              # ikona w zasobniku
    Path("flutter/windows/runner/resources/app_icon.ico"),  # ikona okna / rustdesk.exe
    Path("flutter/assets/icon.ico"),                        # skróty
]
LOGO_TARGET = Path("flutter/assets/logo.png")
ICON_PNG_TARGET = Path("flutter/assets/icon.png")


def fail(msg: str) -> None:
    print(f"BŁĄD: {msg}", file=sys.stderr)
    sys.exit(1)


def validate_key(key: str) -> str:
    key = key.strip()
    try:
        raw = base64.b64decode(key, validate=True)
    except Exception:
        fail("klucz nie jest poprawnym base64 – skopiuj całą zawartość id_ed25519.pub")
    if len(raw) != 32:
        fail(f"klucz ma {len(raw)} bajtów, oczekiwano 32 (Ed25519)")
    return key


def validate_host(host: str) -> str:
    host = host.strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?", host):
        fail(f"niepoprawny host: {host!r}")
    return host


def replace_once(text: str, pattern: str, repl: str, what: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n != 1:
        fail(f"nie znaleziono w źródłach: {what} – zmieniła się struktura kodu RustDesk, "
             f"sprawdź {CONFIG_RS}")
    return new


def patch_config(host: str, key: str) -> None:
    text = CONFIG_RS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'^pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[.*?\];',
        f'pub const RENDEZVOUS_SERVERS: &[&str] = &["{host}"];',
        "RENDEZVOUS_SERVERS",
    )
    text = replace_once(
        text,
        r'^pub const RS_PUB_KEY: &str = ".*?";',
        f'pub const RS_PUB_KEY: &str = "{key}";',
        "RS_PUB_KEY",
    )
    CONFIG_RS.write_text(text, encoding="utf-8")
    print(f"  serwer: {host}")
    print(f"  klucz:  {key}")


def rc_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '""')


def patch_runner_rc(product: str, company: str) -> None:
    text = RUNNER_RC.read_text(encoding="utf-8")
    values = {
        "CompanyName": company,
        "FileDescription": product,
        "ProductName": product,
        "LegalCopyright": f"{company} – oparte na RustDesk (AGPL-3.0)",
    }
    for name, value in values.items():
        text = replace_once(
            text,
            rf'^(\s*VALUE "{name}", )".*?"( "\\0")',
            rf'\1"{rc_escape(value)}"\2',
            f"{name} w Runner.rc",
        )
    RUNNER_RC.write_text(text, encoding="utf-8")
    print(f"  właściwości pliku: {product} / {company}")


def toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def patch_cargo_winres(path: Path, product: str, company: str,
                       original_filename) -> None:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^\[package\.metadata\.winres\]\n(?:[^\[\n].*\n|\n)*", text, re.MULTILINE)
    if not m:
        fail(f"nie znaleziono [package.metadata.winres] w {path} – "
             f"zmieniła się struktura kodu RustDesk")
    values = {
        "CompanyName": company,
        "FileDescription": product,
        "ProductName": product,
        "LegalCopyright": f"{company} – oparte na RustDesk (AGPL-3.0)",
    }
    if original_filename:
        values["OriginalFilename"] = original_filename
    kept = [l for l in m.group(0).splitlines()[1:]
            if l.strip() and l.split("=")[0].strip() not in values]
    kept += [f'{k} = "{toml_escape(v)}"' for k, v in values.items()]
    section = "[package.metadata.winres]\n" + "\n".join(kept) + "\n\n"
    path.write_text(text[:m.start()] + section + text[m.end():], encoding="utf-8")
    print(f"  właściwości pliku: {path}")


def apply_branding(branding: Path) -> None:
    icon = branding / "icon.ico"
    logo = branding / "logo.png"
    icon_png = branding / "icon.png"
    if icon.is_file():
        for target in ICON_TARGETS:
            shutil.copyfile(icon, target)
        print(f"  ikona: {icon} -> {len(ICON_TARGETS)} miejsc")
    else:
        print(f"  ikona: brak {icon}, zostaje domyślna")
    if logo.is_file():
        shutil.copyfile(logo, LOGO_TARGET)
        print(f"  logo:  {logo}")
    else:
        print(f"  logo:  brak {logo}, bez logo w oknie")
    if icon_png.is_file():
        shutil.copyfile(icon_png, ICON_PNG_TARGET)
        print(f"  ikona w aplikacji: {icon_png}")
    else:
        print(f"  ikona w aplikacji: brak {icon_png}, zostaje domyślna")


def main() -> None:
    # Konsola Windows (cp1252) nie wypisze polskich znaków – wymuszamy UTF-8.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", required=True, help="adres serwera, np. pomoc.sertum.pl")
    p.add_argument("--key", required=True, help="zawartość data/id_ed25519.pub z serwera")
    p.add_argument("--product", default="Sertum Pomoc Zdalna")
    p.add_argument("--company", default="Sertum Sp. z o.o.")
    p.add_argument("--branding", type=Path, help="katalog z icon.ico i/lub logo.png")
    args = p.parse_args()

    for f in (CONFIG_RS, RUNNER_RC, *CARGO_WINRES):
        if not f.is_file():
            fail(f"nie znaleziono {f} – uruchom skrypt w katalogu głównym repo RustDesk "
                 f"(z pobranymi submodułami)")

    print("Konfiguracja klienta Sertum:")
    patch_config(validate_host(args.host), validate_key(args.key))
    patch_runner_rc(args.product, args.company)
    for cargo, original_filename in CARGO_WINRES.items():
        patch_cargo_winres(cargo, args.product, args.company, original_filename)
    if args.branding:
        if not args.branding.is_dir():
            fail(f"brak katalogu {args.branding}")
        apply_branding(args.branding)
    print("Gotowe.")


if __name__ == "__main__":
    main()
