# deploy

Everything that runs away from a development machine.

| Folder | What |
|---|---|
| `docker/` | The scheduled jobs (daily ensemble, weekly refresh and forecasts) on any Docker host: `compose.yaml` and `.env.example` |
| `ci/` | `check.sh`: everything CI checks (lint, tests, private folders kept out of git). GitHub Actions runs it on every push; run it locally before pushing |
| `site/` | The built static dashboard (git-ignored): `python -m ldz_demand.publish` builds it, `--push` publishes it to GitHub Pages |

The jobs themselves are defined in `src/ldz_demand/jobs.py`; see the [user guide](../docs/user_guide.md) §5.4.
