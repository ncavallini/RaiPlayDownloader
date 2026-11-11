"""RaiPlay Downloader — customtkinter GUI."""

import sys
import threading
from functools import partial
from multiprocessing.pool import ThreadPool
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp

from main import (
    check_ffmpeg, validate_path, raiplay_url_to_json, build_yt_opts,
    get_episodes_json, download_single_episode, session, REQUEST_TIMEOUT, MAX_WORKERS, __version__,
)

SINGLE, SEASON = "Single video", "Full season"
MUTED = ("gray40", "gray60")
GREEN = ("#1e9e5a", "#2ecc71")
RED = ("#d64545", "#ff6b6b")


def clean_name(name):
    return "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).rstrip()


class TextRedirector:
    """Redirects writes to a text widget (thread-safe)."""

    def __init__(self, widget):
        self.widget = widget

    def write(self, text):
        self.widget.after(0, self._append, text)

    def _append(self, text):
        self.widget.configure(state="normal")
        self.widget.insert("end", text)
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def flush(self):
        pass


class EpisodeRow(ctk.CTkFrame):
    """One download in the list: name, status text and its own progress bar."""

    def __init__(self, master, name):
        super().__init__(master, corner_radius=8, fg_color=("gray95", "gray20"))
        self.name = name
        self.grid_columnconfigure(0, weight=1)
        title = name if len(name) <= 55 else name[:54] + "…"
        ctk.CTkLabel(self, text=title, anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.info = ctk.CTkLabel(self, text="Queued", text_color=MUTED, anchor="e")
        self.info.grid(row=0, column=1, sticky="e", padx=12, pady=(8, 0))
        self.bar = ctk.CTkProgressBar(self, height=6)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 12))

    def set_progress(self, fraction, text):
        if fraction is not None:
            self.bar.set(fraction)
        self.info.configure(text=text)

    def done(self, ok):
        color = GREEN if ok else RED
        self.bar.configure(progress_color=color)
        self.bar.set(1)
        self.info.configure(text="Done" if ok else "Failed", text_color=color)


