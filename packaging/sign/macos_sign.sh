#!/bin/bash
# M10 (REQ-1000): macOS Code-Signing + Notarization (Developer ID).
#
# Aufruf: macos_sign.sh <Pfad-zu-.app>
#
# Signiert, notarisiert und stapelt die .app an Ort und Stelle. Das
# Notarization-Ergebnis (JSON) wird neben der .app als
# notarization.json abgelegt (→ CI-Artefact, REQ-1003).
#
# Benötigte Umgebungsvariablen (aus der CI, Setup-Doku: 09 §11):
#   MACOS_SIGNING_CERT           base64-codierte .p12 (Developer ID Application)
#   MACOS_SIGNING_CERT_PASSWORD  Passwort der .p12
#   MACOS_SIGNING_IDENTITY       Signing-Identität, z. B.
#                                "Developer ID Application: NAME (TEAMID)"
#   APPLE_ID                     Apple-ID (Notarization-Account)
#   APPLE_APP_PASSWORD           App-spezifisches Passwort (appleid.apple.com)
#   APPLE_TEAM_ID                Apple-Team-ID
#
# Hinweis: Der erste Lauf mit echten Credentials ist Teil der M10-
# Akzeptanz (REQ-1000) — dann ggf. Signing-Details (z. B. --deep statt
# nachzeichnen) verfeinern.
set -euo pipefail

APP="${1:?Aufruf: macos_sign.sh <Pfad-zu-.app>}"

for v in MACOS_SIGNING_CERT MACOS_SIGNING_CERT_PASSWORD MACOS_SIGNING_IDENTITY \
         APPLE_ID APPLE_APP_PASSWORD APPLE_TEAM_ID; do
  if [ -z "${!v:-}" ]; then
    echo "::error::M10-Signing: Umgebungsvariable $v fehlt"
    exit 1
  fi
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
KC_PASS="$(openssl rand -hex 16)"
KEYCHAIN="$WORKDIR/signing.keychain-db"

# 1) Temporäres Keychain mit Zertifikat (set-key-partition-list
#    verhindert GUI-Prompts in der CI; das Keychain wird Default).
security create-keychain -p "$KC_PASS" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KC_PASS" "$KEYCHAIN"
printf '%s' "$MACOS_SIGNING_CERT" | base64 --decode > "$WORKDIR/cert.p12"
security import "$WORKDIR/cert.p12" \
  -P "$MACOS_SIGNING_CERT_PASSWORD" -A -t ssl -p keychainpassword \
  -k "$KEYCHAIN"
security set-key-partition-list -S apple-tool:,apple: -k "$KC_PASS" "$KEYCHAIN"
security list-keychains -d user -s "$KEYCHAIN" \
  "$(security list-keychains -d user | tr -d '"' | tr '\n' ' ')"
security default-keychain -s "$KEYCHAIN"

# 2) Signieren (hardened runtime = Notarization-Voraussetzung; --deep
#    signiert die gebündelten Code-Items, Muster: PyInstaller-Doku).
codesign --force --deep --options runtime \
  --sign "$MACOS_SIGNING_IDENTITY" "$APP"

# 3) Notarization (submit → wait; Ablehnung = nicht-0-Exit-Code)
cd "$WORKDIR"
ditto -c -k --sequesterRsrc --keepParent "$APP" app.zip
xcrun notarytool submit app.zip \
  --username "$APPLE_ID" --password "$APPLE_APP_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" --wait --output json \
  > "$(dirname "$APP")/notarization.json"

# 4) Stapling (Notarization-Ticket wird der App angehängt)
xcrun stapler staple "$APP"

# 5) Verifikation
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type exec --verbose "$APP"

echo "M10-Signing OK: $APP (signiert, notarisiert, gestapelt)"
