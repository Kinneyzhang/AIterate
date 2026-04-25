#!/bin/bash
# bump_version.sh — 统一替换 AIIterate 所有 JS/CSS/HTML 的版本号缓存参数
# Usage: ./scripts/bump_version.sh

set -e
cd "$(dirname "$0")/.."

CURRENT=$(grep -oP 'main\.js\?v=\K\d+' index.html | head -1)
if [ -z "$CURRENT" ]; then
    echo "ERROR: cannot find current version in index.html"
    exit 1
fi

NEW=$((10#$CURRENT + 1))
NEW_PADDED=$(printf "%03d" $NEW)
echo "Bumping v=$CURRENT → v=$NEW_PADDED"

# JS files
find assets/js/vue -name '*.js' -exec sed -i "s/?v=$CURRENT/?v=$NEW_PADDED/g" {} +
# CSS files in index.html
sed -i "s/\.css?v=$CURRENT/.css?v=$NEW_PADDED/g" index.html
# main.js in index.html
sed -i "s/main\.js?v=$CURRENT/main.js?v=$NEW_PADDED/g" index.html

echo "Done. Version now v=$NEW_PADDED"
