#!/bin/bash
# Runs as root: fixes ownership, then drops to PUID:PGID and starts the server.
set -euo pipefail

# `docker compose run --rm minecraft mcctl loader neoforge 1.21.1` etc. -> run the command as-is.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

mkdir -p "$DATA_DIR" "$DATA_DIR/mods" "$DATA_DIR/config"

# chown only when needed - worlds can be large.
for d in "$DATA_DIR" "$DATA_DIR/mods" "$DATA_DIR/config"; do
    if [ "$(stat -c %u:%g "$d")" != "$PUID:$PGID" ]; then
        echo "[entrypoint] Setting ownership of $d to $PUID:$PGID"
        chown -R "$PUID:$PGID" "$d"
    fi
done

export HOME="$DATA_DIR"
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups /opt/mcctl/start.sh
