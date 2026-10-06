#!/usr/bin/env python3
"""
Wbudowuje ustawienia Sertum w źródła RustDesk przed kompilacją.

Użycie (w katalogu głównym repozytorium RustDesk):
    python3 sertum/sertum_configure.py --host pomoc.sertum.pl --key "<klucz z id_ed25519.pub>"
    python3 sertum/sertum_configure.py --host ... --key ... --branding sertum/branding
    python3 sertum/sertum_configure.py --host ... --key ... --variant technik

Warianty: pomoc (domyślny) – SertumPomoc.exe dla klientów, tylko połączenia przychodzące;
pomoc32 – SertumPomoc32.exe, to samo dla 32-bitowego Windows (interfejs Sciter);
technik – SertumTechnik.exe dla techników, pełny (łączenie i udostępnianie), niepodpisywany.

Co zmienia:
  * libs/hbb_common/src/config.rs – domyślny serwer ID/relay i klucz publiczny,
    więc klient od razu łączy się z serwerem Sertum, bez żadnej konfiguracji;
    oraz HARD_SETTINGS: tylko połączenia przychodzące, instalacja wyłączona.
  * src/common.rs – using_public_server() uwzględnia wbudowany serwer, więc klient
    nie pokazuje linku „skorzystaj z własnego serwera” (reklama serwerów RustDesk).
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
COMMON_RS = Path("src/common.rs")
# Na stałe wbudowane ustawienia klienta (config::HARD_SETTINGS)
HARD_SETTINGS = {
    "conn-type": "incoming",         # SertumPomoc.exe tylko udostępnia ekran, nie łączy się dalej
    "disable-installation": "Y",     # bez przycisku „Zainstaluj” – wyłącznie praca doraźna
}
RUNNER_RC = Path("flutter/windows/runner/Runner.rc")
# Cargo.toml -> właściwości pliku (OriginalFilename; None = bez zmian)
CARGO_WINRES = {
    Path("Cargo.toml"): None,                              # librustdesk.dll
    Path("libs/portable/Cargo.toml"): "{exe}",             # zewnętrzny plik .exe
}

# Warianty klienta:
#   pomoc   – publiczny, podpisywany plik dla klientów: tylko udostępnia ekran
#   technik – wewnętrzny, niepodpisywany plik techników: łączy się i udostępnia
# Teksty w oknie klienta (klucze tłumaczeń RustDesk: src/lang/<język>.rs)
CLIENT_TEXTS = {
    "pl": {
        "Your Desktop": "Pomoc Sertum",
        "desk_tip": "Przekaż poniższe ID i hasło jednorazowe pracownikowi Sertum "
                    "celem uzyskania pomocy zdalnej.",
    },
    "en": {
        "Your Desktop": "Sertum Support",
        "desk_tip": "Give the ID and one-time password below to a Sertum employee "
                    "to get remote support.",
    },
}

# app_name: tytuł okna i nazwa w komunikatach (RustDesk podmienia w nich „RustDesk”);
# zmiana nazwy wyłącza też sprawdzanie aktualizacji na rustdesk.com. Różne nazwy
# = osobna konfiguracja, więc SertumPomoc i SertumTechnik nie kolidują ze sobą.
VARIANTS = {
    "pomoc": {
        "product": "Sertum Pomoc Zdalna",
        "exe": "SertumPomoc.exe",
        "app_name": "Sertum",
        "hard_settings": HARD_SETTINGS,
        "texts": CLIENT_TEXTS,
    },
    "pomoc32": {                     # 32-bit Windows (interfejs Sciter zamiast Fluttera)
        "product": "Sertum Pomoc Zdalna",
        "exe": "SertumPomoc32.exe",
        "app_name": "Sertum",
        "hard_settings": HARD_SETTINGS,
        "texts": CLIENT_TEXTS,
    },
    "technik": {
        "product": "Sertum Technik",
        "exe": "SertumTechnik.exe",
        "app_name": "SertumTechnik",
        "hard_settings": {},
        "texts": {},
    },
}

ICON_TARGETS = [
    Path("res/icon.ico"),                                   # ikona samorozpakowującego .exe
    Path("res/tray-icon.ico"),                              # ikona w zasobniku
    Path("flutter/windows/runner/resources/app_icon.ico"),  # ikona okna / rustdesk.exe
    Path("flutter/assets/icon.ico"),                        # skróty
]
LOGO_TARGET = Path("flutter/assets/logo.png")
ICON_PNG_TARGET = Path("flutter/assets/icon.png")
UI_RS = Path("src/ui.rs")                                  # ikona okna w interfejsie Sciter
LANG_DIR = Path("src/lang")                                # tłumaczenia (pl.rs, en.rs, ...)
TABBAR_DART = Path("flutter/lib/desktop/widgets/tabbar_widget.dart")   # belka okna Fluttera
TAB_PAGE_DART = Path("flutter/lib/desktop/pages/desktop_tab_page.dart")
INDEX_TIS = Path("src/ui/index.tis")                       # okno główne interfejsu Sciter
SCITER_INCOMING_WIDTH = 240                                # upstream: 180 px


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


def patch_public_server_check() -> None:
    # Upstream uznaje klienta za korzystającego z publicznych serwerów RustDesk, gdy
    # opcja custom-rendezvous-server jest pusta – nawet przy wbudowanym własnym serwerze.
    text = COMMON_RS.read_text(encoding="utf-8")
    marker = "is_public(hbb_common::config::RENDEZVOUS_SERVERS[0])"
    if marker not in text:
        text = replace_once(
            text,
            r'^(pub fn using_public_server\(\) -> bool \{\n'
            r'\s*crate::get_custom_rendezvous_server\(get_option\("custom-rendezvous-server"\)\)'
            r'\.is_empty\(\))\n\}',
            r'\1\n        && ' + marker + r'\n}',
            f"using_public_server() w {COMMON_RS}",
        )
        COMMON_RS.write_text(text, encoding="utf-8")
    print("  serwer publiczny: rozpoznaje wbudowany serwer (bez reklamy serwerów RustDesk)")


def patch_app_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9]+", name):
        fail(f"nazwa aplikacji może zawierać tylko litery i cyfry: {name!r}")
    text = CONFIG_RS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'^(\s*pub static ref APP_NAME: RwLock<String> = RwLock::new\(")[^"]*("\.to_owned\(\)\);)$',
        lambda m: m.group(1) + name + m.group(2),
        "APP_NAME",
    )
    CONFIG_RS.write_text(text, encoding="utf-8")
    print(f"  nazwa aplikacji (tytuł okna): {name}")


def patch_flutter_title() -> None:
    # Belka okna Fluttera (x64) ma napis "RustDesk" wpisany na sztywno i domyślnie ukryty
    # (showTitle: false) – pokazujemy w oknie głównym nazwę aplikacji (APP_NAME).
    text = TABBAR_DART.read_text(encoding="utf-8")
    if "bind.mainGetAppNameSync()," not in text:
        text = replace_once(
            text,
            r'child: const Text\(\n(\s*)"RustDesk",',
            lambda m: "child: Text(\n" + m.group(1) + "bind.mainGetAppNameSync(),",
            f"napis tytułu w {TABBAR_DART}",
        )
        TABBAR_DART.write_text(text, encoding="utf-8")
    text = TAB_PAGE_DART.read_text(encoding="utf-8")
    if "showTitle: true, // Sertum" not in text:
        text = replace_once(
            text,
            r'(body: DesktopTab\(\n(\s*))controller: tabController,',
            lambda m: m.group(1) + "showTitle: true, // Sertum\n" + m.group(2)
                      + "controller: tabController,",
            f"DesktopTab w {TAB_PAGE_DART}",
        )
        TAB_PAGE_DART.write_text(text, encoding="utf-8")
    print("  tytuł na belce okna (Flutter): nazwa aplikacji")


def patch_sciter_width(width: int) -> None:
    # Okno Sciter (x86) w trybie „tylko przychodzące” ma 180 px – za wąsko na tytuł
    # i nagłówek (ma stałą wysokość jednej linii, dłuższy tekst nachodzi na opis).
    text = INDEX_TIS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'^const incoming_only_width = \d+;$',
        f"const incoming_only_width = {width};",
        f"incoming_only_width w {INDEX_TIS}",
    )
    INDEX_TIS.write_text(text, encoding="utf-8")
    print(f"  szerokość okna Sciter: {width} px")


def rust_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def patch_texts(texts: dict) -> None:
    for lang, entries in texts.items():
        path = LANG_DIR / f"{lang}.rs"
        text = path.read_text(encoding="utf-8")
        for key, value in entries.items():
            entry = f'("{rust_str(key)}", "{rust_str(value)}"),'
            pattern = r'^(\s*)\("' + re.escape(key) + r'", ".*"\),$'
            if re.search(pattern, text, re.MULTILINE):
                text = replace_once(text, pattern, lambda m: m.group(1) + entry,
                                    f"{key} w {path}")
            else:
                # klucz bez tłumaczenia w tym języku – dopisujemy na początku tabeli
                text = replace_once(
                    text,
                    r'^(pub static ref T: std::collections::HashMap<&\'static str, &\'static str> =\n\s*\[\n)',
                    lambda m: m.group(1) + "        " + entry + "\n",
                    f"tabela tłumaczeń w {path}",
                )
        path.write_text(text, encoding="utf-8")
    if texts:
        print(f"  teksty w oknie: {', '.join(texts)}")


def patch_hard_settings(settings: dict) -> None:
    # Ustawienia, których użytkownik nie może zmienić (te same klucze, które w RustDesk
    # ustawia podpisany custom.txt), np. tylko połączenia przychodzące i brak instalacji.
    if settings:
        value = "RwLock::new(HashMap::from([" + ", ".join(
            f'("{k}".to_owned(), "{v}".to_owned())' for k, v in settings.items()
        ) + "]))"
    else:
        value = "Default::default()"
    text = CONFIG_RS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'^(\s*pub static ref HARD_SETTINGS: RwLock<HashMap<String, String>> = ).*;$',
        lambda m: m.group(1) + value + ";",
        "HARD_SETTINGS",
    )
    CONFIG_RS.write_text(text, encoding="utf-8")
    if settings:
        print("  tryb: " + ", ".join(f"{k}={v}" for k, v in settings.items()))
    else:
        print("  tryb: pełny (łączenie i udostępnianie)")


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
        patch_sciter_icon(icon_png)
        print(f"  ikona w aplikacji: {icon_png}")
    else:
        print(f"  ikona w aplikacji: brak {icon_png}, zostaje domyślna")


def patch_sciter_icon(icon_png: Path) -> None:
    # Interfejs Sciter (wariant 32-bit) bierze ikonę okna z obrazka wbudowanego
    # w get_icon() w src/ui.rs (128x128, wariant inny niż macOS).
    data = base64.b64encode(icon_png.read_bytes()).decode()
    text = UI_RS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'(#\[cfg\(not\(target_os = "macos"\)\)\] // 128x128 no padding\s*\{\s*)'
        r'"data:image/png;base64,[A-Za-z0-9+/=]*"',
        lambda m: m.group(1) + f'"data:image/png;base64,{data}"',
        f"get_icon() w {UI_RS}",
    )
    UI_RS.write_text(text, encoding="utf-8")


def main() -> None:
    # Konsola Windows (cp1252) nie wypisze polskich znaków – wymuszamy UTF-8.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", required=True, help="adres serwera, np. pomoc.sertum.pl")
    p.add_argument("--key", required=True, help="zawartość data/id_ed25519.pub z serwera")
    p.add_argument("--variant", choices=VARIANTS, default="pomoc",
                   help="pomoc = plik dla klientów (tylko przychodzące), "
                        "technik = plik techników (pełny)")
    p.add_argument("--product", help="nazwa produktu (domyślnie wg wariantu)")
    p.add_argument("--company", default="Sertum Sp. z o.o.")
    p.add_argument("--branding", type=Path, help="katalog z icon.ico i/lub logo.png")
    args = p.parse_args()
    variant = VARIANTS[args.variant]
    product = args.product or variant["product"]

    for f in (CONFIG_RS, COMMON_RS, RUNNER_RC, UI_RS, TABBAR_DART, TAB_PAGE_DART, INDEX_TIS,
              *CARGO_WINRES):
        if not f.is_file():
            fail(f"nie znaleziono {f} – uruchom skrypt w katalogu głównym repo RustDesk "
                 f"(z pobranymi submodułami)")

    print(f"Konfiguracja klienta Sertum (wariant: {args.variant}):")
    patch_config(validate_host(args.host), validate_key(args.key))
    patch_public_server_check()
    patch_hard_settings(variant["hard_settings"])
    patch_app_name(variant["app_name"])
    patch_flutter_title()
    patch_sciter_width(SCITER_INCOMING_WIDTH)
    patch_texts(variant["texts"])
    patch_runner_rc(product, args.company)
    for cargo, original_filename in CARGO_WINRES.items():
        if original_filename:
            original_filename = original_filename.format(exe=variant["exe"])
        patch_cargo_winres(cargo, product, args.company, original_filename)
    if args.branding:
        if not args.branding.is_dir():
            fail(f"brak katalogu {args.branding}")
        apply_branding(args.branding)
    print("Gotowe.")


if __name__ == "__main__":
    main()
