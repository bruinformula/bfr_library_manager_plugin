#!/bin/bash
# ============================================================
# BFR KiCad Library Manager — PCM Package Builder
# ============================================================
# This script builds the ZIP package that KiCad's Plugin &
# Content Manager (PCM) expects, AND generates the repository
# JSON files needed to host your own custom PCM repository.
#
# Usage:
#   chmod +x build_pcm_package.sh
#   ./build_pcm_package.sh
#
# Output (in ./pcm_output/):
#   BFR-KiCad-Library-Manager-1.1.0.zip   <- The installable plugin package
#   repository.json                         <- Top-level repo index
#   packages.json                           <- Version manifest
#   resources.zip                           <- Icon for KiCad UI
# ============================================================

set -e

VERSION="1.1.0"
PKG_NAME="BFR-KiCad-Library-Manager"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/pcm_output"
TEMP_DIR=$(mktemp -d)

echo "🔧 Building PCM package v${VERSION}..."

# Clean output
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

# ── 1. Build the plugin ZIP ──────────────────────────────────
# PCM expects: plugins/<package_name>/  inside the ZIP
PLUGIN_DIR="${TEMP_DIR}/plugins/com_github_bfracing_bfr-kicad-library-manager"
mkdir -p "${PLUGIN_DIR}"

# Copy all plugin files
cp "${SCRIPT_DIR}/plugins/__init__.py"              "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/__main__.py"              "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_gui.py"               "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_backend.py"           "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_classifier.py"        "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_metadata.py"          "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_library_router.py"    "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_master_manager.py"    "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/bfr_logo_stamp.py"        "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/zip_extractor.py"         "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/jlc_store.py"             "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/jlc_fabrication.py"       "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/jlc_schematic_export.py"  "${PLUGIN_DIR}/"
cp "${SCRIPT_DIR}/plugins/icon.png"                 "${PLUGIN_DIR}/"

# Copy metadata.json into the root of the ZIP (PCM requires this)
cp "${SCRIPT_DIR}/plugins/metadata.json"            "${TEMP_DIR}/"

# Create the ZIP
cd "${TEMP_DIR}"
ZIP_PATH="${OUTPUT_DIR}/${PKG_NAME}-${VERSION}.zip"
zip -r "${ZIP_PATH}" metadata.json plugins/
echo "✓ Plugin ZIP: ${ZIP_PATH}"

# ── 2. Compute SHA256 and file sizes ─────────────────────────
ZIP_SHA256=$(shasum -a 256 "${ZIP_PATH}" | awk '{print $1}')
ZIP_SIZE=$(stat -f%z "${ZIP_PATH}" 2>/dev/null || stat --printf="%s" "${ZIP_PATH}")

