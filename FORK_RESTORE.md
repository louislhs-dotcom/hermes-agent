# Hermes Agent — Fork & Local State Documentation

> **Purpose:** A complete record of the fork, the local repo, and the custom
> files, so the setup can be restored if the local copy is destroyed.
> **Last updated:** 2026-08-18
> **Author:** Louis Ling

---

## 1. The two remotes

| Remote | URL | Role |
|---|---|---|
| `origin` | `git@github.com:NousResearch/hermes-agent.git` | Upstream (read-only, no push) |
| `fork` | `git@github.com:louislhs-dotcom/hermes-agent.git` | Personal fork (push access) |

---

## 2. Local repo

- **Path:** `/Users/louisling/.hermes/hermes-agent`
- **Current branch:** `main`
- **Local `main` head:** `5c8d3a810140e007c89746aa18024b7a347ef2b8`
  - `fix(persist): skip empty assistant/user stubs at the write boundary to prevent transcript poisoning`
  - Tracks `origin/main`, **ahead 5** (5 local commits not yet on upstream).

### The 5 local commits on `main` (not on upstream)

| Commit | Description |
|---|---|
| `5c8d3a810` | Persist-time empty-payload guard (skip empty assistant/user stubs at write boundary) |
| `ab8ee83d8` | Wire SkillOpt-validated sections live: destructive-actions carve-out, right-sizing |
| `450c0e512` | Add verify-before-claim guard: never report unverified results |
| `ee78db534` | Add universal conciseness guidance: 1-3 sentence answers, no re-approval, token-cost awareness |
| `67fc2f002` | Harden Hermes stable-tier prompt: exact tool names, memory/skill split, skill reload, skill-bloat trigger |

---

## 3. Fork branches (as of 2026-08-18)

### `fork/main`
- **Head:** `0c9d2eda9236badc6b883b0735c0d63463f6eb30`
- **Status:** STALE / heavily diverged from local `main`. Merge base is
  `126ff7071` (#75448). fork/main is ~1,200 commits behind local main; a merge
  produces **313 conflicts** across the whole tree. **Do not merge this into
  local main.**
- **Contains the custom files** (see §4) via commit `e26d5db23`.

### `louis-main` (created 2026-08-18)
- **Head:** `5c8d3a810140e007c89746aa18024b7a347ef2b8` (identical to local `main`)
- **Status:** This is the **safe backup of the live codebase**. Pushed from
  local `main` on 2026-08-18. Contains all 5 local commits.
- **PR link:** `https://github.com/louislhs-dotcom/hermes-agent/pull/new/louis-main`

> **Restore path:** If the local copy is destroyed, `louis-main` on the fork is
> the authoritative copy of the live code. Clone the fork and check out
> `louis-main`, or `git fetch fork louis-main` then reset local `main` to it.

### Other fork branches
The fork has many other branches (UI, add-morph-snapshot, atropos-*, austin/*,
bb/*, etc.). These are upstream/experimental branches — not part of the
restore-critical state. Full list via `git ls-remote --heads fork`.

---

## 4. Custom files (the "restore custom files" set)

These are Louis's custom additions tracked on `fork/main` in commit
`e26d5db23` ("Restore custom files: tencentdb client, claude-flow, codegraph,
swarm, ruvector db, ruflo workflows, etc."). **They also exist locally as
untracked files** (backed up to `/tmp/hermes_merge_backup/` on 2026-08-18).

### 4a. Runtime state (untracked locally, live on disk)
| Path | Notes |
|---|---|
| `.claude-flow/agents/store.json` | Claude-flow agent state |
| `.claude-flow/daemon-state.json` | Claude-flow daemon state |
| `.claude-flow/policy/state.json` | Claude-flow policy state |
| `.claude-flow/swarm/swarm-state.json` | Claude-flow swarm state |
| `.swarm/memory.db` (+ `-shm`, `-wal`) | Swarm memory SQLite DB |
| `.swarm/model-router-state.json` | Swarm model router state |
| `.swarm/schema.sql` | Swarm DB schema |
| `claude-flow.config.json` | Claude-flow config |

### 4b. Code / plugins / skills (tracked on fork/main)
| Path | Notes |
|---|---|
| `tools/tencentdb_client.py` | TencentDB client (568 lines) |
| `plugins/memory/memory_tencentdb_v2/` | TencentDB memory provider plugin (README, `__init__.py`, `plugin.yaml`, tests) |
| `scripts/push_ruflo_to_tencentdb.py` | Push ruflo to TencentDB |
| `scripts/verify_tencentdb_setup.sh` | Verify TencentDB setup |
| `skills/ruflo-workflows/` | Ruflo workflows skill (SKILL.md, references, scripts) |
| `tests/test_tencentdb_client_decay.py` | TencentDB client test |
| `tests/test_tencentdb_v2_provider_integration.py` | TencentDB provider integration test |
| `tests/skills/test_ruflo_workflows_skill.py` | Ruflo skill test |
| `ruvector.db` | Ruvector DB (binary) |
| `.codegraph/.gitignore` | Codegraph gitignore |

> **Note:** The `.claude-flow/`, `.swarm/`, and `claude-flow.config.json` files
> are **untracked locally** (they're live runtime state). The code/plugin/skill
> files in §4b are **tracked on fork/main** but are also present locally.

---

## 5. Backup taken 2026-08-18

During the merge attempt, the 10 runtime-state files were backed up to:
```
/tmp/hermes_merge_backup/
  .claude-flow/agents/store.json
  .claude-flow/daemon-state.json
  .claude-flow/policy/state.json
  .claude-flow/swarm/swarm-state.json
  .swarm/memory.db
  .swarm/memory.db-shm
  .swarm/memory.db-wal
  .swarm/model-router-state.json
  .swarm/schema.sql
  claude-flow.config.json
```
These were restored to the working tree after the merge was aborted.

---

## 6. Restore procedures

### If the local repo is destroyed
1. Clone the fork: `git clone git@github.com:louislhs-dotcom/hermes-agent.git`
2. Check out the live code: `git checkout louis-main`
3. Re-add upstream: `git remote add origin git@github.com:NousResearch/hermes-agent.git`
4. Restore the custom runtime files from `fork/main` if needed:
   `git checkout fork/main -- .claude-flow .swarm claude-flow.config.json`
   (or restore from `/tmp/hermes_merge_backup/` if still present).

### If you need the custom code/plugin/skill files
They're on `fork/main` (commit `e26d5db23`) and locally. To pull them from the
fork onto any branch:
```bash
git checkout fork/main -- tools/tencentdb_client.py \
  plugins/memory/memory_tencentdb_v2 scripts/push_ruflo_to_tencentdb.py \
  scripts/verify_tencentdb_setup.sh skills/ruflo-workflows \
  tests/test_tencentdb_client_decay.py \
  tests/test_tencentdb_v2_provider_integration.py \
  tests/skills/test_ruflo_workflows_skill.py ruvector.db .codegraph/.gitignore
```

---

## 7. Key hashes (quick reference)

| Item | Hash |
|---|---|
| Local `main` / `louis-main` head | `5c8d3a810140e007c89746aa18024b7a347ef2b8` |
| `fork/main` head | `0c9d2eda9236badc6b883b0735c0d63463f6eb30` |
| Merge base (main ↔ fork/main) | `126ff7071b6b755055879648f4e859b3187d0fac` |
| Custom-files commit on fork/main | `e26d5db237977201125a2c3a9f696594c7a5b7ad` |
| Build-log commit on fork/main | `0c9d2eda9` (also fork/main head) |
