#!/bin/bash
# install.sh — Install yt-gem and dependencies
set -e

echo "=== yt-gem installer ==="

echo "Installing Python deps..."
pip install playwright aiohttp gemini-webapi yt-dlp 2>&1 | tail -1
# On PEP 668-managed system Pythons the line above may refuse; yt-gem then
# bootstraps gemini-webapi / yt-dlp into ~/.hermes/yt_gem_deps on first use.

echo "Installing Chromium..."
playwright install chromium 2>&1 | tail -1

BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"

cp yt-gem "$BIN_DIR/yt-gem"
cp yt-gem-login "$BIN_DIR/yt-gem-login"
cp proxy_fwd.py "$BIN_DIR/proxy_fwd.py"
chmod +x "$BIN_DIR/yt-gem" "$BIN_DIR/yt-gem-login"

echo ""
echo "=== Installed ==="
echo "  yt-gem       -> $BIN_DIR/yt-gem"
echo "  yt-gem-login -> $BIN_DIR/yt-gem-login"
echo "  proxy_fwd.py -> $BIN_DIR/proxy_fwd.py (localhost CONNECT forwarder for VM egress proxies)"
echo ""
echo "=== Next Steps ==="
echo "  1. Run: yt-gem-login   (or gem-pw-login — same profile family)"
echo "  2. Sign into Gemini in the Chromium window"
echo "  3. Use: yt-gem https://www.youtube.com/watch?v=<id>"
echo "  4. Try offline first: yt-gem <url> --dry-run"
