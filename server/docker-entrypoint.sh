#!/bin/sh
# Index the bundled repository once FalkorDB answers, then hand over to CMD.
# Retries with backoff (1, 2, 4, 8, 10, 10 ... seconds) for up to 60 seconds.
set -eu

root="${AIRSPACE_ROOT:-/data/repo}"
deadline=60
elapsed=0
delay=1

until airspace index --root "$root"; do
    if [ "$elapsed" -ge "$deadline" ]; then
        echo "airspace: FalkorDB at ${FALKORDB_HOST:-localhost}:${FALKORDB_PORT:-6379} not reachable after ${deadline}s" >&2
        exit 1
    fi
    if [ "$delay" -gt $((deadline - elapsed)) ]; then
        delay=$((deadline - elapsed))
    fi
    echo "airspace: waiting ${delay}s for FalkorDB" >&2
    sleep "$delay"
    elapsed=$((elapsed + delay))
    delay=$((delay * 2))
    if [ "$delay" -gt 10 ]; then
        delay=10
    fi
done

exec "$@"