class GuiProgressHook:
    """yt-dlp progress hook that updates one EpisodeRow from a worker thread."""

    def __init__(self, row):
        self.row = row
        self.last_text = None

    def __call__(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                fraction = min(downloaded / total, 1)
                text = f"{downloaded / 1_048_576:.0f} / {total / 1_048_576:.0f} MB · {fraction:.0%}"
            else:
                fraction, text = None, f"{downloaded / 1_048_576:.0f} MB"
            # yt-dlp calls this many times per second per worker; only redraw on visible change
            if text != self.last_text:
                self.last_text = text
                self.row.after(0, self.row.set_progress, fraction, text)
        elif d["status"] == "finished":
            self.row.after(0, self.row.set_progress, 1, "Finalising…")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        self.title(f"RaiPlay Downloader {__version__}")
        self.geometry("720x880")
        self.minsize(600, 700)
        self.rows = []

        self._build_ui()
        # Permanent redirect: a windowed build has no console, so yt-dlp/print output goes to the log
        sys.stdout = sys.stderr = TextRedirector(self.log_text)
        self._check_ffmpeg()

    # ── UI construction ──────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        small = ctk.CTkFont(size=12)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        ctk.CTkLabel(header, text="RaiPlay Downloader", font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text=f"Single episodes or whole seasons, best quality, {MAX_WORKERS} at a time",
                     text_color=MUTED).pack(anchor="w")

        # Form card
        form = ctk.CTkFrame(self, corner_radius=12)
        form.grid(row=1, column=0, sticky="ew", padx=24, pady=8)
        form.grid_columnconfigure(0, weight=1)

        self.mode = ctk.CTkSegmentedButton(form, values=[SINGLE, SEASON], command=self._on_mode_change)
        self.mode.set(SINGLE)
        self.mode.grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 8))

        self.url_label = ctk.CTkLabel(form, text="Video link", font=small, text_color=MUTED)
        self.url_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=16)
        self.url_entry = ctk.CTkEntry(form, height=36, placeholder_text="https://www.raiplay.it/…")
        self.url_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16)

        ctk.CTkLabel(form, text="Save to", font=small, text_color=MUTED).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 0))
        self.path_entry = ctk.CTkEntry(form, height=36, placeholder_text="Choose a folder…")
        self.path_entry.grid(row=4, column=0, sticky="ew", padx=(16, 8))
        ctk.CTkButton(form, text="Browse", width=96, height=36, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self._browse).grid(row=4, column=1, padx=(0, 16))

        self.season_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.season_frame.grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(12, 0))
        self.season_var = ctk.StringVar(value="1")
        self.skip_var = ctk.StringVar(value="0")
        ctk.CTkLabel(self.season_frame, text="Season").pack(side="left")
        ctk.CTkEntry(self.season_frame, textvariable=self.season_var, width=56).pack(side="left", padx=(8, 24))
        ctk.CTkLabel(self.season_frame, text="Skip first").pack(side="left")
        ctk.CTkEntry(self.season_frame, textvariable=self.skip_var, width=56).pack(side="left", padx=8)
        ctk.CTkLabel(self.season_frame, text="episodes").pack(side="left")
        self.season_frame.grid_remove()

        self.download_btn = ctk.CTkButton(form, text="Download", height=44,
                                          font=ctk.CTkFont(size=15, weight="bold"), command=self._start_download)
        self.download_btn.grid(row=6, column=0, columnspan=2, sticky="ew", padx=16, pady=16)

        # Overall progress
        overall = ctk.CTkFrame(self, fg_color="transparent")
        overall.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 0))
        overall.grid_columnconfigure(0, weight=1)
        self.status_var = ctk.StringVar(value="Ready")
        self.count_var = ctk.StringVar(value="")
        ctk.CTkLabel(overall, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(overall, textvariable=self.count_var, text_color=MUTED).grid(row=0, column=1, sticky="e")
        self.progressbar = ctk.CTkProgressBar(overall, height=10)
        self.progressbar.set(0)
        self.progressbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Per-episode list
        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Downloads", corner_radius=12)
        self.list_frame.grid(row=3, column=0, sticky="nsew", padx=24, pady=12)

        # Log
        self.log_text = ctk.CTkTextbox(self, height=90, corner_radius=12, state="disabled",
                                       font=ctk.CTkFont(family="Consolas", size=11))
        self.log_text.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 20))

    # ── Helpers ───────────────────────────────────────────────────

    def _on_mode_change(self, mode):
        if mode == SEASON:
            self.url_label.configure(text="Series link")
            self.season_frame.grid()
        else:
            self.url_label.configure(text="Video link")
            self.season_frame.grid_remove()

    def _browse(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _set_status(self, msg):
        self.after(0, self.status_var.set, msg)

    def _set_overall(self, done, total):
        self.progressbar.set(done / total)
        self.count_var.set(f"{done} / {total}")

    def _check_ffmpeg(self):
        if not check_ffmpeg():
            print("Warning: ffmpeg not found on PATH. Downloads will use "
                  "single-stream format (lower quality). Install ffmpeg for best results.")

    def _finish(self, success, summary):
        """Called (from any thread) when a download run completes."""
        def _on_main():
            self.download_btn.configure(state="normal", text="Download")
            print(summary)
            if success:
                self.status_var.set("Done")
                messagebox.showinfo("Download complete", summary)
            else:
                self.status_var.set("Finished with errors")
                messagebox.showwarning("Download finished with errors", summary)
        self.after(0, _on_main)

    # ── Download logic ───────────────────────────────────────────

    def _start_download(self):
        url = self.url_entry.get().strip()
        path = self.path_entry.get().strip()
        if not url:
            print("Error: Please enter a RaiPlay URL.")
            return
        if not path:
            print("Error: Please choose a save path.")
            return
        try:
            season = int(self.season_var.get()) - 1
            skip = int(self.skip_var.get())
        except ValueError:
            print("Error: Season and skipped episodes must be whole numbers.")
            return

        self.download_btn.configure(state="disabled", text="Working…")
        for row in self.rows:
            row.destroy()
        self.rows = []
        self.progressbar.set(0)
        self.count_var.set("")
        self.status_var.set("Starting…")
        threading.Thread(target=self._prepare, args=(url, path, season, skip), daemon=True).start()

    def _prepare(self, url, path, season, skip):
        """Worker thread: fetch metadata, then hand the job list to the main thread."""
        try:
            if self.mode.get() == SINGLE:
                jobs = self._single_jobs(url, path)
            else:
                jobs = self._season_jobs(url, season, path, skip)
        except Exception as exc:
            self._finish(False, str(exc))
            return
        self.after(0, self._start_jobs, jobs)

    def _single_jobs(self, url, path):
        if not validate_path(path):
            raise ValueError("Invalid save path.")
        json_url = raiplay_url_to_json(url)
        if not json_url:
            raise ValueError("Invalid RaiPlay URL.")

        self._set_status("Fetching metadata…")
        try:
            response = session.get(json_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            name = clean_name(response.json().get("name", "unknown_video"))
        except Exception as e:
            raise ValueError(f"Error fetching metadata: {e}")

        def run(hook):
            try:
                with yt_dlp.YoutubeDL(build_yt_opts(path, name, progress_hook=hook, quiet=True)) as ydl:
                    ydl.download([url])
                return f"[OK] Successfully downloaded: {name}"
            except Exception as e:
                return f"[FAIL] Download failed for {name}: {e}"

        return [(name, run)]

    def _season_jobs(self, title_url, season_number, path, skip):
        if not validate_path(path):
            raise ValueError("Invalid save path.")

        self._set_status("Fetching episode list…")
        data = get_episodes_json(title_url)
        if not data:
            raise ValueError("Could not fetch episode data.")
        try:
            cards = data["seasons"][season_number]["episodes"][0]["cards"][skip:]
        except (KeyError, IndexError) as e:
            raise ValueError(f"Error reading episode structure: {e}")
        if not cards:
            raise ValueError("No episodes to download with the given skip count.")

        total = len(cards)
        return [(clean_name(card.get("name", "unknown")),
                 partial(download_single_episode, (card, path, i + 1, total)))
                for i, card in enumerate(cards)]

    def _start_jobs(self, jobs):
        """Main thread: build one row per job, then download them in parallel."""
        self.rows = [EpisodeRow(self.list_frame, name) for name, _ in jobs]
        for row in self.rows:
            row.pack(fill="x", pady=4)
        self._set_overall(0, len(jobs))
        self.status_var.set(f"Downloading {len(jobs)} video(s)…")
        threading.Thread(target=self._run_jobs, args=(list(zip(self.rows, (run for _, run in jobs))),),
                         daemon=True).start()

    @staticmethod
    def _run_one(job):
        row, run = job
        try:
            return row, run(GuiProgressHook(row))
        except Exception as e:
            return row, f"[FAIL] Error downloading {row.name}: {e}"

    def _run_jobs(self, jobs):
        failed = []
        # ThreadPool (not Pool): GUI rows can't be pickled, and its daemon threads don't block closing the window
        with ThreadPool(min(MAX_WORKERS, len(jobs))) as pool:
            for done, (row, result) in enumerate(pool.imap_unordered(self._run_one, jobs), 1):
                print(result)
                ok = result.startswith("[OK]")
                if not ok:
                    failed.append(row.name)
                self.after(0, row.done, ok)
                self.after(0, self._set_overall, done, len(jobs))

        summary = f"{len(jobs) - len(failed)}/{len(jobs)} downloaded, {len(failed)} failed."
        if failed:
            summary += "\nFailed: " + ", ".join(failed)
        self._finish(not failed, summary)


if __name__ == "__main__":
    App().mainloop()
