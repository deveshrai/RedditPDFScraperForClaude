#!/usr/bin/env python3
"""
cli.py - command-line interface for the Reddit -> PDF tool.

Normally launched through ./run.commandline (which sets up Python, a virtual
environment and the dependencies first), but it also runs directly:

    python cli.py SUBREDDIT [options]

Run with --help for every option; see commandline.md for the full manual.
"""

from __future__ import annotations

import argparse
import re
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

from scraper import (
    Cancelled, DEFAULT_BASE, Post, RedditScraper, SORTS, ScrapeError,
    SEARCH_SORTS, TIME_FILTERS, TIMED_SORTS, USER_AGENT, clean_subreddit, run_tag,
    site_mode,
)

PROG = "run.commandline"
VERSION = "1.0"

EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, EXIT_FATAL, EXIT_CANCELLED = 0, 1, 2, 3, 130


# --------------------------------------------------------------------------- #
# argument types
# --------------------------------------------------------------------------- #

def positive_int(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a whole number")
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def non_negative_float(text: str) -> float:
    try:
        x = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a number")
    if x < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return x


def range_arg(text: str) -> tuple[int, int]:
    """'10-30' -> (10, 30);  '25' -> (1, 25)."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-:]\s*(\d+))?\s*", text)
    if not m:
        raise argparse.ArgumentTypeError(f"'{text}' is not a range like 10-30")
    a, b = (1, int(m.group(1))) if m.group(2) is None else (int(m.group(1)), int(m.group(2)))
    if a < 1 or b < a:
        raise argparse.ArgumentTypeError("range must satisfy 1 <= START <= END")
    return a, b


def ranks_arg(text: str) -> list[int]:
    """'1,3,5-8' -> [1, 3, 5, 6, 7, 8]."""
    ranks = parse_ranks(text)
    if ranks is None or not ranks:
        raise argparse.ArgumentTypeError(f"'{text}' is not a list like 1,3,5-8")
    return ranks


def size_arg(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{3,5})\s*[xX]\s*(\d{3,5})\s*", text)
    if not m:
        raise argparse.ArgumentTypeError(f"'{text}' is not a size like 1280x900")
    return int(m.group(1)), int(m.group(2))


def parse_ranks(text: str) -> list[int] | None:
    """Parse '1,3,5-8' into sorted unique ranks; None if malformed."""
    out: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a < 1 or b < a:
            return None
        out.update(range(a, b + 1))
    return sorted(out)


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

DESCRIPTION = """\
Save posts from a subreddit as PDFs, printed by a real Chrome so they look like
File > Print > Save as PDF. Works through safereddit.com by default (no login
needed); old.reddit.com is also supported (Reddit now asks you to log in there).
"""

EPILOG = f"""\
examples:
  {PROG} python                          first 25 hot posts of r/python
  {PROG} python -s top -t month -n 50    top 50 posts of the month
  {PROG} python -s new -r 26-60          posts 26 to 60 of "new"
  {PROG} python -p 1,4,10-12             only posts #1, #4 and #10 through #12
  {PROG} python -i                       list posts, then choose which to save
  {PROG} python -n 100 --list            just print the top 100 titles
  {PROG} python -S "async await"         search r/python (relevance, all time)
  {PROG} python -S visiteur -s top -t year -n 20   top 20 search hits of the past year
  {PROG} python -n 25 -o ~/Desktop/pdfs --paper A4 --no-header-footer
  {PROG} python --show-browser           watch Chrome work (e.g. to solve a captcha)
  {PROG} python --site https://redlib.example.org

selecting posts:
  Use at most one of -n / -r / -p / -i. With none of them you get posts 1-25.
  Post numbers are positions in the listing (stickied posts count).

exit status:
  0  every selected post was saved (or skipped as already present)
  1  some posts failed, the rest were saved
  2  bad command line
  3  could not load the listing (blocked, wrong name, no network, ...)
  130  interrupted with Ctrl-C

first run:
  run.commandline sets up a private Python environment and installs what it needs
  the first time (about a minute). `run.commandline --setup` does only that.

More detail: commandline.md
"""


_ALL_SORTS = SORTS + [x for x in SEARCH_SORTS if x not in SORTS]


def build_parser() -> argparse.ArgumentParser:
    width = max(80, min(shutil.get_terminal_size((100, 24)).columns, 110))
    p = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=lambda prog: argparse.RawDescriptionHelpFormatter(
            prog, max_help_position=30, width=width),
        add_help=False,
        usage=f"{PROG} SUBREDDIT [options]",
    )

    p.add_argument("subreddit", metavar="SUBREDDIT",
                   help="subreddit name: python, r/python, or a reddit.com/r/... URL")

    g = p.add_argument_group("what to fetch")
    g.add_argument("-S", "--search", "--query", metavar="TEXT", dest="search",
                   help="search inside the subreddit instead of browsing it "
                        "(/r/<sub>/search?q=TEXT&restrict_sr=on). Quote multi-word searches")
    g.add_argument("-s", "--sort", choices=_ALL_SORTS, default=None, metavar="SORT",
                   help="browsing: " + ", ".join(SORTS) + " (default: hot).  "
                        "With --search: " + ", ".join(SEARCH_SORTS) + " (default: relevance)")
    g.add_argument("-t", "--time", choices=TIME_FILTERS, default=None, metavar="PERIOD",
                   help="time window: " + ", ".join(TIME_FILTERS) + ".  Browsing: used by "
                        "top/controversial (default: week).  With --search: any sort "
                        "(default: all)")

    g = p.add_argument_group("which posts (choose at most one)")
    sel = g.add_mutually_exclusive_group()
    sel.add_argument("-n", "--count", type=positive_int, metavar="N",
                     help="posts 1 to N (e.g. -n 25, -n 50, -n 100)")
    sel.add_argument("-r", "--range", type=range_arg, metavar="N1-N2", dest="range",
                     help="posts N1 to N2, e.g. 26-60")
    sel.add_argument("-p", "--pick", type=ranks_arg, metavar="LIST",
                     help="specific post numbers, e.g. 1,3,5-8")
    sel.add_argument("-i", "--interactive", action="store_true",
                     help="load a list, show it, and ask which posts to save")
    g.add_argument("--load", type=positive_int, default=50, metavar="N",
                   help="how many posts -i loads and shows (default: 50)")
    g.add_argument("-l", "--list", action="store_true",
                   help="only print the selected posts; don't create any PDFs")

    g = p.add_argument_group("site")
    g.add_argument("--site", metavar="URL", default=DEFAULT_BASE,
                   help=f"frontend to read from (default: {DEFAULT_BASE}); any "
                        "Redlib-style mirror works")
    g.add_argument("--old-reddit", action="store_true",
                   help="shortcut for --site https://old.reddit.com")
    g.add_argument("--site-mode", choices=("auto", "old", "redlib"), default="auto",
                   help="page layout to parse (default: auto - 'old' for "
                        "old.reddit.com, 'redlib' for everything else)")

    g = p.add_argument_group("output")
    g.add_argument("-o", "--output", metavar="DIR",
                   default=str(Path.home() / "Documents" / "RedditPDFs"),
                   help="folder for the PDFs (default: ~/Documents/RedditPDFs)")
    g.add_argument("--flat", action="store_true",
                   help="write PDFs straight into DIR instead of DIR/r_<sub>_<sort>/")
    g.add_argument("--paper", choices=("Letter", "A4"), default="Letter",
                   help="page size (default: Letter)")
    g.add_argument("--no-header-footer", action="store_true",
                   help="leave out Chrome's date/title/URL/page-number header and footer")
    g.add_argument("--many-comments", action="store_true",
                   help="old.reddit only: load up to 500 comments (?limit=500)")
    g.add_argument("--skip-existing", action="store_true",
                   help="don't re-download a post whose PDF is already in the folder")

    g = p.add_argument_group("browser")
    g.add_argument("--show-browser", "--headed", action="store_true", dest="show_browser",
                   help="show the Chrome window instead of running it hidden. Use this "
                        "to watch progress or solve a captcha / challenge by hand "
                        "(see --wait-timeout)")
    g.add_argument("--browser", choices=("auto", "chrome", "chromium"), default="auto",
                   help="which browser to drive: your installed Google Chrome, "
                        "Playwright's bundled Chromium, or auto = Chrome, then Chromium "
                        "(default: auto)")
    g.add_argument("--chrome-path", metavar="FILE",
                   help="path to a specific Chrome/Chromium executable (overrides --browser)")
    g.add_argument("--window-size", type=size_arg, default=(1280, 900), metavar="WxH",
                   help="browser viewport used when loading pages, e.g. 1440x900 "
                        "(default: 1280x900)")
    g.add_argument("--user-agent", default=USER_AGENT, metavar="STRING",
                   help="User-Agent header to send (default: a recent desktop Chrome)")
    g.add_argument("--wait-timeout", type=non_negative_float, default=45.0, metavar="SEC",
                   help="how long to wait for each page's real content to appear after "
                        "it loads - covers challenge / 'Welcome to Reddit' pages "
                        "(default: 45). With --show-browser, raise this (e.g. 180) to "
                        "leave time for solving a captcha")
    g.add_argument("--debug-dir", metavar="DIR",
                   help="where to save last_listing.html/.png when a listing comes back "
                        "empty (default: the 'debug' folder next to the program)")

    g = p.add_argument_group("pacing")
    g.add_argument("--delay", type=non_negative_float, default=1.5, metavar="SEC",
                   help="pause between page loads, to be polite to the site (default: 1.5)")

    g = p.add_argument_group("other")
    g.add_argument("-q", "--quiet", action="store_true",
                   help="print only errors and the final summary")
    g.add_argument("-v", "--verbose", action="store_true",
                   help="also print every page URL as it is loaded")
    g.add_argument("--version", action="version", version=f"{PROG} {VERSION}")
    g.add_argument("-h", "--help", action="help", help="show this help and exit")
    return p


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #

def eprint(*a) -> None:
    print(*a, file=sys.stderr, flush=True)


def print_table(posts: list[Post]) -> None:
    cols = shutil.get_terminal_size((100, 24)).columns
    print(f"{'#':>4}  {'score':>7} {'cmts':>6}  title")
    for p in posts:
        flag = "*" if p.stickied else " "
        head = f"{p.rank:>4}{flag} {p.score:>7} {p.comments:>6}  "
        tail = f"  (u/{p.author})"
        room = max(20, cols - len(head) - len(tail))
        title = p.title if len(p.title) <= room else p.title[: room - 1] + "…"
        print(head + title + tail)
    if any(p.stickied for p in posts):
        print("(* = stickied)")


def ask_selection(posts: list[Post]) -> list[Post]:
    by_rank = {p.rank: p for p in posts}
    top = max(by_rank)
    print()
    while True:
        try:
            ans = input(f"Which posts? e.g. 1,3,5-8 | all | q to quit  [1-{top}]: ").strip().lower()
        except EOFError:
            return []
        if ans in ("q", "quit", "exit", "none", ""):
            return []
        if ans == "all":
            return list(posts)
        ranks = parse_ranks(ans)
        if ranks is None:
            print("  Couldn't read that. Try something like: 1,3,5-8")
            continue
        missing = [r for r in ranks if r not in by_rank]
        if missing:
            print(f"  No such post number(s): {', '.join(map(str, missing[:8]))}")
            continue
        return [by_rank[r] for r in ranks]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        sub = clean_subreddit(args.subreddit)
    except ScrapeError as e:
        parser.error(str(e))

    site = "https://old.reddit.com" if args.old_reddit else args.site.strip()
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    site = site.rstrip("/")
    mode = None if args.site_mode == "auto" else args.site_mode
    eff_mode = mode or site_mode(site)

    if args.interactive and not sys.stdin.isatty():
        parser.error("--interactive needs a terminal (stdin is not a TTY)")
    if args.many_comments and eff_mode != "old":
        eprint("note: --many-comments only applies to old.reddit.com; ignoring it.")

    # How many posts must be loaded, and which of them are wanted.
    if args.range:
        lo, hi = args.range
        fetch_n = hi
    elif args.pick:
        fetch_n = max(args.pick)
    elif args.interactive:
        fetch_n = args.load
    elif args.count:
        fetch_n = args.count
    else:
        fetch_n = 25

    quiet, verbose = args.quiet, args.verbose

    # Search vs. browse decides which sorts are valid and the default sort/time.
    query = None
    if args.search is not None:
        query = args.search.strip()
        if not query:
            parser.error("--search needs some text to look for")
    sort = args.sort or ("relevance" if query else "hot")
    valid = SEARCH_SORTS if query else SORTS
    if sort not in valid:
        parser.error(f"sort '{sort}' isn't available "
                     f"{'with --search' if query else 'when browsing'}; "
                     f"choose from: {', '.join(valid)}")
    tf = args.time or ("all" if query else "week")

    def log(msg: str) -> None:
        if quiet:
            return
        if msg.startswith("Loading listing") and not verbose:
            return
        eprint(msg)

    def info(msg: str) -> None:
        if not quiet:
            eprint(msg)

    cancel = threading.Event()

    def on_sigint(signum, frame):  # noqa: ARG001
        if cancel.is_set():
            raise KeyboardInterrupt
        cancel.set()
        eprint("\nStopping after the current step... (Ctrl-C again to force quit)")

    signal.signal(signal.SIGINT, on_sigint)

    tag = run_tag(sort, tf, query)
    out_dir = Path(args.output).expanduser()
    if not args.flat:
        out_dir = out_dir / f"r_{sub}_{tag}"

    if args.show_browser and args.wait_timeout <= 45:
        info("tip: with --show-browser you can solve a captcha by hand; "
             "consider --wait-timeout 180.")

    ok = failed = skipped = 0
    try:
        with RedditScraper(
            headless=not args.show_browser, delay=args.delay, log=log, base=site,
            mode=mode, browser=args.browser, chrome_path=args.chrome_path,
            viewport=args.window_size, user_agent=args.user_agent,
            ready_timeout=args.wait_timeout, debug_dir=args.debug_dir,
        ) as s:
            what = f'search "{query}" in r/{sub}' if query else f"r/{sub}"
            info(f"Loading {what} ({sort}{'' if tf == 'all' else ', ' + tf}) from {site} "
                 f"- up to {fetch_n} posts...")
            posts = s.fetch_posts(sub, sort, tf, fetch_n, cancel=cancel, query=query)
            info(f"Loaded {len(posts)} posts.")

            if args.range:
                chosen = [p for p in posts if lo <= p.rank <= hi]
                if not chosen:
                    raise ScrapeError(
                        f"r/{sub} only has {len(posts)} posts; nothing in {lo}-{hi}.")
            elif args.pick:
                have = {p.rank for p in posts}
                gone = [r for r in args.pick if r not in have]
                if gone:
                    eprint(f"warning: no post number {', '.join(map(str, gone))} "
                           f"(only {len(posts)} loaded).")
                chosen = [p for p in posts if p.rank in set(args.pick)]
                if not chosen:
                    raise ScrapeError("none of the requested post numbers exist.")
            elif args.interactive:
                print_table(posts)
                if args.list:
                    return EXIT_OK
                chosen = ask_selection(posts)
                if not chosen:
                    info("Nothing selected.")
                    return EXIT_OK
            else:
                chosen = posts[:fetch_n]

            if args.list:
                print_table(chosen)
                return EXIT_OK

            total = len(chosen)
            info(f"Saving {total} PDF{'s' if total != 1 else ''} to {out_dir}")
            for i, post in enumerate(chosen, 1):
                if cancel.is_set():
                    raise Cancelled()
                label = f"[{i:>{len(str(total))}}/{total}]"
                if args.skip_existing and out_dir.is_dir() and any(
                        f.name.endswith(f"[{post.id}].pdf") for f in out_dir.iterdir()):
                    skipped += 1
                    info(f"{label} SKIP #{post.rank:03d} {post.title[:70]} (already saved)")
                    continue
                try:
                    path = s.save_pdf(
                        post, out_dir, paper=args.paper,
                        chrome_header_footer=not args.no_header_footer,
                        many_comments=args.many_comments, cancel=cancel)
                    ok += 1
                    kb = path.stat().st_size / 1024
                    info(f"{label} OK   {path.name}  ({kb:,.0f} KB)")
                except Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    eprint(f"{label} FAIL #{post.rank:03d} {post.title[:60]} - "
                           f"{str(e).splitlines()[0]}")
                if i < total:
                    time.sleep(args.delay)
    except Cancelled:
        eprint(f"Cancelled. Saved {ok}, failed {failed}, skipped {skipped}.")
        return EXIT_CANCELLED
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return EXIT_CANCELLED
    except ScrapeError as e:
        eprint(f"error: {e}")
        return EXIT_FATAL

    summary = f"Done: {ok} saved, {failed} failed"
    if skipped:
        summary += f", {skipped} skipped"
    print(f"{summary}. Folder: {out_dir}")
    return EXIT_PARTIAL if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
