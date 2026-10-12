# run.commandline — manual

Save subreddit posts as PDFs from the terminal. Same engine as the Tkinter app (`run.command`): a real Chrome loads each post and prints it to PDF, so the result looks like *File → Print → Save as PDF*.

```
./run.commandline SUBREDDIT [options]
./run.commandline --help
```

---

## 1. Quick start

```bash
cd "Python Reddit Scraper/PythonCode"

./run.commandline python                         # first 25 hot posts of r/python
./run.commandline python -s top -t month -n 50   # top 50 of the month
./run.commandline python -i                      # list posts, then choose which to save
./run.commandline python --show-browser          # watch Chrome do it
```

The first run takes about a minute: it creates a private `.venv`, installs Playwright, and (only if Google Chrome isn't installed) downloads Chromium. After that it starts immediately. To do just that setup, run `./run.commandline --setup`.

PDFs go to `~/Documents/RedditPDFs/r_<subreddit>_<sort>/` unless you pass `-o`. Searches get their own folder, e.g. `r_Expats_In_France_search-visiteur_top-year/`.

Tip: link it into your PATH to use it from anywhere (it follows symlinks and keeps your current folder for relative `-o` paths):

```bash
ln -s "$PWD/run.commandline" /usr/local/bin/redditpdf     # or ~/bin, /opt/homebrew/bin
redditpdf python -n 25 -o .
```

---

## 2. Choosing which posts

Post numbers are positions in the listing, starting at 1 (stickied posts count). Use **at most one** of the four selectors below; with none, you get posts 1–25.

| Option | Meaning | Example |
|---|---|---|
| `-n N`, `--count N` | Posts 1 to N | `-n 100` |
| `-r N1-N2`, `--range N1-N2` | Posts N1 to N2 (a single number `N` means 1–N) | `-r 26-60` |
| `-p LIST`, `--pick LIST` | Specific numbers and ranges, comma-separated | `-p 1,4,10-12` |
| `-i`, `--interactive` | Load a list, print it, then ask which to save | `-i --load 100` |
| `--load N` | How many posts `-i` loads and shows (default 50) | |
| `-l`, `--list` | Print the selection and exit; **no PDFs are created** | `-n 100 -l` |

In interactive mode you can answer with `1,3,5-8`, `all`, or `q` to quit. Asking for a number that isn't loaded makes it ask again.

`--list` works with every selector, so `-r 26-60 --list` previews exactly what a download of that range would contain. Output is a plain table on stdout (progress chatter is on stderr), so it pipes cleanly:

```bash
./run.commandline python -n 100 -l -q | grep -i pandas
```

### Searching a subreddit

`-S TEXT` (also `--search TEXT` or `--query TEXT`) searches **inside** the subreddit instead of browsing it. It is the same as opening `/r/<sub>/search?q=TEXT&restrict_sr=on` in a browser. Everything else (`-n`, `-r`, `-p`, `-i`, `-l`, output and browser options) works on the search results exactly as it does on a normal listing.

```bash
./run.commandline Expats_In_France -S visiteur                       # relevance, all time
./run.commandline Expats_In_France -S visiteur -s top -t year -n 20  # top 20 hits of the past year
./run.commandline Expats_In_France -S "carte de séjour" -s new -l    # preview newest hits
```

Quote searches with more than one word. Post numbers are positions in the search results.

### Sorting and time window

| Option | Meaning |
|---|---|
| `-s SORT`, `--sort SORT` | **Browsing:** `hot` (default), `new`, `top`, `rising`, `controversial`. **With `-S`:** `relevance` (default), `hot`, `top`, `new`, `comments` |
| `-t PERIOD`, `--time PERIOD` | `hour`, `day`, `week`, `month`, `year`, `all`. **Browsing:** used by `top` and `controversial` only (default `week`). **With `-S`:** applies to any sort (default `all`, meaning no time limit) |

Asking for a sort that doesn't exist in the current mode (for example `-s rising` with `-S`) is a usage error that lists the valid choices.

---|---|
| `-s SORT`, `--sort SORT` | `hot` (default), `new`, `top`, `rising`, `controversial` |
| `-t PERIOD`, `--time PERIOD` | For `top` and `controversial` only: `hour`, `day`, `week` (default), `month`, `year`, `all` |

---

## 3. Output options

| Option | Meaning |
|---|---|
| `-o DIR`, `--output DIR` | Where to write PDFs. Default `~/Documents/RedditPDFs`. Relative paths are relative to where you run the command. |
| `--flat` | Put PDFs straight in `DIR`. Without it they go in `DIR/r_<sub>_<sort>/` (e.g. `r_python_top-month`, or `r_python_search-async-await_top-year` for a search). |
| `--paper Letter\|A4` | Page size. Default `Letter`. |
| `--no-header-footer` | Drop Chrome's header (date, title) and footer (URL, page n/N). |
| `--skip-existing` | Skip a post if a PDF for it (matched by its Reddit id) is already in the folder — handy for re-running a batch after a failure. |
| `--many-comments` | old.reddit.com only: load up to 500 comments. Ignored (with a note) on other sites. |

**File names:** `NNN - Post title [id].pdf` — `NNN` is the post's number in the listing (or search results), so files sort in that order. Characters that are illegal in file names are removed and long titles are shortened.

---

## 4. Site options

By default the tool reads from **safereddit.com** (a Redlib frontend; no login needed). Reddit now asks for a login on old.reddit.com, so that mode only works if you can get past that.

| Option | Meaning |
|---|---|
| `--site URL` | Frontend to use. Any Redlib-style mirror works, e.g. `--site https://redlib.example.org`. |
| `--old-reddit` | Shortcut for `--site https://old.reddit.com`. |
| `--site-mode auto\|old\|redlib` | Which page layout to parse. `auto` (default) picks `old` for old.reddit.com and `redlib` for everything else. Only needed for unusual hostnames. |

---

## 5. Browser options (including the browser window)

The tool drives a real browser. By default it runs **hidden** ("headless"). These options control it:

| Option | Meaning |
|---|---|
| `--show-browser` (alias `--headed`) | Show the Chrome window. See below for when this helps. |
| `--browser auto\|chrome\|chromium` | `chrome` = your installed Google Chrome; `chromium` = Playwright's bundled build; `auto` (default) = Chrome if available, else Chromium. |
| `--chrome-path FILE` | Use a specific browser executable (e.g. Brave, Edge, a Chrome Beta). Overrides `--browser`. |
| `--window-size WxH` | Size of the browser viewport while pages load, e.g. `1440x900`. Default `1280x900`. This can change how a responsive page lays out before printing. |
| `--user-agent STRING` | User-Agent header. Default is a recent desktop Chrome. |
| `--wait-timeout SEC` | After each page loads, how long to wait for the *real* content to appear. Default 45. See below. |
| `--debug-dir DIR` | Where to save `last_listing.html` / `last_listing.png` when a listing is empty. Default: a `debug` folder next to the program. |

### When to use `--show-browser`

- **Watching progress.** You see each page load and print.
- **Challenge or captcha pages.** Sites sometimes show a "Welcome to Reddit" / bot-check page before the real content. Hidden browsers are more likely to be challenged; a visible one often isn't, and if a captcha does appear you can solve it by hand. The tool keeps waiting for the real page, so give yourself time:

  ```bash
  ./run.commandline python --show-browser --wait-timeout 180
  ```

- **Debugging** an empty listing: you can see exactly what the site returned.

Don't minimize or close the window mid-run; closing it makes the current item fail. The browser is a fresh, separate profile: it does **not** share your logged-in Chrome session, cookies or extensions.

### About `--wait-timeout`

`--wait-timeout` is per page, and only matters when a page doesn't show its real content straight away. If a site is simply slow, raise it. If you'd rather fail fast, lower it (`--wait-timeout 10`). `0` means "don't wait". While waiting, the tool prints *Waiting for the site to finish loading (challenge page?)...*.

---

## 6. Pacing and messages

| Option | Meaning |
|---|---|
| `--delay SEC` | Pause between page loads. Default 1.5. Raise it (e.g. `4`) if the site starts rate-limiting you; the tool already waits and retries on HTTP 429. |
| `-q`, `--quiet` | Only errors and the final summary. |
| `-v`, `--verbose` | Also print each listing page URL as it loads. |
| `--version` | Print the version. |
| `-h`, `--help` | Show all options. |

Per-post lines look like:

```
[3/25] OK   003 - Some title [abc123].pdf  (212 KB)
[4/25] FAIL #004 Another title - Failed to load https://… (HTTP 500)
[5/25] SKIP #005 Third title (already saved)
```

`Ctrl-C` once = finish the current step, then stop and print what was saved. `Ctrl-C` twice = quit immediately.

---

## 7. Exit codes

| Code | Meaning |
|---|---|
| 0 | Everything selected was saved (or skipped as already present), or a `--list` finished |
| 1 | Some posts failed; the others were saved |
| 2 | Bad command line (also: invalid subreddit name) |
| 3 | The listing couldn't be loaded (blocked, no such subreddit, no network) |
| 4 | Setup failed (`run.commandline` only: Python, pip or browser install) |
| 130 | Interrupted with Ctrl-C |

Usable in scripts:

```bash
./run.commandline python -n 25 -q --skip-existing || echo "something failed ($?)"
```

---

## 8. Recipes

```bash
# Weekly digest: top 25 of the week, A4, no header/footer, into a dated folder
./run.commandline python -s top -t week -n 25 --paper A4 --no-header-footer \
    --flat -o ~/Documents/reddit/$(date +%F)

# Everything from 51 to 100, resuming after an interruption
./run.commandline python -r 51-100 --skip-existing

# Preview before committing
./run.commandline python -s new -r 1-40 --list
./run.commandline python -s new -r 1-40

# Search, newest first, then choose by hand
./run.commandline Expats_In_France -S visiteur -s new -i --load 40

# Pick by hand from the top 100 of all time
./run.commandline python -s top -t all -i --load 100

# Behind a challenge page: visible browser and plenty of time
./run.commandline python --show-browser --wait-timeout 180

# A different Redlib mirror
./run.commandline python --site https://redlib.example.org -n 10

# Use a different Chromium-based browser
./run.commandline python --chrome-path "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
```

---

## 9. Troubleshooting

**"No posts found for r/…" or "…for search "…"" (exit 3).** For a search, this can simply mean there were no matches — the message includes the site's own wording (e.g. "No posts were found"). The tool printed what the site actually returned (title, URL, first text) and saved `last_listing.html` and `last_listing.png` in the debug folder. Look at the PNG. Typical causes: a challenge page (try `--show-browser --wait-timeout 180`), a misspelled or private/banned subreddit, the mirror being down or rate-limited (try another `--site`, or wait a few minutes), or the mirror's page layout being different from what the parser expects (tell me which site and attach the HTML).

**Slow batches.** Every post is its own page load plus `--delay`, so 100 posts takes a few minutes. That is normal; `--delay 0.5` speeds it up at the risk of being rate-limited.

**A few posts FAIL, the rest are fine.** Re-run the same command with `--skip-existing` to retry only the missing ones.

**"Couldn't start Chrome/Chromium".** Install Google Chrome, or run `./.venv/bin/python -m playwright install chromium`, or point at a browser with `--chrome-path`.

**`./run.commandline: Permission denied`.** Run `chmod +x run.commandline` once.

**macOS blocks the script ("cannot be opened").** Run it once with `bash run.commandline --setup`, or right-click it in Finder → Open.

**Running without the launcher.** If you've already set up the `.venv`, `./.venv/bin/python cli.py SUBREDDIT …` is equivalent.

---

## 10. Files

| File | Purpose |
|---|---|
| `run.commandline` | Launcher: sets up Python/venv/browser, then runs `cli.py "$@"` |
| `cli.py` | The command-line interface (argument parsing, selection, output) |
| `scraper.py` | Shared engine: loads listings, parses posts, prints PDFs |
| `main.py` / `run.command` | The Tkinter app and its launcher |
| `requirements.txt` | Python dependencies (Playwright) |
| `.venv/` | Private environment, shared by both launchers |
| `debug/` | Snapshots of empty listings, for troubleshooting |
