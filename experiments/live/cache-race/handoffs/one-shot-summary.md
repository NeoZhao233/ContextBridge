# Agent B Handoff — Profile-Cache Commit Boundary

**Decision.** `ProfileService.update` (resume_fixture/profile_cache.py) originally popped the cache *before* `store.commit`. Commit is the durability point; on `CommitError` the store kept the old value while the still-correct cache entry had already been discarded — cache/store disagreement plus lost work. Chosen boundary: **commit first; invalidate only after success; on `CommitError`, leave the cache untouched and re-raise.** Rationale documented in `update`'s docstring (~lines 23–31); no separate docs file, since the repo has no docs convention.

**Implementation state.** Success path done: `store.commit(...)` runs inside `try`, cache `pop` moved after it, executing only after commit returns. Failure path deliberately unfinished: the `except CommitError:` handler still calls `self.cache.pop(...)`, flagged `TODO(commit-boundary)` — the handler must not touch `self.cache` at all and should only re-raise. Working tree holds one modified file; nothing committed.

**Files.** `resume_fixture/profile_cache.py` (modified); `tests/test_profile_cache.py` (acceptance tests).

**Test state.** Not run — all suite commands required approval. Static trace: success test passes; `test_failed_commit_keeps_cached_value` fails (handler emptied cache → `KeyError` after re-raise). Expected 1/2. Grep confirms `ProfileService`/`ProfileStore` appear only in these two files.

**Continuing constraints.** Work only in this repo; do not commit; keep the documented commit-boundary decision intact.

**Next change.** Delete the `self.cache.pop(...)` from the `except CommitError:` handler so the failure path only re-raises; failed commits then leave `cache["user-1"] == "old"`. Re-run the suite for 2/2.
