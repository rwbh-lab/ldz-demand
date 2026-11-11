# ldz-demand scheduled job: the daily refresh of every source, the builds, the forecasts, and the dashboard
# snapshot pushed to GitHub Pages (ldz_demand/jobs.py; run them with deploy/docker/compose.yaml).
#   docker build -t ldz-demand .                                  (--platform linux/amd64 for an Intel/AMD host)
#   docker run --rm -v <raw dir>:/data/raw ldz-demand ldz_demand.jobs daily
#   docker run --rm -v <raw dir>:/data/raw ldz-demand ldz_demand.data.ingest.ecmwf_ens status
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TQDM_DISABLE=1 \
    LDZ_DEMAND_CONFIG=/app/config/docker.ini

# git: the publish step pushes the snapshot to the gh-pages branch
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# editable, so the package keeps its project root (config/, geo data) at /app
RUN pip install -e ".[weather,db,forecast,dashboard]"
COPY config/default.ini config/docker.ini ./config/
# the dashboard pages the publish step exports, and the quick-start sample the Overview's worked example runs
COPY dashboard ./dashboard
COPY data/sample ./data/sample

# raw archive (ERA5, National Gas, ensemble runs) is mounted here
VOLUME /data/raw

ENTRYPOINT ["python", "-m"]
CMD ["ldz_demand.data.ingest.ecmwf_ens", "refresh"]
