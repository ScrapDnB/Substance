# Shared DubbingManager client

Source snapshot of `DubbingManager/online/client`, version 0.1.1. Originally
copied on 2026-10-16 and updated for Substance on 2026-10-28. This is the client
used by the current Substance build, including its ASS transfer changes.
It contains no server, account data or credentials. `SOURCE.json` records
SHA-256 hashes of the shipped files.

Install this package before installing Substance:

```sh
python -m pip install ./vendor/dubbing-online-client
python -m pip install -e ".[dev]"
```

When updating, copy the package's `pyproject.toml` and `src/dubbing_online_client`
Python sources from DubbingManager and update the hashes in `SOURCE.json`.
Keep shared changes in sync with the DubbingManager source package.
