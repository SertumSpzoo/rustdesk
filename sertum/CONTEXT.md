# Sertum Pomoc Zdalna – kontekst projektu

To jest fork RustDesk utrzymywany przez Sertum. Komunikacja z zespołem po polsku.

## Cel
Własny klient do **doraźnej** pomocy zdalnej klientom programu Sertum:
klient dzwoni na hotline, pobiera `SertumPomoc.exe` (bez instalacji), podaje ID i hasło,
technik się łączy. Stały/nienadzorowany dostęp do komputerów klientów NIE jest w zakresie.

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
  - ikony i logo z `sertum/branding/` (`icon.ico`, `icon.png`, `logo.png`).
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
- Testowe kompilacje: zmienna repo `SIGN_METHOD=none`. `digicert` włączamy wyłącznie
  za zgodą właściciela i dopiero po udanej identycznej kompilacji bez podpisu.

## Stan prac
- [x] Skrypt konfiguracji klienta i workflow (RustDesk 1.5.0), kompilacja bez podpisu działa.
- [x] Serwer na VPS, DNS, prawdziwy klucz w `SERTUM_KEY`; test połączenia udany.
- [x] Branding: nazwy we właściwościach plików, ikona i logo Sertum.
- [ ] Podpis przez KeyLocker, test SmartScreen na czystym Windows.
- [ ] Pilotaż na części zgłoszeń.

## Zasady
- Licencja AGPL-3.0: źródła zmian muszą być dostępne dla odbiorców klienta.
- Nigdy nie commituj klucza prywatnego serwera (`id_ed25519`) ani danych KeyLocker.
