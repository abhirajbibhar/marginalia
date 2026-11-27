#!/usr/bin/env bash
# vendor_assets.sh — copy runtime assets from cadence/ and node_modules into
# static/ (the template contract says: vendor everything locally).
#
# Bootstrap 6 comes from the Cadence template (v6.0.0-alpha.1, .bs6-sha);
# HTMX and @embedpdf/snippet + pdfium.wasm come from pinned npm packages.
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">> Bootstrap 6 (from cadence/)"
cp cadence/assets/vendor/bootstrap6/css/bootstrap.min.css static/vendor/bootstrap6/css/
cp cadence/assets/vendor/bootstrap6/js/bootstrap.bundle.min.js static/vendor/bootstrap6/js/
cp cadence/assets/css/base.css cadence/assets/css/style.css static/css/

echo ">> HTMX + EmbedPDF (pinned via package.json)"
npm install --no-audit --no-fund
cp node_modules/htmx.org/dist/htmx.min.js static/js/
cp node_modules/@embedpdf/snippet/dist/*.js static/embedpdf/
cp node_modules/@embedpdf/pdfium/dist/pdfium.wasm static/embedpdf/

echo ">> Done. Static assets vendored under static/."
