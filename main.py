from os import sep
from multiprocessing import Pool
import os
import shutil
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yt_dlp
from bs4 import BeautifulSoup
import sys
import time
from tqdm import tqdm
import threading


def create_session():
    """Create a requests session with timeout and retry logic."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


__version__ = "1.0.1"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 8

session = create_session()


def read_int(prompt, default=None):
    """Read an integer from input with validation. Returns default on empty input if provided."""
    while True:
        raw = input(prompt).strip()
        if raw == "" and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("Please enter a valid number.")


def validate_path(path):
    """Check that a directory path exists and is writable. Returns True if valid."""
    if not os.path.isdir(path):
        print(f"Error: Directory does not exist: {path}")
        return False
    test_file = os.path.join(path, ".raiplay_write_test")
    try:
        with open(test_file, "w") as f:
            f.write("")
        os.remove(test_file)
    except OSError:
        print(f"Error: Directory is not writable: {path}")
        return False
    return True


def check_ffmpeg():
    """Check if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def raiplay_url_to_json(url):
    """Convert a RaiPlay .html URL to its .json metadata endpoint.
    Returns the json URL or None if the URL doesn't look right."""
    if not url.rstrip("/").endswith(".html"):
        print("Error: URL doesn't look like a RaiPlay page (expected .html extension).")
        return None
    return url.rstrip("/")[:-5] + ".json"


def get_episodes_json(url):
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        rai_episodes = soup.find("rai-episodes")
        if not rai_episodes:
            print("Error: Could not find rai-episodes element. The page structure might have changed.")
            return None

        required_attrs = ['base_path', 'block', 'set', 'episode_path']
        for attr in required_attrs:
            if attr not in rai_episodes.attrs:
                print(f"Error: <rai-episodes> is missing the '{attr}' attribute. Page structure may have changed.")
                return None

        json_url = "https://www.raiplay.it%s/%s/%s/%s" % (
            rai_episodes['base_path'], rai_episodes['block'], rai_episodes['set'], rai_episodes['episode_path'])
        json_response = session.get(json_url, timeout=REQUEST_TIMEOUT)
        json_response.raise_for_status()
        return json_response.json()
    except requests.exceptions.HTTPError as e:
        print(f"Error: HTTP {e.response.status_code} when fetching episodes: {e}")
        return None
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to RaiPlay. Check your internet connection.")
        return None
    except requests.exceptions.Timeout:
        print("Error: Request timed out. RaiPlay may be slow or unreachable.")
        return None
    except Exception as e:
        print(f"Error getting episodes JSON: {e}")
        return None


def get_available_formats(url):
    """Get available formats for debugging."""
    try:
        yt_opts = {'listformats': True}
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Error listing formats: {e}")


def build_yt_opts(output_path, name, progress_hook=None, quiet=False):
    """Build yt-dlp options dict with proper format selection and resume support."""
    has_ffmpeg = check_ffmpeg()
    fmt = 'bestvideo+bestaudio/best' if has_ffmpeg else 'best'

    opts = {
        'outtmpl': f'{output_path}{sep}{name}.%(ext)s',
        'format': fmt,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'continuedl': True,
        'quiet': quiet,
        # our own bars (tqdm / GUI rows) show progress; yt-dlp's lines flooded the GUI log and froze it
        'noprogress': True,
    }
    if has_ffmpeg:
        opts['merge_output_format'] = 'mp4'
    if progress_hook:
        opts['progress_hooks'] = [progress_hook]
    return opts


class ProgressHook:
    def __init__(self, title="Downloading"):
        self.pbar = None
        self.title = title
    
    def __call__(self, d):
        if d['status'] == 'downloading':
            if self.pbar is None:
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                if total:
                    self.pbar = tqdm(total=total, unit='B', unit_scale=True, desc=self.title)
            
            if self.pbar:
                downloaded = d.get('downloaded_bytes', 0)
                self.pbar.n = downloaded
                self.pbar.refresh()
                
        elif d['status'] == 'finished' and self.pbar:
            self.pbar.close()
            print(f"[OK] Download completed: {d['filename']}")


