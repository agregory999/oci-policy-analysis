# Synthetic compiled corpus example

These files demonstrate the experimental corpus format; they are not live OCI data.

Open `compiled-corpus.json` using **Open Corpus** in the experimental desktop tab.
Six source statements produce five grants: two regional READ alternatives, one
INSPECT grant with two source IDs, a time-constrained DELETE grant, and a conditional
DELETE deny. Select a row to inspect its predicates and provenance.

`corpus-scenarios.json` demonstrates shared region/time context and per-request
overrides. `corpus-results.json` contains all six expected results and contribution
witnesses. The two identical INSPECT statements have no individual removal effect;
the corpus still needs at least one of them.

Opened artifacts are inspection-only until rebuilt against the loaded data. The
sample's reference data is deliberately limited to three operations. See
[the feature guide](../../docs/source/compiled-corpus.md) for the workflow and limits.
