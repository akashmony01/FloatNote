"""`floatnote bench`: pick a speech model using your own voice on this machine.

  floatnote bench record   # read a few sample bug notes aloud (saved as WAV)
  floatnote bench run      # time every model on those clips, show accuracy

Each model runs in its own process so the memory numbers are clean.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import config, paths

SENTENCES = [
    "The navbar overlaps the hero image on mobile, and the hamburger menu doesn't open when I tap it.",
    "When I submit the signup form with an empty email, the button spins forever and nothing shows in the console.",
    "On the pricing page in dark mode, the text on the Pro card is almost invisible.",
    "The useEffect in the dashboard runs twice and calls the Supabase API two times, so the second request returns a 404.",
    "Idea: add a keyboard shortcut that exports all my notes as a markdown file.",
]

# (model, beam_size)
CANDIDATES = [
    ("base.en", 1),
    ("base.en", 5),
    ("distil-small.en", 1),
    ("small.en", 1),
    ("small.en", 5),
]


def bench_dir() -> Path:
    return paths.data_dir() / "bench"


# ---- recording -------------------------------------------------------------

def record(count: int) -> int:
    from .recorder import Recorder, save_wav

    out = bench_dir()
    out.mkdir(parents=True, exist_ok=True)
    rec = Recorder()
    print("Read each sentence aloud at your normal speed, like you would while testing.\n")
    for i, sentence in enumerate(SENTENCES[:count], 1):
        print(f"[{i}/{count}] \"{sentence}\"")
        input("    Press Enter, then speak... ")
        rec.start()
        input("    Recording. Press Enter when done. ")
        audio = rec.stop()
        wav = out / f"clip{i}.wav"
        save_wav(wav, audio)
        wav.with_suffix(".txt").write_text(sentence + "\n")
        print(f"    saved {wav} ({len(audio) / 16000:.1f}s)\n")
    print("Done. Now run: floatnote bench run")
    return 0


# ---- accuracy ---------------------------------------------------------------

def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = _words(reference), _words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


# ---- running ---------------------------------------------------------------

def _rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def _worker(model: str, beam: int, files: list[str]) -> None:
    """Child process: load one model, transcribe files, print JSON."""
    from .transcriber import Transcriber

    cfg = config.load(create=False)
    t = time.perf_counter()
    tr = Transcriber(model, cfg.compute_type, beam, cfg.vocabulary)
    load_s = time.perf_counter() - t
    tr.transcribe(files[0])  # warm-up, not timed
    clips = []
    for f in files:
        r = tr.transcribe(f)
        clips.append({"file": f, "text": r.text, "audio_s": r.audio_seconds, "elapsed_s": r.elapsed_seconds})
    print(json.dumps({"model": model, "beam": beam, "load_s": load_s, "rss_mb": _rss_mb(), "clips": clips}))


def run(files: list[str] | None = None, candidates=CANDIDATES) -> int:
    paths_ = [Path(f) for f in files] if files else sorted(bench_dir().glob("clip*.wav"))
    if not paths_:
        # Fall back to your recent real notes (no script, so no error rate).
        paths_ = sorted(paths.recordings_dir().glob("*.wav"))[-5:]
        if paths_:
            print(f"Using your {len(paths_)} most recent recordings from {paths.recordings_dir()}")
    if not paths_:
        print("No clips found. Record some notes first, or run: floatnote bench record", file=sys.stderr)
        return 1
    refs = {p: p.with_suffix(".txt").read_text().strip() if p.with_suffix(".txt").exists() else None
            for p in paths_}
    print(f"Benchmarking {len(candidates)} setups on {len(paths_)} clip(s). This takes a minute or two.\n")

    results = []
    for model, beam in candidates:
        print(f"  {model} beam={beam} ...", end="", flush=True)
        proc = subprocess.run(
            [sys.executable, "-m", "floatnote.bench", "_worker", model, str(beam), *map(str, paths_)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(" failed")
            print("   ", (proc.stderr.strip().splitlines() or ["?"])[-1])
            continue
        r = json.loads(proc.stdout.strip().splitlines()[-1])
        audio = sum(c["audio_s"] for c in r["clips"])
        elapsed = sum(c["elapsed_s"] for c in r["clips"])
        r["per10s"] = elapsed / audio * 10 if audio else 0
        r["worst_s"] = max(c["elapsed_s"] for c in r["clips"])
        scored = [word_error_rate(refs[Path(c["file"])], c["text"]) for c in r["clips"] if refs[Path(c["file"])]]
        r["wer"] = sum(scored) / len(scored) if scored else None
        results.append(r)
        print(" done")

    print(f"\n{'setup':<22}{'RAM':>8}{'load':>7}{'per 10s':>9}{'slowest':>9}{'errors':>8}")
    for r in results:
        wer = f"{r['wer'] * 100:.0f}%" if r["wer"] is not None else "-"
        print(f"{r['model'] + ' b' + str(r['beam']):<22}{r['rss_mb']:>6.0f}MB{r['load_s']:>6.1f}s"
              f"{r['per10s']:>8.2f}s{r['worst_s']:>8.2f}s{wer:>8}")
    print("\n'per 10s' = time to transcribe 10 seconds of speech. 'errors' = word error rate vs the script.\n")

    for i, p in enumerate(paths_):
        print(f"--- {p.name}" + (f": {refs[p]}" if refs[p] else ""))
        for r in results:
            print(f"  {r['model'] + ' b' + str(r['beam']):<20} {r['clips'][i]['text']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "_worker":
        _worker(sys.argv[2], int(sys.argv[3]), sys.argv[4:])
