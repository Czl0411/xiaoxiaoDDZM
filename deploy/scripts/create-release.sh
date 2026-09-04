#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "$0")/../.." && pwd)
output=${1:-"$root_dir/dzmmbot-server-release.tar.gz"}

cd "$root_dir"
tar -czf "$output" \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  source deploy docs 塔罗牌素材 盲盒小游戏素材
echo "$output"
