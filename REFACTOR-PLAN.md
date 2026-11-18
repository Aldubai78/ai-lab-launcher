# AI Lab Launcher Refactor Plan

**Date:** 2026-09-08  
**Decision:** Claude's hybrid — extract pure logic, add state boundary, ship API, skip GUI splitting.

## Steps

| Step | What | Why |
|------|------|-----|
| 0 | Git branch + commit current state | Real safety net, not backup files |
| 1 | Swap ad-hoc file writes for `logging` module | Observability during the refactor (~20 min) |
| 2 | Extract `tmux_manager.py` — start/stop/kill/capture/health subprocess calls | Pure logic, biggest single win, zero UI deps |
| 3 | Extract `gpu_monitor.py` — polling thread only (UI sync stays in LauncherApp) | Pure, trivial, already separated from rendering |
| 4 | Introduce `AppState` with subscribe/mutate + move `ServiceState` to `state.py` | Single source of truth, enables API without Tk thread-safety nightmares |
| 5 | Add `http_api.py` — Flask daemon thread on 127.0.0.1, endpoints talk only to AppState | **Deliver the actual feature** — Doug controls launcher remotely |

No GUI splits. No extraction theater for its own sake. Clean architecture underneath a fat file, plus you get what you actually want.

## Acceptance Test

Can `http_api.py` start, stop, and query every service while importing nothing from `gui/`? If yes, we're done.

---

# Obituary — 2026-09-11

**Status:** FAILED. Refactor reverted to git baseline `4964cdb` (monolithic launcher.py).

## What Was Done

| Time | Action |
|------|--------|
| ~11:37 | Extracted `tmux_manager.py` — standalone class for start/stop/kill/health/capture/list_sessions |
| ~11:40 | Extracted `gpu_monitor.py` — standalone nvidia-smi polling with thread management |
| ~11:43 | Replaced ~150 lines of tmux subprocess calls in launcher.py with TmuxManager; removed GPU polling thread |
| ~11:50 | Created `state.py` + `app_state.py`; replaced 30+ `service_states[key]` usages with dict-like access |
| ~12:00 | Created `http_api.py` — Flask server on port 5555; wired HttpApiThread into launcher.py init/close |
| ~12:07 | **Bug #1 discovered:** TmuxManager wrapped all tmux calls in `wsl -d Ubuntu-22.04 -- tmux` while already inside WSL2. Created `launcher_api.py` (headless server on port 5556) to bypass Windows GUI loopback isolation. Fixed `_tmux_cmd()` with `_detect_inside_wsl()` |
| ~12:17 | **Bug #2 discovered:** GUI had separate AppState from API — two instances, no sync. Rewrote ApiSyncThread to use `root.after()` for safe Tkinter UI updates |
| ~12:35 | **Bug #3 discovered:** HttpApiThread accessed `.already_running` on TmuxResult (didn't exist). Fixed by removing the attribute |
| ~12:40 | **Bug #4 discovered:** Expanded panels clipped, buttons not updating. Root cause: mixing `pack()` and `grid()` in `_expanded_zone`/`_collapsed_zone`. Fixed by converting to `grid()` throughout |
| ~12:50 | **Bug #5 discovered:** Expanded panels appeared in wrong positions; sync thread overwrote GUI state immediately after user clicks. Introduced ApiSyncThread as background daemon + cooldown mechanism (3s) to prevent overwrite loops |
| ~13:00 | **Bug #6 discovered:** Cooldown mechanism was fundamentally broken — `_auto_detect_running_services` called `_toggle_collapse` on startup, setting `_last_user_action` timestamps that prevented the sync thread from ever applying API changes. Stripped all cooldown logic. Removed `_notify_api()` — GUI now controls tmux directly |
| ~13:05 | **Reverted to git baseline `4964cdb`.** All extracted modules deleted. Broken launcher backed up to `dougs_backups/launcher.py.bak-2026-09-11-final-mess`.

## Why It Was Done

The original goal was reasonable:
- Decouple UI from subprocess calls (tmux, nvidia-smi)
- Add headless API for remote control (from WSL2, bypassing Windows GUI loopback)
- Introduce AppState as single source of truth with subscribe/mutate pattern

These are all good architectural goals. The problem wasn't the destination — it was the execution.

## Where It Went Wrong

### 1. Two AppStates in Flight
The GUI launcher and the headless API server each had their own `AppState` instance. They were never in sync about who controlled what. Clicks in GUI → GUI's AppState → tmux. HTTP POST to API → API's AppState → tmux. Two masters, one process.