def single_request(url, path):
    if not validate_path(path):
        return

    json_url = raiplay_url_to_json(url)
    if not json_url:
        return

    try:
        response = session.get(json_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        json_data = response.json()
    except requests.exceptions.HTTPError as e:
        print(f"Error: HTTP {e.response.status_code} fetching metadata for {json_url}")
        return
    except requests.exceptions.RequestException as e:
        print(f"Error fetching metadata: {e}")
        return

    name = json_data.get("name", "unknown_video")
    name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()

    progress_hook = ProgressHook(f"Downloading: {name[:30]}...")
    yt_opts = build_yt_opts(path, name, progress_hook=progress_hook)

    try:
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        print("Available formats:")
        get_available_formats(url)


EPISODE_MAX_RETRIES = 3


def download_single_episode(args, progress_hook=None):
    """Wrapper function for multiprocessing that handles a single episode with retries."""
    card, path, episode_num, total_episodes = args
    name = card.get('name', 'unknown')
    name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    url = "https://www.raiplay.it" + card['weblink']

    # In CLI batch mode no hook is passed, so no per-episode bars overlap in the terminal
    yt_opts = build_yt_opts(path, name, progress_hook=progress_hook, quiet=True)

    last_error = None
    for attempt in range(1, EPISODE_MAX_RETRIES + 1):
        try:
            with yt_dlp.YoutubeDL(yt_opts) as ydl:
                ydl.download([url])
            return f"[OK] Successfully downloaded: {name}"
        except Exception as e:
            last_error = e
            if attempt < EPISODE_MAX_RETRIES:
                time.sleep(2 * attempt)

    return f"[FAIL] Error downloading {name} after {EPISODE_MAX_RETRIES} attempts: {last_error}"


def batch_request(title_url, season_number, path, first_episode=0):
    if not validate_path(path):
        return

    data = get_episodes_json(title_url)
    if not data:
        return
        
    try:
        seasons = data['seasons']
        cards = seasons[season_number]['episodes'][0]['cards']
        
        # Prepare arguments for multiprocessing
        total_episodes = len(cards) - first_episode
        download_args = [(cards[i], path, i - first_episode + 1, total_episodes) 
                        for i in range(first_episode, len(cards))]
        
        print(f"Starting batch download of {total_episodes} episodes...")
        print("=" * 60)
        
        max_processes = min(MAX_WORKERS, len(download_args))
        
        # Create overall progress bar for batch download
        overall_progress = tqdm(total=total_episodes, desc="Overall Progress", 
                              position=0, leave=True, unit="episode")
        
        with Pool(max_processes) as p:
            # Use imap to get results as they complete
            results = []
            for result in p.imap(download_single_episode, download_args):
                results.append(result)
                overall_progress.update(1)
                # Print the result immediately
                tqdm.write(result)
        
        overall_progress.close()
        
        print("\n" + "=" * 60)
        print("BATCH DOWNLOAD SUMMARY:")
        print("=" * 60)
        
        successful = sum(1 for r in results if r.startswith("[OK]"))
        failed = len(results) - successful
        
        print(f"Total episodes: {len(results)}")
        print(f"[OK] Successful: {successful}")
        print(f"[FAIL] Failed: {failed}")
        
        if failed > 0:
            print("\nFailed downloads:")
            for result in results:
                if result.startswith("[FAIL]"):
                    print(f"  {result}")
            
    except (KeyError, IndexError) as e:
        print(f"Error accessing episode data: {e}")
        print("Available seasons/episodes structure might have changed.")
    except Exception as e:
        print(f"Error in batch download: {e}")


def test_single_download():
    """Test function to check if a single download works"""
    url = input("Insert a single RaiPlay URL to test: ")
    path = input("Insert path to save the test video: ")
    
    print("Testing formats available...")
    get_available_formats(url)
    
    print("\nAttempting download with progress bar...")
    single_request(url, path)


def main():
    if not check_ffmpeg():
        print("Warning: ffmpeg not found on PATH. Downloads will use single-stream format")
        print("(lower quality). Install ffmpeg for best results.\n")

    choice = 0
    while choice not in [1, 2, 3]:
        print(f"=== RaiPlay Downloader {__version__} ===")
        print("Choose an option:\n")
        choice = read_int("""
        [1]: One video
        [2]: All episodes of a serie
        [3]: Test single download (with format info)
        """)

    if choice == 1:
        url = input("Insert RaiPlay URL\n").strip()
        path = input("Insert path to save the video\n").strip()
        single_request(url, path)
    elif choice == 2:
        title_url = input("Insert RaiPlay URL of the serie\n").strip()
        season_number = read_int("Insert season number\n") - 1
        path = input("Insert path to save the videos\n").strip()
        first_episode = read_int("Insert the first episode to download (0 for all)\n", default=0)
        batch_request(title_url, season_number, path, first_episode)
    else:
        test_single_download()


if __name__ == '__main__':
    main()