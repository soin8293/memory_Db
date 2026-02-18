#!/usr/bin/env bash
set -euo pipefail

# Global security check (local-only). Designed to detect exposure footguns.
# Emits output ONLY when it finds a potential issue.

TMP="/tmp/openclaw-security-check.$$.txt"
trap 'rm -f "$TMP"' EXIT

issue() {
  echo "$1" >> "$TMP"
}

# 1) OpenClaw gateway bind/port/auth sanity
if command -v openclaw >/dev/null; then
  BIND="$(openclaw config get gateway.bind 2>/dev/null | tail -n 1 || true)"
  PORT="$(openclaw config get gateway.port 2>/dev/null | tail -n 1 || true)"
  AUTH="$(openclaw config get gateway.auth 2>/dev/null || true)"

  [[ "$BIND" == "loopback" ]] || issue "OpenClaw gateway.bind is not loopback: $BIND"
  [[ -n "$PORT" ]] || issue "OpenClaw gateway.port missing"
  echo "$AUTH" | grep -q '"mode"' || issue "OpenClaw gateway.auth missing/unknown"
fi

# 2) Listening sockets audit (requires /usr/sbin/lsof)
if [[ -x /usr/sbin/lsof ]]; then
  LSOF_OUT="$(/usr/sbin/lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null || true)"

  # Flag any openclaw/clawdbot listening on non-loopback
  echo "$LSOF_OUT" | awk 'NR>1 {print $1,$2,$9}' | while read -r cmd pid addr; do
    case "$cmd" in
      node|openclaw*|clawdbot*)
        case "$addr" in
          127.0.0.1:*|\[::1\]:* ) : ;;
          *:*) issue "Process $cmd pid=$pid listening on non-loopback: $addr" ;;
        esac
      ;;
    esac
  done

  # Flag common tunnel/proxy processes
  if echo "$LSOF_OUT" | grep -qiE 'ngrok|cloudflared|frpc|ssh.*-R|ssh.*-L|tailscale'; then
    issue "Tunnel/proxy-like listener detected in lsof output (ngrok/cloudflared/ssh/tailscale). Review manually."
  fi
fi

# 3) Quick process scan for known tunnels
ps aux | grep -v grep | grep -qiE 'ngrok|cloudflared|tailscale funnel|tailscale serve' && issue "Tunnel process detected (ngrok/cloudflared/tailscale serve/funnel)." || true

# Emit only if issues
if [[ -s "$TMP" ]]; then
  echo "SECURITY_CHECK_ALERT"
  cat "$TMP"

  # FAIL-CLOSED: stop gateway if OpenClaw is present
  if command -v openclaw >/dev/null; then
    echo "---"
    echo "FAIL_CLOSED_ACTION: openclaw gateway stop"
    # Stop may fail if already stopped; that's fine.
    openclaw gateway stop 2>&1 || true
  fi

  exit 2
fi

exit 0