### 2. Bidirectional Sync That Broke Both Directions
The sync thread polled the API and pushed changes back to GUI. GUI clicks pushed changes forward to API. The push-pull relationship created a race condition: API state changes arrived via sync thread at the exact moment the user clicked, overwriting their action. The cooldown was a band-aid that didn't reach the wound — startup auto-detection set timestamps that blocked all future sync updates.

### 3. `_auto_detect_running_services` on Startup
This method called `_toggle_collapse` for every running service during GUI init, setting `_last_user_action` timestamps. The sync thread saw these as "user just acted" and skipped applying API state. Result: the GUI showed stale collapsed state forever after startup.

### 4. Incremental Patches on a Moving Target
Each bug fix was an edit to an already-edited file. No intermediate test passes. No commits. Just layer after layer of partial fixes on top of broken assumptions. The TmuxManager WSL detection fix (`_detect_inside_wsl`) was correct but only addressed one symptom — the underlying AppState duplication remained.

### 5. Geometry Manager Mixing
Tkinter's `pack()` and `grid()` cannot coexist in the same parent hierarchy. `_expanded_zone` used `pack()` while its children used `grid()`. This caused panels to render at wrong sizes and positions — a Tkinter fundamental, not an app logic bug.

### 6. The Headless API Was the Wrong Abstraction
The real problem was GUI-in-WSL2 can't control Windows-side tmux. The solution wasn't "build an API server that runs in WSL2 and talks to AppState." The solution is simpler: either run tmux on the Windows side, or have the GUI talk to tmux directly (which it was already doing before we extracted everything). The API server added a whole extra layer of indirection with no clear ownership.

## Lessons for Next Time

### 1. ONE COMMIT PER STEP
Each refactoring step should be a git commit. If a step breaks things, `git checkout` back to the last good commit — not `cp` to a backup folder and pray. Git is the safety net; backup files are the band-aid.

### 2. TEST EACH STEP IN ISOLATION
Before moving to Step N+1, verify Step N works end-to-end: restart the launcher, click every button, check every panel. Don't chain 6 incremental patches without verifying any of them.

### 3. ONE STATE OWNER
There must be exactly one `AppState` instance that controls tmux. If you need remote access, the API talks to the SAME AppState — not a separate copy. Two AppStates = two sources of truth = inevitable conflict.

### 4. KEEP IT SIMPLE FIRST
The original launcher.py was monolithic but it worked. Before extracting modules, ask: "What's the simplest change that solves the problem?" Building a headless API server + sync thread + cooldown mechanism is the opposite of simple. A simpler path would have been: fix the tmux path issue in the existing code, test, then consider whether an API layer is actually needed.

### 5. VERIFY TKINTER GEOMETRY EARLY
Mixing `pack()` and `grid()` is a Tkinter gotcha that causes silent rendering failures. If you're refactoring UI layout, test geometry managers after each change — don't wait until the end.

### 6. DON'T CONFUSE EXTRACTING WITH IMPROVING
Extracting code into separate files doesn't make it better. It makes it modular. If the original code worked and the extracted version doesn't, you haven't improved anything — you've just made bugs harder to find.

### 7. USER CONFIRMATION BEFORE BIG CHANGES
Before introducing a headless API server, sync threads, cooldown mechanisms, and bidirectional state management: present the plan to Allen, get confirmation, and execute one step at a time with testing between each step.

## What We Learned

- TmuxManager must detect when it's already inside WSL and call `tmux` directly (not `wsl -d Ubuntu-22.04 -- tmux`)
- Tkinter requires a single geometry manager per parent hierarchy
- Two separate AppState instances controlling the same tmux sessions is a fundamental design error
- Bidirectional sync with cooldown is fragile; unidirectional pull or direct control is more reliable
- `_auto_detect_running_services` calling `_toggle_collapse` on startup is a latent bug waiting for any timestamp-based mechanism to break it

## Current State (2026-09-11 ~13:05)

Clean git baseline `4964cdb`. Monolithic `launcher.py`. No extracted modules. No API server. Works as it did before today.

The refactor is not dead — the goals are still valid. But the approach needs to change:
1. One step at a time, each committed and tested
2. Single AppState instance, shared by GUI and any future API
3. Simple changes first, complex abstractions only when proven necessary
4. User confirmation before introducing new architectural layers
