# Run, build, clean and deploy

Scripts live in `run/`. One sourceable configuration lives in **`run-build/.env`**, copied from [the canonical example](../run-build/.env.example). `run/.env.example` is a compatibility link to that same example. The four sections are General Settings, Local Run and Build, Container Only, and MCP Oauth. Each input states its default, optional status, or conditional requirement. `RUN_ENV_FILE=/absolute/path/to/config` selects another file with the same schema.

```bash
cp run-build/.env.example run-build/.env
chmod 600 run-build/.env
run/build.sh
run/local.sh web
```

Choose only the workflow you need:

| Workflow | Values you must supply |
| --- | --- |
| Local run/build | None; existing OCI config and API key are sufficient. |
| Build/push web or MCP | The registry/operator block and that interface's image tag. |
| Deploy web or MCP | The registry/operator block, that interface's tag, and the target-network block. |
| Combined deployment | Same as deployment, with both distinct image tags. |
| OAuth | Only when enabled: the six commented identity-domain values. |

Optional settings are commented out and show their defaults. The file sets just two MCP runtime choices: domain depth and log level. Choose the interface in the command instead of another mode setting. `OCI_DRY_RUN=true` and `OCI_REDEPLOY=true` are one-run actions rather than persistent configuration choices.

The file is trusted shell configuration: quote values containing spaces or shell characters. The loader exports assignments; `export` is optional. Exported one-run environment values override the file, and explicit application command flags override defaults. Web/desktop preferences stay in `~/.oci-policy-analysis/settings.json` and the application's settings screens.

## Local API-key authentication

No container inputs or OAuth setup are required locally. Keep the usual OCI API signing key and `~/.oci/config`; do not copy the private key into `.env`. `LOCAL_OCI_PROFILE` defaults to `DEFAULT` and is separate from the deployment operator's `OCI_PROFILE`. Local commands also work without a default `.env`; an explicitly requested missing `RUN_ENV_FILE` fails.

```bash
run/local.sh desktop
run/local.sh cli --profile DEFAULT --recursive --compartment-domain-search-depth 2
run/local.sh web
run/local.sh mcp --profile DEFAULT
LOCAL_MCP_TRANSPORT=streamable-http run/local.sh mcp --profile DEFAULT
```

MCP defaults to stdio locally. Explicit authentication flags select the identity; without a flag, standalone MCP uses `MCP_AUTH_MODE` (default profile) and the local profile. Installed commands remain `oci-policy-analysis-ui`, `oci-policy-analysis-cli`, `oci-policy-analysis-web`, and `oci-policy-analysis-mcp`. Direct commands read exported environment values; they do not source `.env` automatically.

`MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH=2` is the **only MCP depth variable**. It means root plus direct child compartments; 1 means root only, 3 includes grandchildren, maximum 6. The container entrypoint turns it into `--compartment-domain-search-depth`; the standalone MCP command reads the same name. An explicit command flag wins. The former `OCI_POLICY_ANALYSIS_DOMAIN_COMPARTMENT_DEPTH` is not consumed or forwarded by this workflow. Web/desktop depth is managed through their existing settings, and CLI depth can be selected with its flag.

Containers receive only their own launch settings:

| Container | Runtime environment |
| --- | --- |
| Web | `WEB_RESOURCE_PRINCIPAL_ONLY`, `WEB_HOST`, `WEB_PORT` |
| MCP | `MCP_AUTH_MODE`, `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH`, `MCP_LOG_LEVEL` |

Authentication, transport and bind addresses are filled automatically for containers. OAuth variables enter MCP only when OAuth is enabled; optional MCP recursion/cache controls enter only when explicitly configured. No UI preferences, diagnostics paths, operator credentials or general-purpose settings bundle is forwarded.

## Local build and clean

`run/build.sh [--mode desktop|web|cli|mcp|all]` uses `uv sync` and `uv build`, generating an ignored local `uv.lock`; all is the default. `PYTHON_BIN` optionally selects Python. `run/build-executable.sh` retains platform-specific PyInstaller packaging and resource collection, installing the checked-out project and packaging dependencies through uv. It writes distributables to `dist/` and the generated package version file. PyInstaller packaging needs the platform's Python shared library and icon/archive tools; it is separate from container builds.

Dependencies are declared in `pyproject.toml`; the repository does not track a lockfile. `uv sync` can reuse a local lock; use `uv lock --upgrade` to refresh it within the declared constraints. Fresh checkouts and pip-based container/release builds resolve those constraints independently.

