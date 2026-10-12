"""
Reddit -> PDF  (old.reddit.com)

Run:  python main.py
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    import sys
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    sys.exit(
        "Tkinter isn't available in this Python.\n"
        "It can't be installed with pip. On macOS with Homebrew, run:\n"
        f"    brew install python-tk@{v}\n"
        "then run this program again."
    )

if tk.TkVersion < 8.6:
    import sys
    sys.exit(
        f"This Python is using Tk {tk.TkVersion} (Apple's built-in one), which draws blank\n"
        "windows on modern macOS. Use a Python with Tk 8.6+, e.g. Homebrew's:\n"
        "    brew install python-tk@3.11\n"
        "    /opt/homebrew/bin/python3.11 main.py\n"
        f"(currently running: {sys.executable})"
    )

from scraper import (
    Cancelled, Post, RedditScraper, ScrapeError, SORTS, TIME_FILTERS,
    TIMED_SORTS, clean_subreddit, DEFAULT_BASE, SITE_PRESETS,
    SEARCH_SORTS, run_tag,
)

CHECK_ON, CHECK_OFF = "☑", "☐"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Reddit → PDF")
        self.geometry("900x740")
        self.minsize(760, 600)

        self.q: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None

        self.posts: list[Post] = []
        self.checked: set[str] = set()

        self._setup_theme()
        self._build_vars()
        self._build_ui()
        self._on_sort_change()
        self.update_idletasks()
        self._log(f"Tk {self.tk.call('info', 'patchlevel')} / "
                  f"{self.tk.call('tk', 'windowingsystem')} / theme '{self.style.theme_use()}'")
        self.after(100, self._poll_queue)

    # ----------------------------------------------------------------- theme
    def _setup_theme(self) -> None:
        """Use the pure-Tk 'clam' theme with explicit light colours.

        The native macOS ('aqua') ttk theme can render as a blank window on some
        Tk builds / dark-mode setups, so we avoid depending on it.
        """
        bg, fg, field, accent = "#f0f0f0", "#111111", "#ffffff", "#2f6fdb"
        self.configure(bg=bg)
        st = self.style = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=bg, foreground=fg, fieldbackground=field,
                     bordercolor="#b5b5b5", lightcolor=bg, darkcolor=bg)
        st.configure("TLabelframe", background=bg)
        st.configure("TLabelframe.Label", background=bg, foreground=fg)
        st.configure("TEntry", fieldbackground=field, foreground=fg)
        st.configure("TCombobox", fieldbackground=field, foreground=fg,
                     background="#e4e4e4", arrowcolor=fg)
        st.map("TCombobox", fieldbackground=[("readonly", field), ("disabled", bg)],
               foreground=[("disabled", "#888888")])
        st.configure("TButton", background="#e4e4e4", foreground=fg, padding=(10, 4))
        st.map("TButton", background=[("active", "#d4d4d4"), ("disabled", "#ececec")],
               foreground=[("disabled", "#999999")])
        st.configure("TNotebook", background=bg)
        st.configure("TNotebook.Tab", background="#dcdcdc", foreground=fg, padding=(8, 4))
        st.map("TNotebook.Tab", background=[("selected", field)])
        st.configure("Treeview", background=field, fieldbackground=field,
                     foreground=fg, rowheight=24)
        st.map("Treeview", background=[("selected", accent)],
               foreground=[("selected", "#ffffff")])
        st.configure("Treeview.Heading", background="#e4e4e4", foreground=fg)
        st.configure("Horizontal.TProgressbar", background=accent, troughcolor="#d8d8d8")

    # ------------------------------------------------------------------ vars
    def _build_vars(self) -> None:
        self.v_sub = tk.StringVar()
        self.v_sort = tk.StringVar(value="hot")
        self.v_time = tk.StringVar(value="week")
        self.v_out = tk.StringVar(value=str(Path.home() / "Documents" / "RedditPDFs"))
        self.v_paper = tk.StringVar(value="Letter")
        self.v_header = tk.BooleanVar(value=True)
        self.v_comments = tk.BooleanVar(value=False)
        self.v_show = tk.BooleanVar(value=False)
        self.v_site = tk.StringVar(value=DEFAULT_BASE)
        self.v_query = tk.StringVar()
        self._sort_touched = False
        self._time_touched = False
        self.v_load_n = tk.StringVar(value="50")
        self.v_batch = tk.StringVar(value="25")      # "25" | "50" | "100" | "custom"
        self.v_from = tk.IntVar(value=1)
        self.v_to = tk.IntVar(value=25)
        self.v_status = tk.StringVar(value="Ready.")

    # -------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- source ---------------------------------------------------------
        src = ttk.LabelFrame(self, text="Source")
        src.pack(fill="x", padx=10, pady=(10, 4))
        src.columnconfigure(1, weight=1)

        ttk.Label(src, text="Subreddit  r/").grid(row=0, column=0, sticky="e", **pad)
        sub_entry = ttk.Entry(src, textvariable=self.v_sub)
        sub_entry.grid(row=0, column=1, sticky="ew", **pad)
        sub_entry.focus_set()

        ttk.Label(src, text="Sort").grid(row=0, column=2, sticky="e", **pad)
        self.sort_cb = ttk.Combobox(src, textvariable=self.v_sort, values=SORTS,
                                    state="readonly", width=14)
        self.sort_cb.grid(row=0, column=3, **pad)
        self.sort_cb.bind("<<ComboboxSelected>>", lambda e: self._on_sort_picked())

        ttk.Label(src, text="Time").grid(row=0, column=4, sticky="e", **pad)
        self.time_cb = ttk.Combobox(src, textvariable=self.v_time, values=TIME_FILTERS,
                                    state="readonly", width=8)
        self.time_cb.grid(row=0, column=5, **pad)
        self.time_cb.bind("<<ComboboxSelected>>", lambda e: self._on_time_picked())

        ttk.Label(src, text="Search").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(src, textvariable=self.v_query).grid(row=1, column=1, columnspan=4,
                                                       sticky="ew", **pad)
        ttk.Label(src, text="(optional, inside r/)").grid(row=1, column=5, sticky="w", **pad)
        self.v_query.trace_add("write", lambda *a: self._on_query_change())

        ttk.Label(src, text="Save to").grid(row=2, column=0, sticky="e", **pad)
        ttk.Entry(src, textvariable=self.v_out).grid(row=2, column=1, columnspan=4,
                                                     sticky="ew", **pad)
        ttk.Button(src, text="Browse…", command=self._browse).grid(row=2, column=5, **pad)

        opts = ttk.Frame(src)
        opts.grid(row=3, column=0, columnspan=6, sticky="w", padx=8, pady=(0, 6))
        ttk.Label(opts, text="Site").pack(side="left")
        ttk.Combobox(opts, textvariable=self.v_site, values=SITE_PRESETS,
                     width=24).pack(side="left", padx=(4, 14))
        ttk.Label(opts, text="Paper").pack(side="left")
        ttk.Combobox(opts, textvariable=self.v_paper, values=["Letter", "A4"],
                     state="readonly", width=7).pack(side="left", padx=(4, 14))
        ttk.Checkbutton(opts, text="Chrome-style header/footer (date, title, URL, page #)",
                        variable=self.v_header).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(opts, text="500 comments (old.reddit only)",
                        variable=self.v_comments).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(opts, text="Show browser window",
                        variable=self.v_show).pack(side="left")

        # --- mode tabs ------------------------------------------------------
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=4)

        self._build_pick_tab()
        self._build_batch_tab()

        # --- progress / log -------------------------------------------------
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(4, 10))
        bottom.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.btn_cancel = ttk.Button(bottom, text="Cancel", command=self._cancel,
                                     state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(bottom, textvariable=self.v_status).grid(row=1, column=0, columnspan=2,
                                                          sticky="w", pady=(2, 4))
        log_frame = ttk.Frame(bottom)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.log = tk.Text(log_frame, height=7, state="disabled", wrap="word",
                           bg="#ffffff", fg="#111111", relief="solid", borderwidth=1,
                           font=("Menlo", 10) if self.tk.call("tk", "windowingsystem") == "aqua"
                           else ("Consolas", 9))
        sb = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

    def _build_pick_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Pick posts from a list  ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="Load").pack(side="left")
        ttk.Combobox(top, textvariable=self.v_load_n, values=["25", "50", "100", "200"],
                     width=5, state="readonly").pack(side="left", padx=4)
        ttk.Label(top, text="posts").pack(side="left")
        self.btn_load = ttk.Button(top, text="Load posts", command=self._load_posts)
        self.btn_load.pack(side="left", padx=10)

        self.lbl_sel = ttk.Label(top, text="0 selected")
        self.lbl_sel.pack(side="right")

        cols = ("check", "rank", "title", "score", "comments", "author")
        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True, padx=6)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for c, text, w, anchor in [
            ("check", "", 36, "center"), ("rank", "#", 44, "e"),
            ("title", "Title", 480, "w"), ("score", "Score", 64, "e"),
            ("comments", "Comments", 80, "e"), ("author", "Author", 130, "w"),
        ]:
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "title"))
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", padx=6, pady=6)
        ttk.Button(btns, text="Select all", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text="Select none", command=lambda: self._set_all(False)).pack(side="left", padx=6)
        ttk.Button(btns, text="Invert", command=self._invert).pack(side="left")
        self.btn_dl_sel = ttk.Button(btns, text="Download selected as PDF",
                                     command=self._download_selected)
        self.btn_dl_sel.pack(side="right")

    def _build_batch_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Automatic batch  ")

        ttk.Label(tab, text="Download the top-ranked posts of the chosen sort, in order, without picking.",
                  wraplength=700).pack(anchor="w", padx=12, pady=(12, 6))

        box = ttk.Frame(tab)
        box.pack(anchor="w", padx=12, pady=6)
        for text, val in [("Posts 1 – 25", "25"), ("Posts 1 – 50", "50"), ("Posts 1 – 100", "100")]:
            ttk.Radiobutton(box, text=text, value=val, variable=self.v_batch).pack(anchor="w", pady=2)

        custom = ttk.Frame(box)
        custom.pack(anchor="w", pady=2)
        ttk.Radiobutton(custom, text="Custom range:", value="custom",
                        variable=self.v_batch).pack(side="left")
        ttk.Spinbox(custom, from_=1, to=1000, width=6, textvariable=self.v_from,
                    command=lambda: self.v_batch.set("custom")).pack(side="left", padx=(8, 4))
        ttk.Label(custom, text="to").pack(side="left")
        ttk.Spinbox(custom, from_=1, to=1000, width=6, textvariable=self.v_to,
                    command=lambda: self.v_batch.set("custom")).pack(side="left", padx=4)

        self.btn_batch = ttk.Button(tab, text="Start batch download", command=self._download_batch)
        self.btn_batch.pack(anchor="w", padx=12, pady=14)

    # -------------------------------------------------------------- helpers
    def _query(self) -> str | None:
        return self.v_query.get().strip() or None

    def _on_sort_change(self) -> None:
        enabled = bool(self._query()) or self.v_sort.get() in TIMED_SORTS
        self.time_cb.configure(state="readonly" if enabled else "disabled")

    def _on_sort_picked(self) -> None:
        self._sort_touched = True
        self._on_sort_change()

    def _on_time_picked(self) -> None:
        self._time_touched = True

    def _on_query_change(self) -> None:
        """Switch the Sort/Time choices between browsing and searching."""
        searching = bool(self._query())
        self.sort_cb.configure(values=SEARCH_SORTS if searching else SORTS)
        allowed = SEARCH_SORTS if searching else SORTS
        if not self._sort_touched or self.v_sort.get() not in allowed:
            self.v_sort.set("relevance" if searching else "hot")
        if not self._time_touched:
            self.v_time.set("all" if searching else "week")
        self._on_sort_change()

    def _browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self.v_out.get() or str(Path.home()))
        if d:
            self.v_out.set(d)

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_load, self.btn_dl_sel, self.btn_batch):
            b.configure(state=state)
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        if not busy:
            self.progress.configure(value=0)

    def _validate_source(self) -> str | None:
        try:
            return clean_subreddit(self.v_sub.get())
        except ScrapeError as e:
            messagebox.showerror("Subreddit", str(e))
            return None

    def _out_dir(self, sub: str) -> Path:
        tag = run_tag(self.v_sort.get(), self.v_time.get(), self._query())
        return Path(self.v_out.get()).expanduser() / f"r_{sub}_{tag}"

    def _start_worker(self, target, *args) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.cancel_event.clear()
        self._set_busy(True)
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.v_status.set("Cancelling…")

    # ---------------------------------------------------- list / checkboxes
    def _populate(self, posts: list[Post]) -> None:
        self.posts = posts
        self.checked.clear()
        self.tree.delete(*self.tree.get_children())
        for p in posts:
            title = ("📌 " if p.stickied else "") + p.title
            self.tree.insert("", "end", iid=p.fullname,
                             values=(CHECK_OFF, p.rank, title, p.score, p.comments, p.author))
        self._update_sel_label()

    def _toggle(self, iid: str) -> None:
        if iid in self.checked:
            self.checked.discard(iid)
            mark = CHECK_OFF
        else:
            self.checked.add(iid)
            mark = CHECK_ON
        self.tree.set(iid, "check", mark)
        self._update_sel_label()

    def _on_tree_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_column(event.x) == "#1":
            self._toggle(iid)
            return "break"

    def _on_tree_space(self, event) -> None:
        for iid in self.tree.selection():
            self._toggle(iid)
        return "break"

    def _set_all(self, on: bool) -> None:
        self.checked = {p.fullname for p in self.posts} if on else set()
        for p in self.posts:
            self.tree.set(p.fullname, "check", CHECK_ON if on else CHECK_OFF)
        self._update_sel_label()

    def _invert(self) -> None:
        for p in self.posts:
            self._toggle(p.fullname)

    def _update_sel_label(self) -> None:
        self.lbl_sel.configure(text=f"{len(self.checked)} of {len(self.posts)} selected")

    # --------------------------------------------------------------- actions
    def _load_posts(self) -> None:
        sub = self._validate_source()
        if not sub:
            return
        q = self._query()
        self.v_status.set(f'Searching r/{sub} for "{q}"…' if q else f"Loading r/{sub}…")
        self._start_worker(self._w_load, sub, self.v_sort.get(), self.v_time.get(),
                           int(self.v_load_n.get()), self._scraper_args(), q)

    def _download_selected(self) -> None:
        sub = self._validate_source()
        if not sub:
            return
        chosen = [p for p in self.posts if p.fullname in self.checked]
        if not chosen:
            messagebox.showinfo("Nothing selected", "Tick at least one post first.")
            return
        self._start_worker(self._w_download, sub, chosen, self._opts(), self._scraper_args())

    def _download_batch(self) -> None:
        sub = self._validate_source()
        if not sub:
            return
        mode = self.v_batch.get()
        try:
            if mode == "custom":
                n1, n2 = int(self.v_from.get()), int(self.v_to.get())
            else:
                n1, n2 = 1, int(mode)
        except (tk.TclError, ValueError):
            messagebox.showerror("Range", "Enter whole numbers for the range.")
            return
        if n1 < 1 or n2 < n1:
            messagebox.showerror("Range", "Range must satisfy 1 ≤ from ≤ to.")
            return
        self._start_worker(self._w_batch, sub, self.v_sort.get(), self.v_time.get(),
                           n1, n2, self._opts(), self._scraper_args(), self._query())

    def _scraper_args(self) -> dict:
        base = self.v_site.get().strip() or DEFAULT_BASE
        if not base.startswith(("http://", "https://")):
            base = "https://" + base
        return {"headless": not self.v_show.get(), "base": base.rstrip("/")}

    def _opts(self) -> dict:
        return dict(
            out_dir=self._out_dir(clean_subreddit(self.v_sub.get())),
            paper=self.v_paper.get(),
            chrome_header_footer=self.v_header.get(),
            many_comments=self.v_comments.get(),
            sort=self.v_sort.get(),
        )

    # --------------------------------------------------- worker thread code
    # (these run off the UI thread; talk to the UI only through self.q)
    def _qlog(self, msg: str) -> None:
        self.q.put(("log", msg))

    def _w_load(self, sub, sort, tf, count, sargs, query=None) -> None:
        try:
            with RedditScraper(**sargs, log=self._qlog) as s:
                posts = s.fetch_posts(
                    sub, sort, tf, count,
                    progress=lambda a, b: self.q.put(("progress", a, b)),
                    cancel=self.cancel_event, query=query)
            self.q.put(("posts", posts))
            self.q.put(("done", f"Loaded {len(posts)} posts from r/{sub}."))
        except Cancelled:
            self.q.put(("done", "Cancelled."))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def _w_batch(self, sub, sort, tf, n1, n2, opts, sargs, query=None) -> None:
        try:
            with RedditScraper(**sargs, log=self._qlog) as s:
                self.q.put(("status", f"Fetching listing up to post {n2}…"))
                posts = s.fetch_posts(
                    sub, sort, tf, n2,
                    progress=lambda a, b: self.q.put(("progress", a, b)),
                    cancel=self.cancel_event, query=query)
                chosen = posts[n1 - 1:n2]
                if not chosen:
                    raise ScrapeError(f"r/{sub} only has {len(posts)} posts; nothing in {n1}–{n2}.")
                self._download_with(s, chosen, opts)
        except Cancelled:
            self.q.put(("done", "Cancelled."))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def _w_download(self, sub, chosen, opts, sargs) -> None:
        try:
            with RedditScraper(**sargs, log=self._qlog) as s:
                self._download_with(s, chosen, opts)
        except Cancelled:
            self.q.put(("done", "Cancelled."))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def _download_with(self, s: RedditScraper, chosen: list[Post], opts: dict) -> None:
        total = len(chosen)
        ok = failed = 0
        self.q.put(("progress", 0, total))
        for i, p in enumerate(chosen, 1):
            if self.cancel_event.is_set():
                raise Cancelled()
            self.q.put(("status", f"[{i}/{total}] {p.title[:70]}"))
            try:
                path = s.save_pdf(
                    p, opts["out_dir"], paper=opts["paper"],
                    chrome_header_footer=opts["chrome_header_footer"],
                    many_comments=opts["many_comments"], cancel=self.cancel_event)
                self._qlog(f"✔ {path.name}")
                ok += 1
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                self._qlog(f"✘ #{p.rank} {p.title[:60]} — {e}")
                failed += 1
            self.q.put(("progress", i, total))
            if i < total:
                time.sleep(s.delay)
        self.q.put(("done", f"Finished: {ok} saved, {failed} failed → {opts['out_dir']}"))

    # ------------------------------------------------------- queue polling
    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "status":
                    self.v_status.set(msg[1])
                elif kind == "progress":
                    _, done, total = msg
                    self.progress.configure(maximum=max(total, 1), value=done)
                elif kind == "posts":
                    self._populate(msg[1])
                elif kind == "done":
                    self.v_status.set(msg[1])
                    self._log(msg[1])
                    self._set_busy(False)
                elif kind == "error":
                    self.v_status.set("Error.")
                    self._log("ERROR: " + msg[1])
                    self._set_busy(False)
                    messagebox.showerror("Error", msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


if __name__ == "__main__":
    App().mainloop()
