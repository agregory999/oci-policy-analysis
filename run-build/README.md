# Native packaging

`run/build-executable.sh` and `.ps1` are the public build adapters. Qt's Python
builder, entry point and Nuitka package configuration live here alongside the
shared ignored `.env` configuration.

```bash
run/build-executable.sh qt
run/build-executable.sh qt --mode onefile
run/build-executable.sh qt --mode onefile --lean-data
run/build-executable.sh qt --mode onefile --lean-data --lto yes
run/build-executable.sh desktop
```

Use the equivalent PowerShell adapter on Windows. `--dry-run` prints the command.
Qt outputs live in `dist/qt/`, Tk outputs in `dist/tk/`; compiler work lives under
`build/`. Qt applications, archives and measurement manifests distinguish
standalone and onefile modes. Build on the target operating system.

Compare bundle bytes, archive bytes, build time and smoke time in
`dist/qt/build-result-<mode>.json`. Keep the Python version and dependencies fixed.
`--lean-data` removes Qt translations and build-time ANTLR jars. LTO is a separate
compiler experiment and may take longer. Every Qt candidate must pass its offline
Qt/MCP smoke test before an archive is created. See [operations](../run/README.md).


For local comparisons after dependencies are installed, invoke the helper directly
to retain the current Python/toolchain. Keep each size variant in its own output
folder, for example:

```bash
.venv/bin/python run-build/build_qt_executable.py --mode onefile
.venv/bin/python run-build/build_qt_executable.py --mode onefile --lean-data --output-dir dist/qt/experiments/lean
.venv/bin/python run-build/build_qt_executable.py --mode onefile --lean-data --lto yes --output-dir dist/qt/experiments/lean-lto
```

On macOS, true onefile is an experimental command-line binary; the regular
standalone `.app` supplies Finder integration and high-resolution app metadata.
The pinned compiler's `app` mode creates a normal macOS bundle, not a compressed
onefile payload. Windows onefile uses the native GUI executable mode.

`publish_release.py` attaches verified archives by release ID. It prefers an
already published tag over duplicate drafts, retains existing assets on reruns,
and finalizes the same release record rather than creating another one.
