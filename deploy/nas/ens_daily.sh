#!/bin/bash
# Daily ECMWF ensemble job for the Synology NAS (DSM Task Scheduler, user root, daily at 11:00 UK time).
#
#   1. download  the latest 00z ensemble run (and yesterday's, if missing), cropped to GB
#   2. build     ens_ldz_daily in MySQL from every archived run not yet built
#
# Both steps run in the ldz-demand image (built on the Mac, imported in Container Manager; see
# docs/user_guide.md section 5.3). The build runs even if the download failed, so earlier runs still
# get built. The task fails (and DSM emails) if either step fails.
#
# Each step's container is kept after it finishes, so its log can be read in Container Manager
# (Container -> ldz-ens-download / ldz-ens-build -> Details -> Log) until the next day's run.
#
# Task Scheduler -> Run command:
#   bash /volume1/<share>/ldz-demand/deploy/ens_daily.sh

# --- settings -------------------------------------------------------------------------------------
SHARE="$(cd "$(dirname "$0")/.." && pwd)"   # the ldz-demand folder on the NAS (this script is in its deploy/)
RAW="$SHARE/raw"                            # raw archive, mounted in the container at /data/raw
DB_SETTINGS="$SHARE/docker.env"             # LDZ_DB_* database settings (NAS LAN address), root-only
IMAGE=ldz-demand:latest

# --- helpers --------------------------------------------------------------------------------------
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

run_step() {  # run_step <container name> [docker options...] -- <module> [arguments...]
    local name=$1; shift
    local options=()
    while [ "$1" != "--" ]; do options+=("$1"); shift; done
    shift
    docker rm -f "$name" >/dev/null 2>&1          # yesterday's container, kept for its log
    docker run --name "$name" -v "$RAW:/data/raw" "${options[@]}" "$IMAGE" "$@"
}

# --- 1. download ----------------------------------------------------------------------------------
log "download: latest ensemble run"
run_step ldz-ens-download -- ldz_demand.data.ingest.ecmwf_ens refresh
download_status=$?
log "download: finished (exit $download_status)"

# --- 2. build -------------------------------------------------------------------------------------
log "build: ens_ldz_daily"
run_step ldz-ens-build --env-file "$DB_SETTINGS" -- ldz_demand.data.build.ens_ldz_daily
build_status=$?
log "build: finished (exit $build_status)"

# --- result: fail if either step failed -----------------------------------------------------------
if [ $download_status -ne 0 ]; then exit $download_status; fi
exit $build_status
