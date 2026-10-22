#!/usr/bin/env bash
# Isolated Linux verification; never copies .env or touches production services.
set -euo pipefail
runtime_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
case "$(uname -s):$(uname -m)" in
  Linux:x86_64) bun_package=@oven/bun-linux-x64 ;;
  Linux:aarch64) bun_package=@oven/bun-linux-aarch64 ;;
  *) printf '%s\n' 'This acceptance script requires Linux x86_64 or aarch64.' >&2; exit 2 ;;
esac
command -v npm >/dev/null
workdir=$(mktemp -d /tmp/hbcn-assistant-linux.XXXXXX)
cleanup() {
  # Only the absolute directory created by mktemp above may be removed.
  case "$workdir" in /tmp/hbcn-assistant-linux.*) rm -rf -- "$workdir" ;; esac
}
trap cleanup EXIT
npm install --prefix "$workdir/tooling" --ignore-scripts --no-audit --no-fund "${bun_package}@1.4.3"
bun_bin="$workdir/tooling/node_modules/$bun_package/bin/bun"
export PATH="$(dirname -- "$bun_bin"):$PATH"
mkdir "$workdir/runtime"
cp -- "$runtime_root/package.json" "$runtime_root/bun.lock" "$runtime_root/tsconfig.json" "$workdir/runtime/"
cp -R -- "$runtime_root/src" "$runtime_root/.opencode" "$workdir/runtime/"
cd "$workdir/runtime"
"$bun_bin" --version
"$bun_bin" install --frozen-lockfile --ignore-scripts
"$bun_bin" run typecheck
"$bun_bin" test
"$bun_bin" run build
if command -v systemd-analyze >/dev/null; then
  # Validate the template offline with this test's executable/release paths.
  # No unit is installed or started, and the production env file is not read.
  sed -e "s|^WorkingDirectory=.*|WorkingDirectory=$workdir/runtime|" \
      -e "s|^ExecStart=.*|ExecStart=$bun_bin run dist/index.js|" \
      "$runtime_root/deploy/hbcn-assistant-runtime.service" > "$workdir/hbcn-assistant-runtime.service"
  systemd-analyze verify --man=no "$workdir/hbcn-assistant-runtime.service"
fi
printf '%s\n' 'Linux source and isolated release bundle verification passed (mock model; no HSBC credentials copied).'
