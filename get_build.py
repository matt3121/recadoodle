import os
import sys
import time
import zipfile
from pathlib import Path

try:
    import requests
    from tqdm import tqdm
except ImportError:
    print("Missing packages. Run:")
    print("pip install requests tqdm")
    sys.exit(1)

URL = "https://archive.recagain.site/download/2023-04-18T06-58-58Z"

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "DepotDownloader"
ARCHIVE_FILE = BASE_DIR / "RecRoom-2023-04-18.zip"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print(r"""
══════════════════════════════════════════════════════════
               RECADOODLE BUILD DOWNLOADER              
                     liamcodeslol :)                                                                   
══════════════════════════════════════════════════════════
""")


def download():
    print("\nConnecting to download server")

    response = requests.get(
        URL,
        stream=True,
        timeout=30
    )

    response.raise_for_status()

    total = int(response.headers.get("content-length", 0))

    print("Starting Download...\n")

    start_time = time.time()

    with open(ARCHIVE_FILE, "wb") as file:
        with tqdm(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc="Rec Room",
            ncols=90,
            bar_format=(
                "{l_bar}{bar}| "
                "{percentage:3.0f}% "
                "{n_fmt}/{total_fmt} "
                "[{elapsed}<{remaining}, {rate_fmt}]"
            )
        ) as progress:

            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)
                    progress.update(len(chunk))

    elapsed = time.time() - start_time

    print(f"\nDownload finished in {elapsed:.1f} seconds.")


def extract():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    print("\nExtracting build...")
    print(f"Destination: {DOWNLOAD_DIR}\n")

    with zipfile.ZipFile(ARCHIVE_FILE, "r") as archive:
        members = archive.infolist()

        with tqdm(
            total=len(members),
            desc="Extracting",
            ncols=90,
            unit="files"
        ) as progress:

            for member in members:
                archive.extract(member, DOWNLOAD_DIR)
                progress.update(1)

    ARCHIVE_FILE.unlink(missing_ok=True)

    print("\nExtraction complete.")


def main():
    clear()
    banner()

    print("\nYou must own Rec Room or have it in your library on Steam to use the build.")
    answer = input("Do you own Rec Room on Steam? [Y/N]: ").strip().lower()

    if answer not in ("y", "yes"):
        print("\nidk how to bypass that uhh.")
        input("\nPress Enter to exit bye...")
        return

    print("\n ok.")

    try:
        download()
        extract()

    except requests.RequestException as error:
        print("\nthe download failed check ur internet")
        print(f"    {error}")
        input("\nPress Enter to exit bye...")
        return

    except zipfile.BadZipFile:
        print("\nerror with that zip yk")
        input("\nPress Enter to exit bye...")
        return

    except Exception as error:
        print("\n we dont EXACTLY know what happened it just did tho.")
        print(f"    {error}")
        input("\nPress Enter to exit bye...")
        return

    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║                       SUCCESS                            ║
║                                                          ║
║       Was that successful?                               ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")

    answer = input("[Y/N]: ").strip().lower()

    if answer in ("y", "yes"):
        print("\nPatch in progress - liamcodeslol :)")
    else:
        print("\noh well, uh. idk what to do then")

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()