# Rough install size (sum of source files)
INSTALL_SIZE=0
for f in "${PLUGIN_DIR}"/*; do
    fsize=$(stat -f%z "$f" 2>/dev/null || stat --printf="%s" "$f")
    INSTALL_SIZE=$((INSTALL_SIZE + fsize))
done

echo "   SHA256: ${ZIP_SHA256}"
echo "   Download size: ${ZIP_SIZE}"
echo "   Install size: ~${INSTALL_SIZE}"

# ── 3. Build resources.zip (icon) ────────────────────────────
RESOURCES_DIR="${TEMP_DIR}/resources"
mkdir -p "${RESOURCES_DIR}/com.github.bfracing.bfr-kicad-library-manager"
cp "${SCRIPT_DIR}/plugins/icon.png" "${RESOURCES_DIR}/com.github.bfracing.bfr-kicad-library-manager/icon.png"

RESOURCES_ZIP="${OUTPUT_DIR}/resources.zip"
cd "${RESOURCES_DIR}"
zip -r "${RESOURCES_ZIP}" .
RESOURCES_SHA256=$(shasum -a 256 "${RESOURCES_ZIP}" | awk '{print $1}')
echo "✓ Resources ZIP: ${RESOURCES_ZIP}"

# ── 4. Generate packages.json ────────────────────────────────
# IMPORTANT: Replace GITHUB_USER and REPO_NAME with your actual GitHub info!
GITHUB_USER="bruinformula"
REPO_NAME="bfr_library_manager_plugin"
DOWNLOAD_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}/releases/download/v${VERSION}/${PKG_NAME}-${VERSION}.zip"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M:%S")
EPOCH=$(date +%s)

cat > "${OUTPUT_DIR}/packages.json" << PACKAGES_EOF
{
    "packages": [
        {
            "\$schema": "https://go.kicad.org/pcm/schemas/v1",
            "name": "BFR KiCad Library Manager",
            "description": "All-in-one library manager, JLCPCB manufacturing suite, and LCSC part assigner",
            "description_full": "BFR KiCad Library Manager is a comprehensive KiCad plugin that combines library management with JLCPCB manufacturing integration. Features include ZIP import, auto-classification, LCSC metadata enrichment, JLCPCB production file generation, Interactive HTML BOM, and more.",
            "identifier": "com.github.bfracing.bfr-kicad-library-manager",
            "type": "plugin",
            "author": {
                "name": "BF Racing",
                "contact": {
                    "web": "https://github.com/${GITHUB_USER}"
                }
            },
            "maintainer": {
                "name": "BF Racing",
                "contact": {
                    "web": "https://github.com/${GITHUB_USER}"
                }
            },
            "license": "MIT",
            "resources": {
                "homepage": "https://github.com/${GITHUB_USER}/${REPO_NAME}"
            },
            "versions": [
                {
                    "version": "${VERSION}",
                    "status": "stable",
                    "kicad_version": "8.0",
                    "download_sha256": "${ZIP_SHA256}",
                    "download_size": ${ZIP_SIZE},
                    "download_url": "${DOWNLOAD_URL}",
                    "install_size": ${INSTALL_SIZE}
                }
            ]
        }
    ]
}
PACKAGES_EOF

PACKAGES_SHA256=$(shasum -a 256 "${OUTPUT_DIR}/packages.json" | awk '{print $1}')
echo "✓ packages.json generated"

# ── 5. Generate repository.json ──────────────────────────────
RESOURCES_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}/raw/main/repository/resources.zip"
PACKAGES_URL="https://raw.githubusercontent.com/${GITHUB_USER}/${REPO_NAME}/main/repository/packages.json"

cat > "${OUTPUT_DIR}/repository.json" << REPO_EOF
{
    "\$schema": "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v1.schema.json#/definitions/Repository",
    "maintainer": {
        "contact": {
            "web": "https://github.com/${GITHUB_USER}"
        },
        "name": "BF Racing"
    },
    "name": "BFR KiCad Repository",
    "packages": {
        "sha256": "${PACKAGES_SHA256}",
        "update_time_utc": "${TIMESTAMP}",
        "update_timestamp": ${EPOCH},
        "url": "${PACKAGES_URL}"
    },
    "resources": {
        "sha256": "${RESOURCES_SHA256}",
        "update_time_utc": "${TIMESTAMP}",
        "update_timestamp": ${EPOCH},
        "url": "${RESOURCES_URL}"
    }
}
REPO_EOF

echo "✓ repository.json generated"

# ── Cleanup ──────────────────────────────────────────────────
rm -rf "${TEMP_DIR}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ BUILD COMPLETE — Output in: ${OUTPUT_DIR}"
echo ""
echo "Files:"
ls -lh "${OUTPUT_DIR}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Create a GitHub repo: ${GITHUB_USER}/${REPO_NAME}"
echo "2. Copy 'repository/' folder structure:"
echo "     repository/"
echo "       ├── repository.json"
echo "       ├── packages.json"
echo "       └── resources.zip"
echo ""
echo "3. Create a GitHub Release tagged 'v${VERSION}' and attach:"
echo "     ${PKG_NAME}-${VERSION}.zip"
echo ""
echo "4. In KiCad → Plugin Manager → Manage Repositories → Add:"
echo "   Name: BFR KiCad Repository"
echo "   URL:  https://raw.githubusercontent.com/${GITHUB_USER}/${REPO_NAME}/main/repository/repository.json"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
