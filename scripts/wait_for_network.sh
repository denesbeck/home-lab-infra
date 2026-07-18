#!/bin/bash
# ExecStartPre for docker.service: block until the network is ready enough for
# containers to publish their ports cleanly after a (slow) boot.
#
# Phase 1 (HARD) — default gateway reachable:
#   Polls for BOTH a default route and a successful ping, up to $gwTimeout. Exits
#   1 on timeout so systemd retries the unit. docker.service sets
#   StartLimitIntervalSec=0 (see override.conf), so these retries never trip the
#   "start request repeated too quickly" latch that left the daemon permanently
#   dead on a slow-wifi boot (2026-07-16 incident).
#
# Phase 2 (BEST-EFFORT) — Tailscale IPv4 assigned:
#   pihole publishes :53 on the Tailscale IP as well as the LAN IP. Docker
#   publishes a container's ports atomically: if it starts before tailscaled has
#   assigned the Tailscale IP, the bind fails with "cannot assign requested
#   address" and Docker rolls back pihole's ENTIRE network setup (bridge join
#   included) — killing LAN DNS too even though the LAN IP was available
#   (2026-07-18 incident). So we wait for tailscale0 to have an IPv4 before
#   starting Docker. But we NEVER fail the unit for this: a Tailscale outage must
#   not keep Docker (and thus LAN DNS) down. If it doesn't come up in time we
#   start anyway; the docker-watchdog then Discord-alerts if pihole ends up dark.

gwCycle=2       # seconds between gateway checks
gwTimeout=120   # max seconds to wait for the LAN gateway (hard requirement)
tsCycle=2       # seconds between Tailscale checks
tsTimeout=60    # max seconds to wait for the Tailscale IP (best-effort)
tsIface=tailscale0

# --- Phase 1: LAN gateway (hard) ---
elapsed=0
while true; do
    gateway=$(ip route | awk '/default/ {print $3; exit}')
    if [ -n "$gateway" ] && ping -c 1 -W 2 "$gateway" >/dev/null 2>&1; then
        break
    fi
    if [ "$elapsed" -ge "$gwTimeout" ]; then
        echo "wait_for_network: gateway not reachable after ${gwTimeout}s; letting systemd retry" >&2
        exit 1
    fi
    sleep "$gwCycle"
    elapsed=$((elapsed + gwCycle))
done

# --- Phase 2: Tailscale IPv4 (best-effort, never fails the unit) ---
elapsed=0
while true; do
    if ip -4 addr show dev "$tsIface" 2>/dev/null | grep -q 'inet '; then
        exit 0
    fi
    if [ "$elapsed" -ge "$tsTimeout" ]; then
        echo "wait_for_network: ${tsIface} has no IPv4 after ${tsTimeout}s; starting Docker anyway (Tailscale-bound ports may fail until it comes up)" >&2
        exit 0
    fi
    sleep "$tsCycle"
    elapsed=$((elapsed + tsCycle))
done
