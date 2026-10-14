# ldz-demand scheduled jobs: the daily ECMWF ensemble job and the weekly refresh + forecasts (deploy/nas/).
#   docker build -t ldz-demand .                                  (or --platform linux/amd64 for the NAS)
#   docker run --rm -v <raw dir>:/data/raw ldz-demand             (default: ensemble refresh)
#   docker run --rm -v <raw dir>:/data/raw ldz-demand ldz_demand.data.ingest.ecmwf_ens status
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TQDM_DISABLE=1 \
    LDZ_DEMAND_CONFIG=/app/config/docker.ini

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# editable, so the package keeps its project root (config/, geo data) at /app
RUN pip install -e ".[weather,db,forecast]"
COPY config/default.ini config/docker.ini ./config/

# raw archive (ERA5, National Gas, ensemble runs) is mounted here
VOLUME /data/raw

ENTRYPOINT ["python", "-m"]
CMD ["ldz_demand.data.ingest.ecmwf_ens", "refresh"]
