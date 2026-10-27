# db

Only needed if you store the processed tables in MySQL instead of the default CSV files (`database = true`
in `config/local.ini`, credentials in `.env`).

`migrations/` holds numbered SQL files that create the tables. The runner applies the ones the database
doesn't have yet:

```bash
python -m ldz_demand.db status     # which migrations are applied
python -m ldz_demand.db migrate    # apply the rest
```

The runner and connection code are in `src/ldz_demand/db/`; setup is in the [user guide](../docs/user_guide.md).
