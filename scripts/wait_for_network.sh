#!/bin/bash
# ExecStartPre for docker.service: block until the default gateway is reachable
# so containers that need the network come up cleanly after a (slow) wifi boot.
#
# Polls for BOTH a default route and a successful ping, for up to $timeout
# seconds. Exits 1 on timeout so systemd retries the unit. docker.service sets
# StartLimitIntervalSec=0 (see override.conf), so these retries never trip the
# "start request repeated too quickly" latch that left the daemon permanently
# dead on a slow-wifi boot (2026-07-16 incident).

cycleLength=2   # seconds between checks
timeout=120     # max seconds to wait before letting systemd retry

elapsed=0
while true; do
    gateway=$(ip route | awk '/default/ {print $3; exit}')
    if [ -n "$gateway" ] && ping -c 1 -W 2 "$gateway" >/dev/null 2>&1; then
        exit 0
    fi
    if [ "$elapsed" -ge "$timeout" ]; then
        echo "wait_for_network: gateway not reachable after ${timeout}s; letting systemd retry" >&2
        exit 1
    fi
    sleep "$cycleLength"
    elapsed=$((elapsed + cycleLength))
done
