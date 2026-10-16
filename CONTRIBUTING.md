# Development

Use Python 3.11 or newer and install the development dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./vendor/dubbing-online-client
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/test.py
.venv/bin/python run.py
```

On Windows use `.venv\Scripts\python.exe`. Package on the target OS with
`python scripts/build.py`. GitHub Actions tests and packages macOS and Windows.
The shared online client is included as a source snapshot in
`vendor/dubbing-online-client`; install it before the editor dependencies.
See [docs/builds.md](docs/builds.md) for automatic builds and Windows commands
without a virtual environment.

Keep user projects, media, credentials, virtual environments and generated
packages out of Git. Private ASS integration fixtures are optional and must be
provided explicitly through `DUBBING_MANAGER_TEST_FILES`.

Changes to project persistence must preserve older supported schemas and unknown
fields. Verify round trips, undo/redo, recovery and plain subtitle export when
changing the document model. Include a short description and relevant validation
in pull requests. Record user-visible changes in CHANGELOG.md.
