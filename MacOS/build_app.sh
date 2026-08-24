#!/bin/zsh
set -euo pipefail

cd "${0:A:h}"
swift test
swift build -c release

app_dir="build/AwayCam.app"
contents_dir="$app_dir/Contents"
macos_dir="$contents_dir/MacOS"

rm -rf "$app_dir"
mkdir -p "$macos_dir"
cp ".build/release/AwayCamMac" "$macos_dir/AwayCamMac"
cp "Resources/Info.plist" "$contents_dir/Info.plist"
chmod +x "$macos_dir/AwayCamMac"

echo "作成しました: $app_dir"
echo "FinderでAwayCam.appをアプリケーションフォルダへ移動してください。"

