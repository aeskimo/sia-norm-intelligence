#!/bin/bash
# M10 (REQ-1001): Windows-Authenticode-Signing (signtool, SHA-256 + TSA).
#
# Aufruf: windows_sign.sh <Pfad-zu-.exe>
#
# Signiert die EXE an Ort und Stelle; die signtool-verify-Ausgabe wird
# neben der EXE als sign-verify.txt abgelegt (→ CI-Artefact, REQ-1003).
#
# Benötigte Umgebungsvariablen (aus der CI, Setup-Doku: 09 §11):
#   WINDOWS_SIGNING_CERT           base64-codierte .pfx (inkl. privatem Key)
#   WINDOWS_SIGNING_CERT_PASSWORD  Passwort der .pfx
#
# signtool.exe kommt aus dem Windows-10/11-SDK, das auf den GHA
# windows-latest-Runnern vorinstalliert ist.
#
# Hinweis: Der erste Lauf mit echtem Zertifikat ist Teil der M10-
# Akzeptanz (REQ-1001, SmartScreen-Verhalten).
set -euo pipefail

EXE="${1:?Aufruf: windows_sign.sh <Pfad-zu-.exe>}"

for v in WINDOWS_SIGNING_CERT WINDOWS_SIGNING_CERT_PASSWORD; do
  if [ -z "${!v:-}" ]; then
    echo "::error::M10-Signing: Umgebungsvariable $v fehlt"
    exit 1
  fi
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
printf '%s' "$WINDOWS_SIGNING_CERT" | base64 --decode > "$WORKDIR/cert.pfx"

# Neueste SDK-Version mit signtool (x64)
SIGNTOOL="$(ls "/c/Program Files (x86)/Windows Kits/10/bin/"*/x64/signtool.exe 2>/dev/null | sort -V | tail -1)"
if [ -z "$SIGNTOOL" ]; then
  echo "::error::M10-Signing: signtool.exe nicht gefunden (Windows SDK fehlt?)"
  exit 1
fi

# Signieren mit Zeitstempel (TSA — Signatur bleibt nach Zertifikats-
# Ablauf gültig)
"$SIGNTOOL" sign /fd SHA256 \
  /tr http://timestamp.sectigo.com /td SHA256 \
  /f "$WORKDIR/cert.pfx" /p "$WINDOWS_SIGNING_CERT_PASSWORD" \
  "$EXE"

# Verifikation (Auskunft → Artefact)
"$SIGNTOOL" verify /pa /v "$EXE" | tee "$(dirname "$EXE")/sign-verify.txt"

echo "M10-Signing OK: $EXE (Authenticode + Zeitstempel)"
