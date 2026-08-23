# Hermes upstream integration

StudyHub Agent V2 starts from an unmodified Hermes Agent checkout. The exact
upstream repository and commit are recorded in `upstream.lock.json`.

Bootstrap the checkout with:

```bash
bash studyhub-agent/scripts/setup-hermes.sh
```

The script clones or fetches Hermes into
`studyhub-agent/.vendor/hermes-agent`, verifies that an existing checkout is
clean and points at the expected upstream repository, and checks out the pinned
commit in detached-HEAD mode.

This integration deliberately contains no StudyHub patch, skin, router,
planner, tool loop, memory implementation, or model configuration. Install and
configure Hermes from inside the checkout by following the upstream
documentation. Keep its virtual environment and credentials separate from the
StudyHub website runtime.
