# RaiPlay Downloader

Download single episodes or whole seasons from [RaiPlay](https://www.raiplay.it), in the best available quality, up to 8 episodes at a time.

## Download

Get the latest build from the [Releases page](https://github.com/ncavallini/RaiPlayDownloader/releases/latest):

| Platform | File | Notes |
|----------|------|-------|
| Windows | `RaiPlayDownloader-windows.exe` | Just run it. SmartScreen may warn because the exe is unsigned: *More info → Run anyway*. |
| macOS (Apple Silicon) | `RaiPlayDownloader-macos.zip` | Unzip, then right-click the app → *Open* the first time (the app is unsigned). |
| Linux | `RaiPlayDownloader.flatpak` | `flatpak install --user RaiPlayDownloader.flatpak` (needs the `org.freedesktop.Platform//25.08` runtime from Flathub). |

Install [ffmpeg](https://ffmpeg.org/download.html) and put it on your `PATH` for the best quality: without it, videos are downloaded as a single combined stream, which can be lower quality.

## Usage

1. Choose **Single video** and paste an episode link, or **Full season** and paste the series link (e.g. `https://www.raiplay.it/programmi/...`).
2. Pick the folder to save into.
3. For a season, set the season number and, optionally, how many episodes to skip.
4. Click **Download**. Each episode gets its own progress bar; failed episodes are retried 3 times and listed at the end.

Some RaiPlay content is only available from Italy.

## Run from source

Requires Python 3.11+.

```bash
pip install yt-dlp requests beautifulsoup4 tqdm customtkinter
python gui.py    # graphical app
python main.py   # interactive command-line version
```

## Releasing

Publishing a GitHub release runs `.github/workflows/release.yml`, which builds the Windows, macOS and Flatpak packages and attaches them to the release.

## Disclaimer

For personal use only. Respect RaiPlay's terms of service and the copyright of the content you download.
