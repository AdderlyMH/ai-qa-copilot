# Guest demo fixture

The source material for the public guest demo
([ADR-019](../../docs/adr/ADR-019-guest-demo-snapshot.md) Decisions 8, 10
and 12).

- **Synthetic and authored for the demo.** It describes a fictional order
  service. It is not derived from the evaluation seeds, overlays, labels or
  any other evaluation material, and it is demo content, not evaluation
  evidence.
- **Deliberately flawed.** Some requirements are vague, incomplete or
  contradictory, so the rule-based analyzer has real findings to report.
- **Only what the in-process mock order API implements.** Every requirement
  and seed describes an operation of `mock_order_api.py`: create, list,
  read, update and cancel orders.

## Files

| File | Content |
|---|---|
| `requirements.md` | Eight requirements, one per line as `REQ-<ID>: <statement>`, in document order. |
| `seeds.json` | Author-written test-generation seeds (request and assertions). Each names its requirement(s) and the finding category it is bound to. The page says the seeds are author-written. |
| `demo-manifest.json` | Fixture id, classification, schema version and the SHA-256 of each file's raw bytes. |

`README.md` is documentation and is not listed in the manifest.

## Limits

- **Findings are predictable by design.** The requirements were authored so
  that the rule-based analyzer's findings are known in advance; the test
  asserts the exact set.
- **The analyzer matches lowercase substrings.** Other wordings can trigger
  extra findings or miss real ones. For example, "authenticated" contains
  "then", which the analyzer treats as an acceptance-criteria marker, and
  "updated" contains "update", which it treats as a state-changing action.
- **The 14 findings describe this fixture only.** They say nothing about the
  analyzer's accuracy on real documents.

## Hash check

Each manifest `sha256` is the SHA-256 of the file's raw bytes, which is the
value a document version stores at upload. `.gitattributes` keeps
`demo/**` LF-normalized so the bytes, and therefore the hashes, are the same
on Windows and Linux. `apps/api/tests/test_demo_fixture.py` recomputes every
hash and fails on a mismatch, so any edit to a listed file must update the
manifest in the same change.
