# Source-refresh offline fixtures

Inputs for [`../../scripts/check_refresh_sources.py`](../../scripts/check_refresh_sources.py),
so the refresh tool's analysis can be tested without touching the network.

`snapshot.json` is a synthetic capture in the shape `refresh_sources.py capture`
produces. The **URLs are the registry's real ones**, because that is what the
matching logic must handle; everything else — statuses, validators, redirects,
link text, the hub page in `hub.html` — is invented for this fixture. No
official page content, document body, or excerpt is reproduced here, and none
should ever be added: real captures are written to the git-ignored
`skill/.local/refresh-reports/` precisely so third-party text stays out of this
repository.

The snapshot is arranged so every network-derived finding the analyzer can emit
is reachable offline: a healthy source, one that redirects, one that 404s, one
whose validators changed while its registry version did not, one the capture
missed entirely, and a hub link no registry entry covers. `check_refresh_sources.py`
fails if any of those stops being exercised — a refresh tool that has quietly
gone blind to a failure mode looks exactly like a clean run.

Registry-hygiene findings are not fixtured. They are produced by mutating a
copy of the real registry in memory inside the check, so a broken-registry
fixture never sits on disk where it could be mistaken for the real one.
