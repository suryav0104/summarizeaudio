# SummarizeAudio Backlog

Ranked from highest to lowest impact.

## 1. Tighten the summarization prompt and output constraints
- Add a stricter prompt template with a required structure.
- Reduce verbosity and force more specific bullets.
- Add anti-hallucination instructions and a stronger instruction hierarchy.

## 2. Add a quality mode and model selection UI
- Expose model choice in the app instead of only config files.
- Add a fast vs high-quality toggle.
- Prefer a stronger model when hardware allows it.

## 3. Add transcript chunking for long inputs
- Split long transcripts into chunks before summarizing.
- Summarize each chunk, then synthesize a final summary.
- Preserve more detail for long meetings and transcripts.

## 4. Validate and normalize model output before saving
- Ensure the summary contains the expected sections.
- Trim excessive repetition or rambling.
- Optionally reject obviously malformed output.

## 5. Add transcript-quality regression tests
- Add a known 20+ sentence fixture.
- Compare output shape and key facts.
- Catch prompt regressions before release.

## 6. Improve the summarization UX with progress and cancellation
- Show a visible processing state while the model runs.
- Add a cancel option for long jobs.
- Make the app feel less frozen during heavy work.

## 7. Reduce noise and improve the output experience
- Add a summary preview.
- Add an "open folder" action.
- Add a lightweight history view for past runs.

## 8. Make recorder and transcription settings more explicit
- Expose device selection in the UI.
- Expose language and model settings in the UI.
- Reduce dependence on editing config files by hand.

## 9. Improve performance for large local audio files
- Improve model loading feedback and caching.
- Surface hardware-aware defaults more clearly.
- Consider optional GPU acceleration when available.

## 10. Clean up cross-platform and documentation drift
- Keep README, example config, and installers in sync.
- Generate shared defaults from one source of truth.
- Reduce confusion between macOS and Windows setup paths.