For the Qt workbench, use the local source Nuitka build path:

```bash
run/build-executable.sh qt                       # native .app on macOS, standalone directory elsewhere
run/build-executable.sh qt --mode onefile        # single executable on the native platform
run/build-executable.sh qt --dry-run             # inspect compiler arguments
run/build-executable.sh qt --mode onefile --lean-data
run/build-executable.sh qt --mode onefile --lean-data --lto yes
```

On Windows: `run/build-executable.ps1 qt` (optionally `--mode onefile`).
The wrapper installs the `qt`, `qt-build`, `web` and `mcp` extras with uv,
validates dependencies and Qt/MCP startup, then invokes
`run-build/build_qt_executable.py`. Build on each target OS with its native C
compiler (Xcode Command Line Tools on macOS, MSVC on Windows, GCC/Clang on
Linux). Nuitka is pinned to 4.2.2 because 4.3 regressed compiled PySide6 signal
connections. Upgrading the compiler requires passing the packaged smoke test.
The PySide6 plugin collects native Qt libraries/plugins; package data
includes icons, reference resources, parsers and the fictional sample. The
package configuration retains the pinned OCI SDK’s normal lazy-import branch,
avoiding compilation of unrelated services through its eager fallback. See
[Qt's Nuitka deployment guide](https://doc.qt.io/qtforpython-6/deployment/deployment-nuitka.html).

After compilation, the executable runs `--self-test` offline with temporary
settings/cache storage, exercising Qt startup, packaged resources, sample
loading, shared principal queries, typed MCP metadata and in-memory snapshot MCP
queries. Only a passing bundle
is archived. Compiler intermediates stay under `build/qt/<mode>/native/`.
`dist/qt/` contains cleanly named runnable applications, release archives and
`build-result-<mode>.json`, which identifies the executable and archive (ZIP on Windows, tar.gz on macOS/Linux to
preserve symlinks and executable permissions);
`build/qt/nuitka-report.xml` records module and data inclusion. Artifacts are
ignored. These builds are unsigned and not notarized; external Codex CLI/login
remain separate. Existing `run/build-executable.sh`/`.ps1` without `qt` retain
the Tkinter/PyInstaller path.

Both local and CI builds use the Nuitka project options in `run-build/qt_entry.py`.
Nuitka may download compiler helpers without prompting. ccache is used when
available on macOS/Linux; MSVC uses clcache on Windows. Install ccache locally
with `brew install ccache` on macOS. Removing `dist/` does not clear compiler caches.
The GitHub `build_qt` matrix uses the pinned official Nuitka action, persists its
cache, and smoke-tests macOS arm64 and Windows x64 bundles before attaching their
archives to the same semantic-release prerelease as the Tkinter installers.
On Windows, extract the entire Qt ZIP and run `oci-policy-analysis-qt/oci-policy-analysis-qt.exe`;
keep its adjacent DLLs and resource folders together.

`run/clean.sh` deliberately removes `.venv`, `dist`, `build`, `wheels`, generated dependency lists and source Python caches. It preserves configuration, signing keys and application data. Build again afterward. Root `local-run.sh`, `local-build.sh`, `local-clean.sh`, `local-build-with-pyinstaller.sh`, and MCP build/deploy shell/PowerShell names are compatibility adapters into `run/`; they use the same configuration. Native Windows commands are `run/local.ps1`, `run/build.ps1`, `run/clean.ps1`, and `run/build-executable.ps1`; they read the same literal assignments in the shared file. PowerShell container adapters require Bash. PowerShell configuration supports literal quoted values, not shell expansion/command substitution. The ignored old `env.sh` is no longer sourced by these commands.

## Build and push source images

Prerequisites: Docker/buildx, OCI CLI, jq, authenticated operator profile, and an existing OCIR repository. Set registry host, namespace, repository, region, compartment, operator `OCI_PROFILE`, and distinct release tags in the Container Only section. Authenticate Docker to that exact host using its credential store:

```bash
docker login YOUR_OCIR_HOST
run/build-push-image.sh web
run/build-push-image.sh mcp
# Or build/push both sequentially:
run/build-push-image.sh combined
```

`Dockerfile` has web and mcp targets and installs this checkout, never a published application wheel. Dockerfile.mcp remains compatible for direct legacy builds; consolidated scripts use Dockerfile targets. `BUILD_PLATFORM` defaults to linux/amd64. OCI image lookup checks tag existence; an existing tag is refused unless `ALLOW_TAG_REPUSH=true` is intentional. Reusing tags makes rollback ambiguous and may not trigger replacement: prefer fresh tags. Build validates Docker, OCI access, and repository existence; Docker push uses the operator's existing registry login and reports authentication failures. No repository or credentials are created.

## Build and push a published PyPI release

Choose this path when the deployment must use a published application release rather than your checkout. In the **PIP Deployments** section of the same `.env`, uncomment and set one exact version:

```bash
OPA_VERSION=6.5.5
```

Choose fresh, distinct image tags in the existing Container Only section (for example, `6.5.5-pypi-web-1` and `6.5.5-pypi-mcp-1`). Then:

```bash
run/build-push-pypi.sh web
run/build-push-pypi.sh mcp
# Or both:
run/build-push-pypi.sh combined

OCI_DRY_RUN=true OCI_REDEPLOY=true run/deploy-container-instance.sh combined
OCI_REDEPLOY=true run/deploy-container-instance.sh combined
```

`run/build-push-image.sh` always builds local application source, even when `OPA_VERSION` is set. Only `run/build-push-pypi.sh` uses that version. Its Dockerfile installs `oci-policy-analysis[web]==VERSION` or `[mcp]==VERSION` from PyPI and labels the image with the published package version. Its build context is `docker/`, containing launch scripts, not `src/`, pyproject, or local dependencies. No local application edits enter these images. The thin launch scripts still come from this operations checkout, so retain its Git revision alongside the package version and image tags when documenting a deployment.

Both build paths publish to the same configured OCIR repository and feed the same deploy script; runtime settings, network validation, explicit replacement, health checks and rollback work the same way. `OPA_VERSION` is a build input, not a container runtime variable. Setting it alone does not replace a running image. A configuration-only redeploy can reuse existing tags and does not need Docker or an image build.

`OPA_VERSION` selects the published application code; local edits are included only by the source build. Record the pushed image digest for exact rollback. New source builds stamp their tag and UTC build time into the image; the web console's bottom status bar shows these alongside the application version and server start time. No extra `.env` settings are needed.


## Container Instances

Set the target compartment, region, availability domain, subnet, NSG, instance name, shape/capacity and relevant tags. Python 3 is needed for validated JSON generation. Modes are `combined` (default), `web` and `mcp`. Single modes require only their image tag; they still need their own unique instance name and available private IP. Switching modes under one instance name explicitly replaces it. An unrelated or separately deployed OAuth instance is never retired by this workflow.

```bash
OCI_DRY_RUN=true OCI_REDEPLOY=true run/deploy-container-instance.sh combined
OCI_REDEPLOY=true run/deploy-container-instance.sh combined
# Separate instance, configured with its own name/private IP:
run/deploy-container-instance.sh mcp
```

Preflight validates the selected container runtime/OAuth settings, operator access, availability domain, available shape, network resources and selected images before mutations. Deployment creates only the named Container Instance with a private VNIC. Containers use Resource Principal; the web interface is restricted to it and MCP uses streamable HTTP. The payload includes only that container's launch settings, never the operator profile, local session token or registry credentials. Private image pulling requires the existing OCIR/resource-principal IAM and egress setup. Dynamic group, workload IAM, VCN, subnet, NSG rules, repository, Load Balancer and its backends are managed outside this script.

`WEB_PORT` defaults to 8000 and `MCP_PORT` to 8765; configure the actual existing backend ports (the current combined instance uses **8000/8001**). New locally built images honor these ports; an older web image may have a fixed port. Health checks use `/health`; MCP protocol traffic uses `/mcp`. Configure ingress from the existing Load Balancer and OCIR/OCI API egress independently. OAuth is disabled unless explicitly enabled; enabling it requires all six identity-domain values in the example. Optional discovery/update scopes are passed too.

An instance with matching images, runtime environment and health ports is left alone. Configuration changes, including depth or OAuth, require replacement just like image changes. `OCI_REDEPLOY=true` opts into delete/create; the script validates the existing name, subnet, NSG and private IP first. This causes downtime. The old IP is requested but not reserved; creation can fail if it becomes unavailable. The script never searches for/deletes an unrelated instance occupying an IP.

The script prints the resulting private IP and writes ignored `run/.container-private-ip` and `run/.container-instance-id`. Check both configured `/health` endpoints from the network and both separately managed Load Balancer backend health statuses. MCP startup loads tenancy data before serving, so allow time for identity-domain traversal. Check container lifecycle/logs if the health endpoint stays unavailable.

## Rollback and verification

Record the two prior image tags and runtime settings before replacement. To roll back, restore those tags **and** settings in the same `.env`, run a dry run, then explicit replacement. If create fails after delete, inspect OCI work requests and correct capacity/IP/pull permissions before retrying. A different private IP requires an operator update of each Load Balancer backend.

```bash
uv sync --extra web --extra mcp
.venv/bin/python -m pytest -q src/test/test_runtime_environment.py src/test/test_web_resource_principal.py
.venv/bin/ruff check src/oci_policy_analysis/runtime_settings.py run/container-config.py
python3 scripts/check_project.py .
```

OCI's [container update API](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/container-instances/container/update.html) only exposes metadata changes; runtime/image changes use the [Container Instance create operation](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/container-instances/container-instance/create.html) after explicit replacement.

Legacy deployment variable migration: `OCI_COMPARTMENT_OCID` → `OCI_COMPARTMENT_ID`, `OCI_SUBNET_OCID` → `OCI_SUBNET_ID`, `OCIR_REPO` → `OCI_REPOSITORY`, `OCI_AD` → `OCI_AVAILABILITY_DOMAIN`, `OCI_CONTAINER_INSTANCE_NAME` → `OCI_INSTANCE_NAME`, and `OCI_IMAGE_URL` → registry/namespace/repository plus the selected image tag. `OPA_VERSION` is consumed only by the explicit PyPI build path; the default source build uses this checkout. `DOCKER_CONTEXT`, legacy instance names and LB NSG inputs are no longer consumed. Select the Docker CLI context normally; networking and other deployments stay externally owned.

## Less common options

These are supported when needed but intentionally absent from the short example. Set an exported one-run value or add an assignment to the same `.env`:

- `LOCAL_MODE=desktop` and `LOCAL_BUILD_MODE=all`: optional defaults; commands can choose the mode directly.
- `CONTAINER_MODE=combined`: default deployment mode; the positional command argument overrides it.
- `ALLOW_TAG_REPUSH=true`: intentionally replace an existing image tag; prefer a fresh release tag.
- `MCP_RECURSIVE=false`: limit policy loading; default true in the container.
- `MCP_SAVE_CACHE_AFTER_LOAD=true`: save container-loaded caches; default false.
- Local MCP alternate authentication: use `--instance-principal`, `--resource-principal`, `--use-cache NAME`, or `--session-token TOKEN` instead of profile auth. `MCP_AUTH_MODE`, `MCP_USE_CACHE` and `OCI_SESSION_TOKEN` remain supported for direct standalone use, but local credentials never enter deployed containers.
- Advanced OAuth: `MCP_OAUTH_UPDATE_SCOPE`, `MCP_OAUTH_AUTHORIZATION_SCOPES`, `MCP_OAUTH_AUTHORIZATION_SERVER_METADATA_ISSUER`, `MCP_OAUTH_AUTHORIZATION_ENDPOINT`, `MCP_OAUTH_TOKEN_ENDPOINT`, and `MCP_OAUTH_ALGORITHM` (default RS256). These are forwarded only with OAuth enabled. See [OAuth configuration](../docs/source/mcp_oauth.md).

Diagnostics and UI preferences are not part of deployment configuration. Use the existing application controls and [troubleshooting guide](../docs/source/logging_and_troubleshooting.md) for those.


## Local packaging comparisons

Qt's helper, entry point and Nuitka configuration live under `run-build/`; the
shell and PowerShell launchers remain under `run/`. Tk builds use `dist/tk/`
and the `oci-policy-analysis-tk` application name. Qt builds use `dist/qt/`
and `oci-policy-analysis-qt`; onefile applications add `-onefile`. Archives include
their mode and version, so standalone and onefile outputs can be compared safely.
Compiler work stays under `build/`, and neither output cleanup clears Nuitka caches.

The per-mode Qt manifests record uncompressed bundle size, archive size, build
time and smoke-test time. Keep Python, dependencies and compiler settings fixed
for a fair comparison. Onefile changes distribution and extraction behavior;
it still needs the same Qt/Python runtime contents. `--lean-data` omits Qt
translations and build-time parser jars. `--lto yes` is a separate, slower compiler
experiment. Retain MCP metadata/descriptions and validate every candidate with
the packaged smoke test before using or distributing it.
