#!/bin/bash
# Weekly job for the Synology NAS (DSM Task Scheduler, user root, weekly — e.g. Sunday 12:00 UK time,
# after that day's ensemble job).
#
#   1. National Gas  download new days (demand, offtakes, their forecasts); build the three tables
#   2. ERA5          download the latest weeks; build weather_ldz_daily for this month and last
#   3. Forecasts     demand forecasts for every built ensemble run that doesn't have one yet
#
# Nothing here is lost by running weekly: National Gas keeps five years and Copernicus all of ERA5. Only
# the ensemble must be downloaded daily (ens_daily.sh). The forecasts are "as issued": each uses only the
# ERA5 that existed on its run date, so a weekly batch makes the same forecast a daily job would have.
#
# Each step runs even if an earlier one failed (the forecasts can bridge a missing ERA5 week); the task
# fails (and DSM emails) if any step fails. Each step's container is kept for its log until next week
# (Container Manager -> Container -> ldz-weekly-* -> Details -> Log).
#
# Task Scheduler -> Run command:
#   bash /volume1/Development/ldz-demand/deploy/weekly.sh

# --- settings -------------------------------------------------------------------------------------
SHARE=/volume1/Development/ldz-demand       # the ldz-demand folder on the NAS
RAW="$SHARE/raw"                            # raw archive, mounted in the container at /data/raw
DB_SETTINGS="$SHARE/docker.env"             # LDZ_DB_* database settings (NAS LAN address), root-only
CDS_SETTINGS="$SHARE/cds.env"               # CDSAPI_URL and CDSAPI_KEY for ERA5, root-only
IMAGE=ldz-demand:latest

# --- helpers --------------------------------------------------------------------------------------
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

run_step() {  # run_step <container name> [docker options...] -- <module> [arguments...]
    local name=$1; shift
    local options=()
    while [ "$1" != "--" ]; do options+=("$1"); shift; done
    shift
    docker rm -f "$name" >/dev/null 2>&1          # last week's container, kept for its log
    docker run --name "$name" -v "$RAW:/data/raw" "${options[@]}" "$IMAGE" "$@"
}

failed=0
step() {  # step <label> <container name> [docker options...] -- <module> [arguments...]
    local label=$1; shift
    log "$label"
    run_step "$@"
    local status=$?
    log "$label: finished (exit $status)"
    [ $status -ne 0 ] && failed=$status
    return 0
}

# --- 1. National Gas ------------------------------------------------------------------------------
step "national gas: download"        ldz-weekly-ng-download -- ldz_demand.data.ingest.national_gas refresh
step "national gas: ng_ldz_daily"    ldz-weekly-ng-ldz      --env-file "$DB_SETTINGS" -- ldz_demand.data.build.ng_ldz_daily
step "national gas: ng_offtake_daily" ldz-weekly-ng-offtake --env-file "$DB_SETTINGS" -- ldz_demand.data.build.ng_offtake_daily
step "national gas: ng_forecast_daily" ldz-weekly-ng-forecast --env-file "$DB_SETTINGS" -- ldz_demand.data.build.ng_forecast_daily

# --- 2. ERA5 --------------------------------------------------------------------------------------
step "era5: download"                ldz-weekly-era5        --env-file "$CDS_SETTINGS" -- ldz_demand.data.ingest.era5 refresh
step "era5: weather_ldz_daily"       ldz-weekly-weather     --env-file "$DB_SETTINGS" -- ldz_demand.data.build.weather_ldz_daily --recent 1

# --- 3. Demand forecasts --------------------------------------------------------------------------
step "forecasts: missing runs"       ldz-weekly-forecast    --env-file "$DB_SETTINGS" -- ldz_demand.models.forecast --missing

exit $failed
