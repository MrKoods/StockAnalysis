# How every role works (short - read it every run)

- You run unattended. Nobody can answer questions. Do the job, write your files, stop.
- **Be economical**: your runs share the user's Claude plan. Read `state/context.md` first - it says why you were
  woken. Read only what that needs. Prefer grep/tail-sized reads over whole files. Stop when the job is done.
- Your working directory is the team folder `C:\Users\user\Documents\Git\StockAnalysis-Team`. Use relative paths.
  Live folders (V2 `StockAnalysis`, V3 `StockAnalysis-V3`, V4 `StockAnalysis-V4`) are read-only for you.
- Your shell already starts in the team folder. Run commands **plain and alone**, exactly like
  `python tools/ideas.py list` - never `cd ... &&`, pipes, `2>&1` or `python -c` (those are refused even when the
  command itself is allowed). Read files with the Read tool, not Bash.
- A refused tool means your permission file forbids it. If a refused command matters to your job, retry it once
  in the plain form above; if it is still refused, say so in your outbox with the exact command.
- Your memory is `notes/<your role>.md`: read it at the start, update it at the end (keep it under ~150 lines;
  prune old entries). Put what you checked, what to watch, and anything the next run must not redo.
- The user reads Discord on a phone. `outbox/<your role>.txt` is posted for you: max 1,200 characters, plain
  text, first line = the headline, no tables. Say plainly what matters and what (if anything) the user must do.
  Write the outbox file last, only when the run's work is done - the dispatcher treats it as "finished".
- Ops alerts in `state/context.md` were already posted - don't repeat them.
- Dates: Pacific time. Markets: NYSE. "Today" is in the prompt.
