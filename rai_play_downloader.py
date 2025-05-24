from os import sep
from multiprocessing import Pool
import requests
import yt_dlp
from bs4 import BeautifulSoup
import sys
from tqdm import tqdm
import threading


def get_episodes_json(url):
    try:
        soup = BeautifulSoup(requests.get(url).text, 'html.parser')
        rai_episodes = soup.find("rai-episodes")
        if not rai_episodes:
            print("Error: Could not find rai-episodes element. The page structure might have changed.")
            return None
        json_url = "https://www.raiplay.it%s/%s/%s/%s" % (
            rai_episodes['base_path'], rai_episodes['block'], rai_episodes['set'], rai_episodes['episode_path'])
        return requests.get(json_url).json()
    except Exception as e:
        print(f"Error getting episodes JSON: {e}")
        return None


def get_available_formats(url):
    """Get available formats for debugging"""
    try:
        yt_opts = {'listformats': True}
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Error listing formats: {e}")


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
            print(f"✓ Download completed: {d['filename']}")


def single_request(url, path):
    try:
        json_url = url.replace(".html", ".json")
        json_data = requests.get(json_url).json()
        name = json_data["name"]
        
        # Clean filename to avoid issues
        name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()

        progress_hook = ProgressHook(f"Downloading: {name[:30]}...")
        
        yt_opts = {
            'outtmpl': f'{path}{sep}{name}.%(ext)s',
            # Try different format options - start with best available
            'format': 'best[height<=720]/best',  # Fallback to best available
            'writesubtitles': False,
            'writeautomaticsub': False,
            'progress_hooks': [progress_hook],
        }
        
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])
            
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        # If the above fails, try listing formats to see what's available
        print("Available formats:")
        get_available_formats(url)


def download_single_episode(args):
    """Wrapper function for multiprocessing that handles a single episode"""
    card, path, episode_num, total_episodes = args
    try:
        name = card['name']
        # Clean filename
        name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        url = "https://www.raiplay.it" + card['weblink']
        
        # Create a simpler progress description for batch downloads
        desc = f"[{episode_num}/{total_episodes}] {name[:25]}..."
        progress_hook = ProgressHook(desc)
        
        yt_opts = {
            'outtmpl': f'{path}{sep}{name}.%(ext)s',
            'format': 'best[height<=720]/best',  # More flexible format selection
            'writesubtitles': False,
            'writeautomaticsub': False,
            'quiet': False,  # Set to True to reduce output
            'progress_hooks': [progress_hook],
        }
        
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])
            
        return f"✓ Successfully downloaded: {name}"
        
    except Exception as e:
        return f"✗ Error downloading {card.get('name', 'unknown')}: {str(e)}"


def batch_request(title_url, season_number, path, first_episode=0):
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
        
        # Use fewer processes to avoid overwhelming the server
        max_processes = min(4, len(download_args))
        
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
        
        successful = sum(1 for r in results if r.startswith("✓"))
        failed = len(results) - successful
        
        print(f"Total episodes: {len(results)}")
        print(f"✓ Successful: {successful}")
        print(f"✗ Failed: {failed}")
        
        if failed > 0:
            print("\nFailed downloads:")
            for result in results:
                if result.startswith("✗"):
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
    choice = 0
    while choice not in [1, 2, 3]:
        print("=== RaiPlay Downloader 2.0 (Fixed) ===")
        print("Choose an option:\n")
        choice = int(input("""
        [1]: One video
        [2]: All episodes of a serie
        [3]: Test single download (with format info)
        """))

    if choice == 1:
        url = input("Insert RaiPlay URL\n")
        path = input("Insert path to save the video\n")
        single_request(url, path)
    elif choice == 2:
        title_url = input("Insert RaiPlay URL of the serie\n")
        season_number = int(input("Insert season number\n")) - 1
        path = input("Insert path to save the videos\n")
        first_episode = int(input("Insert the first episode to download (0 for all)\n") or 0)
        batch_request(title_url, season_number, path, first_episode)
    else:
        test_single_download()


if __name__ == '__main__':
    main()
