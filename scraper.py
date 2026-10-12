"""
scraper.py - Core logic for the Reddit -> PDF tool.

Uses Playwright driving a real Chrome/Chromium so the PDFs match what you'd get
from "Print -> Save as PDF" in Chrome. Works with a Redlib-style frontend
(default: safereddit.com) or with old.reddit.com (which now wants a login).

Public API:
    RedditScraper(...)            context manager that owns the browser
        .fetch_posts(sub, sort, time_filter, count, progress_cb, cancel_event)
        .save_pdf(post, out_dir, index, ...)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Optional

DEFAULT_BASE = "https://safereddit.com"
SITE_PRESETS = ["https://safereddit.com", "https://old.reddit.com"]

SORTS = ["hot", "new", "top", "rising", "controversial"]
TIME_FILTERS = ["hour", "day", "week", "month", "year", "all"]
TIMED_SORTS = {"top", "controversial"}
SEARCH_SORTS = ["relevance", "hot", "top", "new", "comments"]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ScrapeError(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Post:
    rank: int            # 1-based position in the listing
    fullname: str        # e.g. t3_abc123
    title: str
    author: str
    score: str
    comments: int
    url: str             # comments page on the chosen site
    stickied: bool = False

    @property
    def id(self) -> str:
        return self.fullname.split("_", 1)[-1]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def clean_subreddit(name: str) -> str:
    name = name.strip()
    name = re.sub(r"^(https?://)?(old\.|www\.)?reddit\.com/", "", name)
    name = re.sub(r"^/?r/", "", name)
    name = name.strip("/ ").split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_+]{1,60}", name):
        raise ScrapeError(f"'{name}' doesn't look like a valid subreddit name.")
    return name


def safe_filename(text: str, max_len: int = 90) -> str:
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")
    return text or "untitled"


def site_mode(base: str) -> str:
    """'old' for old.reddit.com, otherwise a Redlib-style frontend."""
    return "old" if "old.reddit.com" in base else "redlib"


def listing_url(base: str, mode: str, sub: str, sort: str, time_filter: str,
                limit: int = 100, after: Optional[str] = None,
                query: Optional[str] = None) -> str:
    from urllib.parse import quote_plus
    if query:
        # Search inside the subreddit:  /r/<sub>/search?q=..&restrict_sr=on&sort=..&t=..
        url = f"{base}/r/{sub}/search?q={quote_plus(query)}&restrict_sr=on&sort={sort}"
        if time_filter and time_filter != "all":
            url += f"&t={time_filter}"
        if mode == "old":
            url += f"&limit={limit}"
        if after:
            url += f"&after={after}"
        return url
    if mode == "old":
        url = f"{base}/r/{sub}/{sort}/?limit={limit}"
        if sort in TIMED_SORTS:
            url += f"&t={time_filter}"
        if after:
            url += f"&after={after}"
        return url
    params = []
    if sort in TIMED_SORTS:
        params.append(f"t={time_filter}")
    if after:
        params.append(f"after={after}")
    return f"{base}/r/{sub}/{sort}" + ("?" + "&".join(params) if params else "")


def run_tag(sort: str, time_filter: str, query: Optional[str] = None) -> str:
    """Folder-name fragment describing what was fetched, e.g. 'top-month' or
    'search-visiteur_top-year'."""
    if query:
        slug = re.sub(r"[^\w]+", "-", query.strip(), flags=re.UNICODE).strip("-")[:40] or "query"
        tag = f"search-{slug}_{sort}"
        return tag + (f"-{time_filter}" if time_filter and time_filter != "all" else "")
    return f"{sort}-{time_filter}" if sort in TIMED_SORTS else sort


# JS run inside the listing page; returns the posts + next-page link.
_PARSE_JS = r"""
(mode) => {
  const out = [];
  let next = null;
  if (mode === 'old') {
    document.querySelectorAll('#siteTable div.thing[data-fullname^="t3_"]').forEach(el => {
      if (el.classList.contains('promoted') || el.dataset.promoted === 'true') return;
      const titleA = el.querySelector('a.title');
      if (!titleA) return;
      out.push({
        fullname: el.dataset.fullname || '',
        title: titleA.textContent.trim(),
        author: el.dataset.author || '[deleted]',
        score: (el.querySelector('.score.unvoted, .score.likes, .score.dislikes') || {}).textContent || (el.dataset.score || ''),
        comments: parseInt(el.dataset.commentsCount || '0', 10),
        permalink: el.dataset.permalink || '',
        stickied: el.classList.contains('stickied'),
      });
    });
    // search results use a different markup than normal listings
    document.querySelectorAll('#siteTable div.search-result-link').forEach(el => {
      const a = el.querySelector('a.search-title');
      if (!a) return;
      const href = a.getAttribute('href') || '';
      const m = href.match(/\/comments\/([a-z0-9]+)/i);
      if (!m) return;
      const sc = el.querySelector('.search-score');
      const cm = el.querySelector('.search-comments');
      const au = el.querySelector('.search-author .author, .search-author a');
      out.push({
        fullname: 't3_' + m[1],
        title: a.textContent.trim(),
        author: au ? au.textContent.trim() : '[deleted]',
        score: sc ? sc.textContent.trim() : '',
        comments: parseInt(((((cm ? cm.textContent : '0')).match(/[\d,]+/) || ['0'])[0]).replace(/,/g, ''), 10) || 0,
        permalink: new URL(href, location.href).pathname,
        stickied: false,
      });
    });
    const n = document.querySelector('span.next-button a');
    next = n ? n.href : null;
  } else {
    // Redlib-style frontends (safereddit.com etc.)
    document.querySelectorAll('div.post').forEach(el => {
      if (el.classList.contains('highlighted')) return;
      const cm = el.querySelector('a.post_comments');
      const ta = el.querySelector('.post_title a, h2 a');
      let perma = '';
      for (const h of [cm && cm.getAttribute('href'), ta && ta.getAttribute('href')]) {
        if (h && /\/comments\/[a-z0-9]+/i.test(h)) { perma = h; break; }
      }
      if (!perma) return;
      const id = (perma.match(/\/comments\/([a-z0-9]+)/i) || [])[1];
      const sc = el.querySelector('.post_score');
      const au = el.querySelector('.post_author');
      const cmText = cm ? (cm.getAttribute('title') || cm.textContent) : '0';
      out.push({
        fullname: 't3_' + id,
        title: ((ta ? ta.textContent : '') || '').trim(),
        author: au ? au.textContent.trim().replace(/^u\//, '') : '[deleted]',
        score: sc ? (sc.getAttribute('title') || sc.textContent).trim() : '',
        comments: parseInt(((cmText.match(/[\d,]+/) || ['0'])[0]).replace(/,/g, ''), 10) || 0,
        permalink: perma,
        stickied: !!el.querySelector('.stickied') || el.classList.contains('stickied'),
      });
    });
    const links = Array.from(document.querySelectorAll('a[href*="after="]'));
    const n = links.find(a => /next/i.test(a.textContent)) || null;
    next = n ? n.href : null;
  }
  return {posts: out, next: next};
}
"""


# --------------------------------------------------------------------------- #
# the scraper
# --------------------------------------------------------------------------- #

class RedditScraper:
    def __init__(self, headless: bool = True, delay: float = 1.5,
                 log: Callable[[str], None] = lambda s: None,
                 base: str = DEFAULT_BASE, mode: Optional[str] = None,
                 browser: str = "auto", chrome_path: Optional[str] = None,
                 viewport: tuple = (1280, 900), user_agent: str = USER_AGENT,
                 ready_timeout: float = 45.0, debug_dir: Optional[str] = None):
        self.base = (base or DEFAULT_BASE).rstrip("/")
        self.mode = mode or site_mode(self.base)
        self.headless = headless
        self.delay = delay
        self.log = log
        self._pw = None
        self._browser = None
        self._ctx = None
        self.browser_kind = browser          # auto | chrome | chromium
        self.chrome_path = chrome_path       # explicit browser executable
        self.viewport = viewport
        self.user_agent = user_agent
        self.ready_timeout = ready_timeout
        self.debug_dir = (Path(debug_dir).expanduser() if debug_dir
                          else Path(__file__).resolve().parent / "debug")

    def _launch_options(self) -> list:
        if self.chrome_path:
            return [{"executable_path": str(self.chrome_path)}]
        if self.browser_kind == "chrome":
            return [{"channel": "chrome"}]
        if self.browser_kind == "chromium":
            return [{}]
        return [{"channel": "chrome"}, {}]   # auto: real Chrome, else Chromium

    # context manager -------------------------------------------------------
    def __enter__(self) -> "RedditScraper":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise ScrapeError(
                "Playwright isn't installed.\n"
                "Run:  pip install playwright   (see requirements.txt)"
            ) from e

        self._pw = sync_playwright().start()
        launch_errors = []
        # Prefer the user's real Chrome so output matches Chrome's own print.
        for kwargs in self._launch_options():
            try:
                self._browser = self._pw.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                    **kwargs)
                break
            except Exception as e:  # noqa: BLE001
                launch_errors.append(str(e).splitlines()[0])
        if self._browser is None:
            self._pw.stop()
            raise ScrapeError(
                "Couldn't start Chrome/Chromium.\n"
                "Install Google Chrome, or run:  python -m playwright install chromium\n"
                "(or point to a browser with --chrome-path)\n\n"
                + "\n".join(launch_errors)
            )

        self._ctx = self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            locale="en-US",
        )
        # Don't advertise "I'm an automated browser" to bot-detection scripts.
        self._ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        if self.mode == "old":
            # Skip the "are you over 18?" interstitial on NSFW subs.
            self._ctx.add_cookies([
                {"name": "over18", "value": "1", "domain": ".reddit.com", "path": "/"},
            ])
        else:
            # Redlib settings: light theme prints best; allow NSFW subreddits.
            self._ctx.add_cookies([
                {"name": "theme", "value": "light", "url": self.base},
                {"name": "show_nsfw", "value": "on", "url": self.base},
            ])
        return self

    def __exit__(self, *exc) -> None:
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass

    # navigation with retry --------------------------------------------------
    def _goto_raw(self, page, url: str, cancel: Optional[Event] = None) -> None:
        last = ""
        for attempt in range(4):
            if cancel and cancel.is_set():
                raise Cancelled()
            try:
                resp = page.goto(url, wait_until="load", timeout=60_000)
            except Exception as e:  # noqa: BLE001  (timeouts etc.)
                last = str(e).splitlines()[0]
                # A "load" timeout often still leaves a usable page.
                if "Timeout" in last and page.query_selector("#siteTable, .commentarea, div.post"):
                    return
                time.sleep(2 + attempt * 2)
                continue
            status = resp.status if resp else 0
            if status == 429:
                wait = 10 * (attempt + 1)
                self.log(f"  Rate-limited by Reddit (429). Waiting {wait}s...")
                for _ in range(wait):
                    if cancel and cancel.is_set():
                        raise Cancelled()
                    time.sleep(1)
                last = "HTTP 429"
                continue
            if status in (403, 404):
                raise ScrapeError(f"HTTP {status} for {url}")
            return
        raise ScrapeError(f"Failed to load {url} ({last})")

    def _goto(self, page, url: str, cancel: Optional[Event] = None,
              ready: Optional[str] = None, ready_timeout: Optional[float] = None) -> None:
        """Load *url*, then wait for the *ready* selector to appear.

        Reddit often answers first with a "Welcome to Reddit" JS-challenge /
        skeleton page and only swaps in the real page a few seconds later, so
        the 'load' event alone isn't enough.
        """
        self._goto_raw(page, url, cancel)
        if not ready:
            return
        deadline = time.time() + (self.ready_timeout if ready_timeout is None else ready_timeout)
        announced = False
        while time.time() < deadline:
            if cancel and cancel.is_set():
                raise Cancelled()
            try:
                page.wait_for_selector(ready, timeout=1500, state="attached")
                return
            except Exception:  # noqa: BLE001  (timeout / navigation in flight)
                if not announced:
                    self.log("  Waiting for the site to finish loading (challenge page?)...")
                    announced = True
        # Not ready: caller will diagnose from whatever is on screen.

    # listing -----------------------------------------------------------------
    def fetch_posts(self, sub: str, sort: str, time_filter: str, count: int,
                    progress: Callable[[int, int], None] = lambda a, b: None,
                    cancel: Optional[Event] = None,
                    query: Optional[str] = None) -> list[Post]:
        sub = clean_subreddit(sub)
        posts: list[Post] = []
        seen: set[str] = set()
        page = self._ctx.new_page()
        try:
            url = listing_url(self.base, self.mode, sub, sort, time_filter,
                              limit=min(100, max(count, 25)), query=query)
            ready = "#siteTable" if self.mode == "old" else "div.post, #error, #posts"
            while url and len(posts) < count:
                self.log(f"Loading listing: {url}")
                self._goto(page, url, cancel, ready=ready)

                data = page.evaluate(_PARSE_JS, self.mode)
                if not data["posts"] and not posts:
                    raise ScrapeError(self._diagnose(page, sub, sort, query))
                if not data["posts"]:
                    break
                for p in data["posts"]:
                    if p["fullname"] in seen or not p["permalink"]:
                        continue
                    seen.add(p["fullname"])
                    posts.append(Post(
                        rank=len(posts) + 1,
                        fullname=p["fullname"],
                        title=p["title"],
                        author=p["author"],
                        score=str(p["score"]).strip() or "?",
                        comments=p["comments"],
                        url=(p["permalink"] if p["permalink"].startswith("http")
                             else self.base + p["permalink"]),
                        stickied=p["stickied"],
                    ))
                    if len(posts) >= count:
                        break
                progress(len(posts), count)
                url = data["next"]
                if url and len(posts) < count:
                    time.sleep(self.delay)
        finally:
            page.close()
        if not posts:
            raise ScrapeError(f"No posts found for r/{sub} ({sort}).")
        return posts

    def _diagnose(self, page, sub: str, sort: str, query: Optional[str] = None) -> str:
        """Explain an empty listing and save the page for inspection."""
        try:
            title = page.title()
        except Exception:  # noqa: BLE001
            title = "?"
        try:
            text = " ".join((page.inner_text("body") or "").split())[:300]
        except Exception:  # noqa: BLE001
            text = "?"
        saved = ""
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            (self.debug_dir / "last_listing.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(self.debug_dir / "last_listing.png"), full_page=False)
            saved = f"\nSaved page snapshot to: {self.debug_dir}"
        except Exception:  # noqa: BLE001
            pass
        self.log(f"  Page URL:   {page.url}")
        self.log(f"  Page title: {title}")
        self.log(f"  Page text:  {text}")
        what = f"search \"{query}\" in r/{sub} ({sort})" if query else f"r/{sub} ({sort})"
        return (f"No posts found for {what}.\n"
                f"The site returned: \"{title}\" at {page.url}\n{text[:200]}{saved}")

    # pdf ---------------------------------------------------------------------
    def save_pdf(self, post: Post, out_dir: Path, *, paper: str = "Letter",
                 chrome_header_footer: bool = True, many_comments: bool = False,
                 cancel: Optional[Event] = None) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{post.rank:03d} - {safe_filename(post.title)} [{post.id}].pdf"
        dest = out_dir / name

        url = post.url
        if many_comments and self.mode == "old":
            url += ("&" if "?" in url else "?") + "limit=500"
        ready = ".commentarea" if self.mode == "old" else "div.post, #error"

        page = self._ctx.new_page()
        try:
            self._goto(page, url, cancel, ready=ready)
            page.wait_for_timeout(500)  # let late layout settle
            page.emulate_media(media="print")

            kwargs = dict(
                path=str(dest),
                format=paper,
                print_background=True,
                margin={"top": "0.4in", "bottom": "0.4in",
                        "left": "0.4in", "right": "0.4in"},
            )
            if chrome_header_footer:
                style = "font-size:8px; font-family:Arial,sans-serif; width:100%; padding:0 0.4in; color:#000;"
                kwargs["display_header_footer"] = True
                kwargs["header_template"] = (
                    f'<div style="{style} display:flex; justify-content:space-between;">'
                    '<span class="date"></span><span class="title"></span></div>'
                )
                kwargs["footer_template"] = (
                    f'<div style="{style} display:flex; justify-content:space-between;">'
                    '<span class="url"></span>'
                    '<span><span class="pageNumber"></span>/<span class="totalPages"></span></span></div>'
                )
            page.pdf(**kwargs)
        finally:
            page.close()
        return dest
