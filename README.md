# Reddit → PDF (reddit.com old.reddit.com or RedLib Mirrors)

Scrape entire Sub-Reddits into PDFs and auto-magically feed them into claude for processing. Now also supports Redlib mirrors of Reddit if you get banned from reddit/old.reddit.

Tkinter app that saves old.reddit.com posts as PDFs, rendered by a real Chrome
(print layout, like Ctrl/Cmd+P → Save as PDF).

## Quick start (macOS)

Double-click `run.command` (or `./run.command`). It finds a Python with Tk 8.6+,
installs Homebrew's `python-tk@3.11` if needed, creates a `.venv`, installs the
requirements, and launches the app. If macOS blocks it, right-click -> Open once.

## Command line

`./run.commandline SUBREDDIT [options]` does the same job from the terminal
(`--help` lists every option; the full manual is `commandline.md`).

## Manual setup

```
pip install -r requirements.txt
```

Tkinter can't be installed via pip. On macOS with Homebrew Python:

```
brew install python-tk@3.11    # match your Python version
```

Uses your installed Google Chrome automatically. If you don't have Chrome:

```
python -m playwright install chromium
```

## Run

```
python main.py
```

## Use

1. Type a subreddit (e.g. `python`), pick a sort (hot / new / top / rising / controversial; Time applies to top & controversial) and an output folder.
2. **Pick posts from a list** → *Load posts*, tick the boxes (click the ☐, or select a row and press Space), *Download selected as PDF*.
3. **Search (optional):** type text in the *Search* box to search inside the subreddit (`/r/<sub>/search?q=…&restrict_sr=on`). Sort then offers relevance / hot / top / new / comments and Time works with every sort. Leave it empty to browse as before. Both tabs use it.
4. **Automatic batch** → choose 1–25 / 1–50 / 1–100 or a custom range n1–n2, *Start batch download*.

PDFs land in `<output>/r_<sub>_<sort>/` named `NNN - Title [id].pdf`, where NNN is the post's rank in the listing.

## Files

- `main.py` – the Tkinter UI (run this, or double-click `run.command`)
- `cli.py` – command-line interface (run via `run.commandline`)
- `scraper.py` – listing parsing + PDF rendering via Playwright
# RedditPDFScraperForClaude
