# Usage

## From source
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m oci_policy_analysis
```
## Run from a release executable

Simply run the executable from the release secion

```bash
# Windows
oci-policy-analysis.exe

# macOS
./oci-policy-analysis.app
```

## Main Tabs

Policies — browse & filter parsed policy statements

Users / Groups / Dynamic Groups — explore relationships and memberships

Overlap Detection — find potential redundant/conflicting statements

Historical Comparison — diff cached tenancy snapshots

MCP / AI — built-in FastMCP server + AI results pane