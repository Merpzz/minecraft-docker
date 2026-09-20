#!/bin/bash
# Runs as the unprivileged user: install if needed, then exec the server (becomes the main process).
set -euo pipefail
cd "$DATA_DIR"

case "${EULA:-false}" in
    true|yes|1) echo "eula=true" > eula.txt ;;
    *)
        echo "[start] You must accept the Minecraft EULA (https://aka.ms/MinecraftEULA)."
        echo "[start] Set EULA=true in your .env file and start again."
        exit 1 ;;
esac

mcctl install
mcctl prepare      # SERVER_PORT, OPS, PERSIST
mcctl check-mods

# launch-cmd prints: java binary, then one argument per line.
mapfile -t LAUNCH < <(mcctl launch-cmd)
[ "${#LAUNCH[@]}" -ge 2 ] || { echo "[start] Could not determine launch command"; exit 1; }
JAVA="${LAUNCH[0]}"
ARGS=("${LAUNCH[@]:1}")

# shellcheck disable=SC2206  # JVM_OPTS is intentionally word-split
JVM=(-Xms"${MEMORY_MIN:-$MEMORY}" -Xmx"$MEMORY" -Dfile.encoding=UTF-8 ${JVM_OPTS:-})

echo "[start] $JAVA ${JVM[*]} ${ARGS[*]}"
exec "$JAVA" "${JVM[@]}" "${ARGS[@]}"
