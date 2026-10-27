# tests

pytest, one file per module or feature. From the repository root:

```bash
python -m pytest          # the tests
deploy/ci/check.sh        # what CI runs: the tests plus lint and the private-folder check
```

The MySQL tests start a throwaway MySQL container (`conftest.py`), so they need Docker; without it they
are skipped. The rest need no network, keys or data beyond what's committed.
