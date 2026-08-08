PRE-HARNESS

If scope is clear, proceed without an artificial pause.

If scope is unclear or expansion is required, explain DB impact, API impact, required files, and why the additional scope is needed before editing.

---

SCOPE EXPANSION HARNESS

Prefer modifying 5 or fewer files.

If more than 5 files are required, explain why the additional files are necessary before expanding scope.

Do not split a correct root-cause fix solely to satisfy an arbitrary file count.

---

TEST HARNESS

Run relevant tests when code behavior changes.

For documentation, configuration review, or non-behavioral changes, tests may be skipped.

When tests are not run, explicitly report that they were not run.

Detailed testing rules belong in `testing.md`.

---

CONTEXT OVERFLOW HARNESS

If context becomes large:

1. Stop reading new files.
2. Do not re-analyze the repository.
3. Do not repeat completed investigation.
4. Preserve current conclusions.
5. Create a minimal task checkpoint.
6. Record only information required to continue.
7. Continue from the checkpoint.
8. Re-read only files required for the next change.

Never use repository-wide re-analysis to recover context.

---

HARNESS OVERFLOW

If harness instructions become large:

1. Keep AGENTS.md minimal.
2. Keep SKILL.md as the entry point.
3. Move detailed rules into specialized files.
4. Load only the specialized rule required by the current task.
5. Do not load every skill file for every task.
6. Do not duplicate rules between files.
7. Never delete existing safety rules to reduce context.

Load rules by task:

Authentication → google-auth.md

Database Migration → migration.md

Deployment → deployment.md

Testing → testing.md

General Workflow → prompts.md

Execution Control → harness.md

Do not load unrelated skills.

---

SESSION RECOVERY HARNESS

When a new Codex session is required:

1. Do not analyze the whole repository again.
2. Read AGENTS.md.
3. Read SKILL.md.
4. Read the latest task checkpoint.
5. Read only the specialized skill required for the task.
6. Check git status.
7. Check git diff only for relevant files.
8. Continue from Next Action.

Do not repeat completed work unless verification failed.

---

CHECKPOINT HARNESS

Before context exhaustion or session termination:

Create:
.codex/oap-task-checkpoint.md

The checkpoint must contain only:

Task

DB Impact

API Impact

Files Read

Files Changed

Completed Work

Remaining Work

Tests Run

Test Results

Known Risks

Next Action

Do not copy source code into the checkpoint.

Do not copy full logs into the checkpoint.

Do not copy conversation history into the checkpoint.

Do not include secrets.

Do not include environment variable values.

Keep the checkpoint concise.

Overwrite the previous checkpoint when continuing the same task.

Create a new checkpoint only when starting a different task.

---

TOKEN CONTROL HARNESS

To minimize Codex usage:

1. Never read the entire repository.
2. Never read all tests unless required.
3. Never read all migrations unless required.
4. Prefer targeted search before opening files.
5. Open the smallest relevant file set.
6. Do not reopen unchanged files without reason.
7. Do not repeat explanations already established.
8. Do not regenerate unchanged code.
9. Prefer diff inspection over full file inspection.
10. Stop exploration once enough evidence exists.

---

FAILURE RECOVERY HARNESS

If implementation or verification fails:

1. Preserve the current working state.
2. Identify the exact failing step.
3. Do not restart the entire task.
4. Do not revert unrelated changes.
5. Inspect only files related to the failure.
6. Fix the smallest possible scope.
7. Follow testing.md for test selection, ordering, and regression scope.

If the cause cannot be determined:

Stop modifications.

Report:

Failure

Evidence

Files Investigated

Possible Cause

Required Next File

Do not guess.

---

LOOP PREVENTION HARNESS

If the same investigation, edit, command, or test is attempted repeatedly without progress:

1. Stop the loop.
2. Do not repeat the same action a third time.
3. Record what was attempted.
4. Record the observed result.
5. Identify what new evidence is required.
6. Request or inspect only that evidence.

