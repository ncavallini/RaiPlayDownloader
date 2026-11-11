# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RaiPlay Downloader (version in `main.__version__`) is a single-file Python CLI tool for downloading videos from RaiPlay (Italian public broadcaster RAI's streaming platform). It supports downloading individual episodes or entire seasons in batch using multiprocessing.

## Commands

```bash
# Run the application
python main.py

# Build Windows executable with PyInstaller
pyinstaller main.spec

# Install dependencies (no requirements.txt exists; install manually)
pip install "yt-dlp[default]" requests beautifulsoup4 tqdm customtkinter pyinstaller

# Run the GUI (customtkinter; downloads up to 8 episodes in parallel via ThreadPool)
python gui.py
```

Releases: publishing a GitHub release runs `.github/workflows/release.yml`, which builds the GUI with PyInstaller for Windows (.exe plus an Inno Setup installer from `installer.iss`), macOS (.app zip) and Linux, repackages the Linux build as a Flatpak (`io.github.ncavallini.RaiPlayDownloader.yml`), and attaches all three to the release.

There are no tests or linting configured.

## Architecture

The entire application lives in `main.py`. Key components:

- **`get_episodes_json(url)`** — Scrapes a RaiPlay series page for a `<rai-episodes>` custom element, constructs a JSON API URL from its attributes (`base_path`, `block`, `set`, `episode_path`), and returns the season/episode metadata.
- **`single_request(url, path)`** — Downloads one episode. Converts the `.html` URL to `.json` to fetch metadata, cleans the filename, and uses yt-dlp with format `best[height<=720]/best`.
- **`batch_request(title_url, season_number, path, first_episode)`** — Downloads all episodes of a season using `multiprocessing.Pool` (max 4 workers). Uses `imap` for streaming results with a tqdm overall progress bar.
- **`download_single_episode(args)`** — Worker function unpacked by the pool; wraps a single yt-dlp download with progress tracking.
- **`ProgressHook`** — Callable class that bridges yt-dlp's progress callback to tqdm progress bars.
- **`main()`** — Interactive CLI menu with three modes: single video, batch season, or test download (which also lists available formats).

**Data flow:** RaiPlay HTML page → scrape `<rai-episodes>` attributes → construct JSON API URL → fetch episode metadata → download via yt-dlp.

## Key Dependencies

- **yt-dlp** — Video downloading (core engine)
- **requests** — HTTP requests to RaiPlay pages and JSON API
- **beautifulsoup4** — HTML parsing to extract `<rai-episodes>` element
- **tqdm** — Progress bars for downloads

## Build Configuration

`main.spec` is the PyInstaller spec file. It produces a single console executable (`dist/main.exe`) with UPX compression enabled. No hidden imports or extra data files are bundled.
