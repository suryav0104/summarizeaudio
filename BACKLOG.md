# SummarizeAudio Backlog

Ranked from highest to lowest impact.

## [Done] 1. Tighten the summarization prompt and output constraints
- Done. The prompt is now stricter, more explicit, and mirrored into the installer and example config.
- Keep an eye on real-world outputs and refine further if users still report weak summaries.

## [Done] 2. Add a quality mode and model selection UI
- Done. The tray menu now exposes fast/high model choices and persists the selection.
- Revisit if you want a third "auto" option or a richer settings panel later.

## [Done] 3. Polish the tray icon visuals
- Done. The tray icons were updated to a more polished branded treatment and regenerated for the app bundle.
- Revisit if you want alternate icon variants, darker-light modes, or a different visual direction.

## [Done] 4. Add transcript chunking for long inputs
- Done. Long transcripts (>8,000 chars) are split into ~6,000-char chunks with 500-char overlap, each chunk summarized separately, then consolidated into a final summary.

## [Done] 5. Validate and normalize model output before saving
- Removed. Validation was implemented then intentionally disabled — the model output is now written as-is. Re-evaluate if output quality becomes a recurring problem.

## [Done] 6. Add transcript-quality regression tests
- Add a known 20+ sentence fixture.
- Compare output shape and key facts.
- Catch prompt regressions before release.

## [Done] 7. Improve the summarization UX with progress and cancellation
- Show a visible processing state while the model runs.
- Add a cancel option for long jobs.
- Make the app feel less frozen during heavy work.

## 8. Reduce noise and improve the output experience
- Add a summary preview.
- Add an "open folder" action.
- Add a lightweight history view for past runs.

## 9. Make recorder and transcription settings more explicit
- Expose device selection in the UI.
- Expose language and model settings in the UI.
- Reduce dependence on editing config files by hand.

## 10. Improve performance for large local audio files
- Improve model loading feedback and caching.
- Surface hardware-aware defaults more clearly.
- Consider optional GPU acceleration when available.

## 11. Clean up cross-platform and documentation drift
- Keep README, example config, and installers in sync.
- Generate shared defaults from one source of truth.
- Reduce confusion between macOS and Windows setup paths.