Never solve uncertainty by repeatedly scanning the repository.

---

STATE SAFETY HARNESS

Before continuing work after interruption:

Verify:

git status

git diff -- relevant files only

current task checkpoint

Do not assume previous commands completed successfully.

Do not discard uncommitted user changes.

Do not use git reset --hard.

Do not use git clean -fd.

Do not overwrite files unrelated to the task.

---

SECRET SAFETY HARNESS

Never print, copy, summarize, checkpoint, or commit:

.env contents

DATABASE_URL

OPENAI_API_KEY

JWT secrets

Google secrets

OAuth credentials

production passwords

cookie secrets

private keys

If secret verification is required, verify only presence or safe metadata.

Never reveal the value.

---

STOP CONDITION HARNESS

Stop work immediately when:

Required evidence is missing.

A destructive DB operation is required.

Existing user changes conflict with the task.

Migration state is inconsistent.

Production access is required.

Secrets are required.

The requested task has already been completed.

When stopped:

Do not improvise.

Do not expand scope.

Report the exact blocker and the minimum next action.

---

DYNAMIC STATE HARNESS

Project rules and current project state are different.

Never assume these values are permanent:

API endpoints
API schemas
environment variable values
CORS origins
domains
service names
migration revisions
Alembic heads
test counts
deployment state
current branch
current commit
authentication implementation state
production configuration

Before using dynamic information:

1. Identify the smallest authoritative source.
2. Read only that source.
3. Distinguish confirmed facts from inference.
4. Do not convert inference into fact.
5. Report UNKNOWN when evidence is unavailable.
6. Do not reuse stale values without verification.

---

INFERENCE SAFETY HARNESS

Always classify uncertain findings as:

CONFIRMED
INFERRED
UNKNOWN

Never report an inferred cause as confirmed.

---

CONFIGURATION SAFETY HARNESS

Before recommending configuration changes:

1. Find where the application reads the setting.
2. Determine parsing format.
3. Determine precedence.
4. Check example configuration if relevant.
5. Verify runtime configuration when possible.
6. Preserve existing values unless replacement is explicitly required.

Never assume local .env equals production configuration.

---

API CONTRACT HARNESS

Do not permanently memorize the complete API surface.

For API tasks:

1. Identify the relevant router/controller.
2. Read only the relevant endpoint.
3. Trace only required schema/service dependencies.
4. Verify the current request and response contract.
5. Compare documentation only when required.

---

ENVIRONMENT SEPARATION HARNESS

Always distinguish:

Local
Test
Production

Never infer one environment from another.

---

MCP SELECTION HARNESS

Do not use every MCP for every task.

Use only the minimum MCP required.

Route by capability: official documentation, source control, browser inspection or interaction, model and dataset references, workspace content, or database inspection. Prefer the available purpose-built MCP for that capability.

Do not invoke unrelated MCP servers.

---

MCP SAFETY HARNESS

Default external tools to read-only behavior.

GitHub:
- Read before write.
- Do not push, merge, delete, or modify repository state unless explicitly requested.

Supabase:
- Preserve read_only=true.
- Do not apply migrations or modify production data through MCP.

Notion:
- Do not edit pages unless explicitly requested.

Browser tools:
- Do not expose secrets, cookies, tokens, or sensitive page contents.

Never copy secrets into prompts, checkpoints, logs, or source files.

---

PONYTAIL COMPATIBILITY HARNESS

Do not force artificial pauses, unnecessary tests, arbitrary file-count-driven task splitting, or speculative abstractions.

Ponytail rules must not override:

security checks
database safety
API compatibility
necessary tests
user-requested scope

---

MCP FALLBACK HARNESS

If an MCP fails:

1. Do not retry repeatedly.
2. Record the exact failure.
3. Use another authoritative source only if available.
4. Do not broaden repository exploration to compensate.
5. Report the missing capability if no safe fallback exists.
