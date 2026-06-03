from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, "float | None"], None]


class _ProgressHook:
    """Adapts pyannote's hook protocol to a simple progress callback.

    pyannote calls the hook as hook(step_name, step_artifact, file=None,
    total=None, completed=None). Steps that report incremental work (the long
    embeddings step) pass total/completed; single-shot steps pass neither. We
    forward a 0..1 fraction (or None when the step is not measurable) and skip
    repeat calls that resolve to the same integer percent so the UI queue is
    not flooded during the embeddings batches.
    """

    def __init__(self, callback: ProgressCallback) -> None:
        self._callback = callback
        self._last: tuple[str, int | None] | None = None

    def __call__(
        self,
        step_name: str,
        step_artifact: Any,
        file: Any = None,
        total: int | None = None,
        completed: int | None = None,
    ) -> None:
        if completed is None or not total:
            fraction: float | None = None
        else:
            fraction = max(0.0, min(1.0, completed / total))
        key = (step_name, None if fraction is None else int(fraction * 100))
        if key == self._last:
            return
        self._last = key
        self._callback(step_name, fraction)


class Diarizer:
    """Speaker diarization using pyannote.audio.

    Requires pyannote.audio to be installed (pip install 'summarizeaudio[diarization]')
    and a HuggingFace token with access to pyannote/speaker-diarization-3.1.
    """

    def __init__(self, hf_token: str) -> None:
        self._hf_token = hf_token
        self._pipeline: Any = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        log.info("Loading pyannote speaker-diarization-3.1 pipeline")
        from pyannote.audio import Pipeline  # type: ignore[import]
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=self._hf_token,
        )
        log.info("Diarization pipeline loaded")

    def label(
        self,
        audio_path: Path,
        segments: list[Any],
        num_speakers: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        """Assign speaker labels to Whisper segments and return formatted transcript.

        segments: objects with .start (float), .end (float), .text (str) —
                  as returned by faster-whisper segment iteration.
        num_speakers: if known in advance, hint the exact speaker count to pyannote
                      for more reliable clustering (optional).
        Returns lines formatted as 'Speaker 1: ...' grouped by speaker turns.
        """
        self._load()
        log.info("Running diarization on %s", audio_path.name)
        kwargs: dict[str, Any] = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers
        if progress_callback is not None:
            kwargs["hook"] = _ProgressHook(progress_callback)

        # pyannote's crop() requires an exact sample count, but MP3 decoding
        # produces slightly fewer samples than round(duration × sr) due to
        # encoder-delay padding.  Convert to a clean mono 16 kHz WAV first.
        import torchaudio  # type: ignore[import]
        waveform, sr = torchaudio.load(str(audio_path))
        if sr != 16000:
            waveform = torchaudio.functional.resample(waveform, sr, 16000)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            torchaudio.save(str(wav_path), waveform, 16000)
            result = self._pipeline(str(wav_path), **kwargs)
        finally:
            wav_path.unlink(missing_ok=True)

        annotation = result.speaker_diarization

        # Build (start, end, raw_label) turns from pyannote output
        turns: list[tuple[float, float, str]] = [
            (turn.start, turn.end, speaker)
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]

        # Map SPEAKER_00 → Speaker 1 etc. in order of first appearance
        speaker_map: dict[str, str] = {}
        counter = 1
        for _, _, sp in turns:
            if sp not in speaker_map:
                speaker_map[sp] = f"Speaker {counter}"
                counter += 1

        # Assign each Whisper segment to its dominant speaker
        labeled: list[tuple[str, str]] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            speaker = self._dominant_speaker(seg.start, seg.end, turns, speaker_map)
            labeled.append((speaker, text))

        return self._format(labeled)

    def _dominant_speaker(
        self,
        start: float,
        end: float,
        turns: list[tuple[float, float, str]],
        speaker_map: dict[str, str],
    ) -> str:
        fallback = next(iter(speaker_map.values()), "Speaker 1")
        best_speaker = fallback
        best_overlap = 0.0
        for t_start, t_end, sp in turns:
            overlap = max(0.0, min(end, t_end) - max(start, t_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker_map.get(sp, fallback)
        return best_speaker

    def _format(self, labeled: list[tuple[str, str]]) -> str:
        if not labeled:
            return ""
        lines: list[str] = []
        current_speaker, buf = labeled[0][0], [labeled[0][1]]
        for speaker, text in labeled[1:]:
            if speaker == current_speaker:
                buf.append(text)
            else:
                lines.append(f"{current_speaker}: {' '.join(buf)}")
                current_speaker = speaker
                buf = [text]
        lines.append(f"{current_speaker}: {' '.join(buf)}")
        return "\n".join(lines)
