# Sertum Pomoc Zdalna – kontekst projektu

To jest fork RustDesk utrzymywany przez Sertum. Komunikacja z zespołem po polsku.

## Cel
Własny klient do **doraźnej** pomocy zdalnej klientom programu Sertum:
klient dzwoni na hotline, pobiera `SertumPomoc.exe` (bez instalacji), podaje ID i hasło,
technik się łączy. Stały/nienadzorowany dostęp do komputerów klientów NIE jest w zakresie.

`SertumPomoc.exe` działa w trybie **tylko przychodzącym** z wyłączoną instalacją
(`HARD_SETTINGS`: `conn-type=incoming`, `disable-installation=Y`) – publicznie dostępny
plik nie może służyć do łączenia się z innymi komputerami.

Część klientów ma 32-bitowy Windows (7 i 10). Flutter nie obsługuje x86, więc dla nich jest
`SertumPomoc32.exe` (wariant `pomoc32`): ten sam silnik i ustawienia, interfejs Sciter,
kompilacja według upstreamowego joba `build-for-windows-sciter` (i686, nightly-2023-10-13).
Podpis: 2 pliki (`rustdesk.exe`, `SertumPomoc32.exe`); `sciter.dll` to biblioteka zewnętrzna.

Technicy używają `SertumTechnik.exe` (wariant `technik` tego samego workflow: pełny klient,
bez instalacji, z wbudowanym serwerem i kluczem; **nigdy nie podpisywany i nie publikowany**)
albo oficjalnego klienta RustDesk ze wpisanym serwerem `pomoc.sertum.pl` i kluczem.
Plan po pilotażu: token techników sprawdzany przez zmodyfikowany hbbs/hbbr
(pole `token` w `PunchHoleRequest`/`RequestRelay`), żeby serwer obsługiwał tylko nasze
aplikacje techników.

## Architektura
- Serwer: RustDesk Server OSS (hbbs + hbbr) w Dockerze na VPS w UE,
  porty 21115/tcp, 21116/tcp+udp, 21117/tcp. Pliki w `server/` paczki startowej.
- Klient: ten fork. Zmiany względem upstream ograniczamy do katalogu `sertum/`
  i workflow `.github/workflows/sertum-windows.yml` – źródła upstream są modyfikowane
  dopiero w CI przez `sertum/sertum_configure.py` (nic z tego nie jest commitowane),
  dzięki czemu aktualizacja = `git rebase <nowy tag>` bez konfliktów.
  Uwaga: `libs/hbb_common` to submoduł, dlatego config.rs patchujemy w CI, a nie w repo.
- `sertum_configure.py` ustawia:
  - `RENDEZVOUS_SERVERS` i `RS_PUB_KEY` w `libs/hbb_common/src/config.rs`,
  - właściwości pliku: `flutter/windows/runner/Runner.rc` (rustdesk.exe) oraz
    `[package.metadata.winres]` w `Cargo.toml` (librustdesk.dll) i
    `libs/portable/Cargo.toml` (zewnętrzny SertumPomoc.exe),
  - ikony i logo z `sertum/branding/` (`icon.ico`, `icon.png`, `logo.png`; dla Sciter
    także ikonę w `get_icon()` w `src/ui.rs`),
  - `APP_NAME` (tytuł okna; `Sertum` dla klienta, `SertumTechnik` dla technika) – oficjalna
    ścieżka „custom client”: osobna konfiguracja, brak sprawdzania aktualizacji rustdesk.com,
  - teksty okna klienta w `src/lang/pl.rs` i `en.rs` (`Your Desktop`, `desk_tip`).
- `.gitignore` upstream ignoruje `*png` – pliki PNG w `sertum/branding/` dodawaj `git add -f`.
- Kompilacja: GitHub Actions, tylko Windows x64, wersja przenośna
  (`build.py --portable --flutter --skip-portable-pack`, potem `libs/portable/generate.py`).
  Kroki skopiowane z joba `build-for-windows-flutter` w upstream `flutter-build.yml` (1.5.0).
  Workflow upstream są w forku wyłączone; aktywne zostają tylko `sertum-windows.yml`
  i wywoływany przez niego `bridge.yml`.

## Podpisywanie
- Certyfikat: DigiCert Code Signing, klucz w DigiCert KeyLocker (Software Trust Manager),
  akcja `digicert/code-signing-software-trust-action@v1` w trybie simple-signing-mode.
- Mamy wykupioną **pulę podpisów** – każdy podpisany plik ją zużywa. Podpisujemy tylko
  `rustdesk.exe`, `librustdesk.dll` i finalny `SertumPomoc.exe` (3 na kompilację).
  Nie zmieniaj tego na podpisywanie całego katalogu bez uzgodnienia.
- Certyfikat w KeyLocker może mieć tylko **jednego użytkownika podpisującego**; sekrety
  `SM_*` w repo należą do tego użytkownika (osobny token API i certyfikat `.p12` dla CI).
  Błąd 403 „does not have privileges to access the keypair” = sekrety innego użytkownika.
- Testowe kompilacje: zmienna repo `SIGN_METHOD=none`. `digicert` włączamy wyłącznie
  za zgodą właściciela i dopiero po udanej identycznej kompilacji bez podpisu.

## Stan prac
- [x] Skrypt konfiguracji klienta i workflow (RustDesk 1.5.0), kompilacja bez podpisu działa.
- [x] Serwer na VPS, DNS, prawdziwy klucz w `SERTUM_KEY`; test połączenia udany.
- [x] Branding: nazwy we właściwościach plików, ikona i logo Sertum.
- [x] Podpis przez KeyLocker (pierwsze podpisane wydanie 2026-10-06, run 37425308494).
- [ ] Test SmartScreen na czystym Windows.
- [ ] Pilotaż na części zgłoszeń.

## Zasady
- Licencja AGPL-3.0: źródła zmian muszą być dostępne dla odbiorców klienta.
- Nigdy nie commituj klucza prywatnego serwera (`id_ed25519`) ani danych KeyLocker.
