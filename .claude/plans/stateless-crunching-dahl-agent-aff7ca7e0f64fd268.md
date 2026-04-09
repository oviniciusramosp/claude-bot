# Claude Bot: Comprehensive Audit & Knowledge Base Plan

## Table of Contents
1. [Robustness Audit Report](#1-robustness-audit-report)
2. [Fix Implementation Plan](#2-fix-implementation-plan)
3. [Knowledge Base Structure](#3-knowledge-base-structure)
4. [Execution Phases](#4-execution-phases)

---

## 1. Robustness Audit Report

### Legend
- **P0 (CRITICAL)**: Causes crashes, data loss, or infinite hangs -- fix immediately
- **P1 (HIGH)**: Causes degraded operation, resource leaks, or security issues -- fix soon
- **P2 (MEDIUM)**: Causes inconsistency or poor UX -- fix in normal cycle

---

### P0 -- CRITICAL BUGS

#### BUG-01: Infinite recursion in _get_session() (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, line 2504-2513
- **Symptom**: If `self._ctx` is None or `self._ctx.session_name` is falsy, `_get_session()` calls itself unconditionally at line 2513, producing infinite recursion and a `RecursionError` crash.
- **Root cause**: The fallback case `return self._get_session()` has no base case to terminate recursion.
- **Impact**: Bot crashes whenever a routine or any code path calls `_get_session()` without a valid `_ctx`. Triggered in routine execution contexts.
- **Fix**: Replace the recursive fallback with a sensible default -- return the active session from `self.sessions`, or create/return a default session:
  ```python
  # Line 2513: Replace recursive call with:
  active = self.sessions.active
  if active and active in self.sessions.sessions:
      return self.sessions.sessions[active]
  # Last resort: create a transient default
  return self.sessions.create("default")
  ```
- **Verification**: `python3 -m py_compile claude-fallback-bot.py`. Test by triggering a routine when no context is active.

#### BUG-02: Undefined attributes in cmd_btw() (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 2018-2024
- **Symptom**: `cmd_btw()` references `self._pending_lock` and `self.pending_messages` which do not exist on `ClaudeTelegramBot`. These attributes exist on `ThreadContext` as `ctx.pending_lock` and `ctx.pending`.
- **Root cause**: `/btw` was written against an older API. The refactor to per-context pending queues was not propagated.
- **Impact**: Any use of `/btw` while Claude is running crashes with `AttributeError`.
- **Fix**: Replace with context-aware pending queue access (mirroring `_run_claude_prompt()` lines 2522-2528):
  ```python
  def cmd_btw(self, text: str) -> None:
      ctx = self._ctx
      if self.runner.running:
          if ctx:
              with ctx.pending_lock:
                  ctx.pending.append(text)
          self.send_message("Mensagem enfileirada.")
      else:
          self._run_claude_prompt(text)
  ```
- **Verification**: Send `/btw test` while Claude is processing. Verify no crash.

#### BUG-03: No timeout on urlretrieve() for file downloads (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, line 2340
- **Symptom**: `urllib.request.urlretrieve(url, str(save_path))` has no timeout. Blocks handler thread indefinitely on slow networks.
- **Impact**: Handler thread hangs permanently. Images and voice messages trigger this.
- **Fix**: Replace with `urlopen` + file write with timeout:
  ```python
  req = urllib.request.Request(url)
  with urllib.request.urlopen(req, timeout=30) as resp:
      save_path.write_bytes(resp.read())
  ```
- **Verification**: Send an image. Verify download succeeds with timeout protection.

#### BUG-04: saved.with_suffix(".wav") crashes if saved is None (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, line 2488
- **Symptom**: In `_handle_voice()` finally block, `saved.with_suffix(".wav")` called without None check. If download fails, `saved` is None, raising `AttributeError`.
- **Root cause**: `finally` always executes even after early `return` at line 2452.
- **Fix**: Guard against None:
  ```python
  finally:
      paths_to_clean = []
      if saved:
          paths_to_clean.extend([saved, saved.with_suffix(".wav")])
      for p in paths_to_clean:
          try:
              if p.exists():
                  p.unlink()
          except OSError:
              pass
  ```
- **Verification**: Test voice when download is expected to fail. Verify no crash.

#### BUG-05: No file locking on RoutineStateManager._save() (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 367-470
- **Symptom**: `_save()` does direct `write_text()` with no locking. Concurrent routines calling `set_status()` can corrupt state via interleaved load/modify/save cycles.
- **Impact**: Routine state tracking becomes inconsistent. Completed routine may show as "running" forever.
- **Fix**:
  1. Add `self._lock = threading.Lock()` in `__init__` (after line 371)
  2. Make `_save()` use atomic write (tmp + rename)
  3. Wrap `set_status()`, `set_pipeline_status()`, `set_step_status()` in `with self._lock:`
- **Verification**: Run two routines concurrently. Verify state file integrity.

#### BUG-06: Deadlock-prone _save_contexts() (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 1527, 1576-1607
- **Symptom**: `_save_contexts()` documents "Must NOT acquire _contexts_lock" but is called from `_get_context()` which holds the lock. Fragile contract that breaks with any incorrect call site.
- **Fix**: Replace `threading.Lock()` with `threading.RLock()` at line 1527. Add explicit lock in `_save_contexts()`. Move I/O (file write) outside the lock:
  ```python
  self._contexts_lock = threading.RLock()  # line 1527
  
  def _save_contexts(self) -> None:
      try:
          with self._contexts_lock:
              entries = [{"chat_id": cid, "thread_id": tid, "session_name": ctx.session_name}
                         for (cid, tid), ctx in list(self._contexts.items())]
          data = {"contexts": entries}
          tmp = CONTEXTS_FILE.with_suffix(".tmp")
          tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
          tmp.replace(CONTEXTS_FILE)
      except Exception as exc:
          logger.error("Failed to save contexts: %s", exc)
  ```
- **Verification**: Send messages from multiple topics simultaneously. Verify no deadlock.

---

### P1 -- HIGH SEVERITY

#### BUG-07: Zombie process handling in _cleanup() (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 1056-1068
- **Symptom**: `process.wait(timeout=5)` can raise `subprocess.TimeoutExpired` if process is a zombie. Exception is caught generically but process is not killed.
- **Fix**: Add explicit `TimeoutExpired` handling that escalates to SIGKILL then waits again.
- **Verification**: Test /stop on a long-running prompt. Verify process cleanup.

#### BUG-08: Pipeline workspace cleanup only on success (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 1227-1233
- **Symptom**: Failed pipelines leave `/tmp/claude-pipeline-*` directories permanently.
- **Fix**: Add deferred cleanup (24h TTL thread) for failed workspaces. Add startup cleanup of stale workspaces (>48h) in `RoutineStateManager.__init__()`.
- **Verification**: Run a failing pipeline. Confirm workspace persists temporarily. Restart bot and confirm stale workspaces cleaned.

#### BUG-09: No graceful shutdown (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 3238-3257
- **Symptom**: `stop()` only cancels running contexts. Scheduler, pipelines, and control server keep running as daemon threads.
- **Fix**: In `stop()`, also call `self.scheduler.stop()`, cancel active pipelines, and add 2-second grace period. Register SIGTERM handler in entrypoint.
- **Verification**: Send SIGTERM. Verify clean shutdown in logs.

#### BUG-10: Stream message editing has no global rate limit (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, around edit_message
- **Symptom**: Per-chat edit interval (3s) does not account for global Telegram rate limits across multiple concurrent sessions.
- **Fix**: Add global rate limiter tracking edit timestamps. Cap at 18 edits/min per chat.
- **Verification**: Run concurrent sessions. Monitor for 429 errors.

#### BUG-11: No bounds on pending message queue (Python Bot)
- **File**: claude-fallback-bot.py, ThreadContext, _run_claude_prompt, cmd_btw
- **Fix**: Add `MAX_PENDING = 20` cap. Return warning when exceeded.

#### BUG-12: Control server has no authentication (Python Bot)
- **File**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`, lines 3073-3160
- **Symptom**: Any local process can trigger routines or stop pipelines via HTTP.
- **Fix**: Generate `secrets.token_hex(16)` on startup, write to `DATA_DIR/control-token`. Require `Authorization: Bearer <token>` header. Update ClaudeBotManager to read and send token.
- **Files to modify**: claude-fallback-bot.py, AppState.swift (line 197-201)

#### BUG-13: VaultService file write atomicity (Swift App)
- **File**: `/Users/viniciusramos/claude-bot/ClaudeBotManager/Sources/Services/VaultService.swift`
- **Status**: VERIFIED OK -- No fix needed. VaultService is an `actor` which serializes all calls. All `.write(to:atomically:encoding:)` calls already use `atomically: true`.

#### BUG-14: No timeout on dry-run HTTP calls (Swift App)
- **File**: `/Users/viniciusramos/claude-bot/ClaudeBotManager/Sources/App/AppState.swift`, line 198
- **Fix**: Add `req.timeoutInterval = 10` before the URLSession call.

#### BUG-15: launchd plist crash loop potential
- **File**: `/Users/viniciusramos/claude-bot/com.vr.claude-bot.plist`
- **Fix**: Increase ThrottleInterval from 5 to 30 seconds. Add startup config validation in bot that exits cleanly (exit 0) on invalid config.

#### BUG-16: Hardcoded control port 27182
- **Files**: claude-fallback-bot.py line 77, AppState.swift line 197
- **Fix**: Make port configurable via CONTROL_PORT env var. Write bound port to `DATA_DIR/control-port`. Have Manager read from file.

#### BUG-17: No debouncing on FileWatcher (Swift App)
- **File**: `/Users/viniciusramos/claude-bot/ClaudeBotManager/Sources/Services/FileWatcher.swift`
- **Fix**: Add 500ms debounce using DispatchWorkItem cancel/reschedule pattern.

#### BUG-18: No config validation before save (Swift App)
- **File**: AppState.swift saveConfig()
- **Fix**: Validate claudePath is executable and claudeWorkspace is a directory before writing.

---

### P2 -- MEDIUM SEVERITY

#### BUG-19: No health check between Swift app and Python bot
- Add `/health` GET endpoint to control server. Poll from AppState.

#### BUG-20: ENV parsing does not handle quoted values
- Strip surrounding single/double quotes from .env values in both Python and Swift parsers.

#### BUG-21: Pipeline DAG cycle detection incomplete
- Add topological sort check before DAG loop starts. Fail fast with clear error.

#### BUG-22: Routine frontmatter validation missing
- Validate required fields (schedule.times, type) before enqueuing.

#### BUG-23: Menu bar refresh cadence
- 15-second timer is adequate. Consider push-based refresh via control server in future.

#### BUG-24: Agent ID not validated
- Add regex validation `^[a-z0-9]+(-[a-z0-9]+)*$` in both Python and Swift.

#### BUG-25: Timer leaks on app exit (Swift App)
- Invalidate statusTimer and usageTimer in a shutdown method.

#### BUG-26: Log parsing fragile (Swift App)
- Add multiple date format fallbacks in LogService.

#### BUG-27: No app-level logging in Swift app
- Add `os.Logger` usage in key services.

---

## 2. Fix Implementation Plan

### Phase 0: P0 Critical Fixes

**Estimated time**: 1-2 hours
**Files to modify**: `/Users/viniciusramos/claude-bot/claude-fallback-bot.py` only

Execute in this order (each fix is independent):

| Step | Bug | Lines | Change Summary |
|------|-----|-------|----------------|
| 0.1 | BUG-01 | 2513 | Replace recursive call with fallback to active session |
| 0.2 | BUG-02 | 2018-2024 | Replace self._pending_lock/self.pending_messages with ctx.pending_lock/ctx.pending |
| 0.3 | BUG-03 | 2340 | Replace urlretrieve with urlopen+write+timeout=30 |
| 0.4 | BUG-04 | 2486-2493 | Add None guard before saved.with_suffix(".wav") |
| 0.5 | BUG-05 | 367-470 | Add threading.Lock + atomic write to RoutineStateManager |
| 0.6 | BUG-06 | 1527, 1576-1607 | Change to RLock, add explicit locking in _save_contexts |

**Validation after Phase 0:**
1. `python3 -m py_compile claude-fallback-bot.py`
2. Start bot locally (`python3 claude-fallback-bot.py`)
3. Send a text message -- verify response
4. Send `/btw test` while processing -- verify enqueued
5. Send an image -- verify download and analysis
6. Run a routine via control server -- verify completion
7. Commit: `fix: resolve 6 critical bugs (recursion, btw attrs, timeouts, file locking)`

### Phase 1: P1 High-Severity Fixes

**Estimated time**: 2-3 hours
**Files to modify**: claude-fallback-bot.py, AppState.swift, FileWatcher.swift, com.vr.claude-bot.plist

| Step | Bug | File | Change Summary |
|------|-----|------|----------------|
| 1.1 | BUG-07 | claude-fallback-bot.py:1056-1068 | Add TimeoutExpired handling + SIGKILL escalation |
| 1.2 | BUG-08 | claude-fallback-bot.py:1227-1233 | Add deferred cleanup + startup stale workspace purge |
| 1.3 | BUG-09 | claude-fallback-bot.py:3238-3257 | Graceful shutdown: stop scheduler, cancel pipelines, SIGTERM handler |
| 1.4 | BUG-10 | claude-fallback-bot.py:edit_message area | Add global rate limiter (18/min per chat) |
| 1.5 | BUG-11 | claude-fallback-bot.py:multiple | Add MAX_PENDING=20 cap |
| 1.6 | BUG-12 | claude-fallback-bot.py:3073-3160, AppState.swift:197 | Add Bearer token auth to control server |
| 1.7 | BUG-14 | AppState.swift:198 | Add req.timeoutInterval = 10 |
| 1.8 | BUG-15 | com.vr.claude-bot.plist, claude-fallback-bot.py | ThrottleInterval=30, startup config validation |
| 1.9 | BUG-16 | claude-fallback-bot.py:77, AppState.swift:197 | Configurable control port via env var + file |
| 1.10 | BUG-17 | FileWatcher.swift | Add 500ms debounce |
| 1.11 | BUG-18 | AppState.swift:saveConfig | Add path/directory validation |

**Validation after Phase 1:**
1. `python3 -m py_compile claude-fallback-bot.py`
2. `cd ClaudeBotManager && swift build`
3. Full integration test: start/stop bot, dry-run routine, concurrent messages, SIGTERM test
4. Commit: `fix: 11 high-severity fixes (shutdown, rate limits, auth, validation)`

### Phase 2: P2 Medium-Severity Fixes

**Estimated time**: 1-2 hours

Batch into 2-3 commits. See BUG-19 through BUG-27 above for details.

### Phase 3: Knowledge Base Generation

**Estimated time**: 2-3 hours
**Prerequisite**: Phase 0 and Phase 1 complete (API changes affect documented interfaces)

| Step | File | Source Material |
|------|------|----------------|
| 3.1 | docs/README.md | Overview from README.md, links to other docs |
| 3.2 | docs/architecture.md | CLAUDE.md, source code class definitions |
| 3.3 | docs/installation.md | README.md setup section, claude-bot.sh |
| 3.4 | docs/configuration.md | .env.example, CLAUDE.md config section, source constants |
| 3.5 | docs/development.md | CLAUDE.md development section |
| 3.6 | docs/sessions-and-agents.md | Session/Agent classes, commands, vault structure |
| 3.7 | docs/routines-and-pipelines.md | RoutineScheduler, PipelineExecutor, state format |
| 3.8 | docs/audio-and-images.md | _handle_voice, _handle_photo, dependencies |
| 3.9 | docs/troubleshooting.md | Common failure modes from audit |
| 3.10 | docs/api-reference.md | Control server, JSON schemas |

After docs are generated, update CLAUDE.md to add a pointer: "For comprehensive documentation, see `docs/`."

---

## Appendix: Key Line References

Quick reference for implementors:

| Area | File | Lines |
|------|------|-------|
| _get_session recursion | claude-fallback-bot.py | 2504-2513 |
| cmd_btw undefined attrs | claude-fallback-bot.py | 2018-2024 |
| urlretrieve no timeout | claude-fallback-bot.py | 2340 |
| wav cleanup NoneType | claude-fallback-bot.py | 2486-2493 |
| RoutineStateManager._save | claude-fallback-bot.py | 413-415 |
| _contexts_lock definition | claude-fallback-bot.py | 1527 |
| _save_contexts | claude-fallback-bot.py | 1576-1592 |
| _get_context (holds lock) | claude-fallback-bot.py | 1594-1607 |
| ClaudeRunner._cleanup | claude-fallback-bot.py | 1056-1068 |
| Pipeline workspace cleanup | claude-fallback-bot.py | 1227-1233 |
| bot.stop() | claude-fallback-bot.py | 3238-3245 |
| Control server | claude-fallback-bot.py | 3073-3160 |
| CONTROL_PORT constant | claude-fallback-bot.py | 77 |
| ThreadContext dataclass | claude-fallback-bot.py | 1146-1165 |
| PipelineExecutor | claude-fallback-bot.py | 1173-1420 |
| RoutineScheduler | claude-fallback-bot.py | 489-564 |
| AppState dryRun | AppState.swift | 192-209 |
| FileWatcher | FileWatcher.swift | 1-28 |
| launchd plist | com.vr.claude-bot.plist | 1-51 |
