"""
Instagram Archiver Script
=========================

Purpose:
- Download ALL publicly available content from an Instagram profile:
  - Profile picture (HD)
  - Active stories
  - Posts (including Reels)
- Highlights are intentionally disabled due to a known Instaloader bug (≥4.15)

Key features:
- Human-like anti-ban behavior (random delays + micro-breaks)
- Persistent login session (avoids repeated logins)
- Per-profile log file, cumulative and human-readable
- Windows / Linux compatible

IMPORTANT:
- This script does NOT bypass privacy settings.
- It only downloads content accessible to the logged-in account.
"""

import random
import time
import instaloader
import os
from pathlib import Path
import getpass
import datetime
import sys
from instaloader.exceptions import (
    TwoFactorAuthRequiredException,
    BadCredentialsException,
    ConnectionException,
    QueryReturnedNotFoundException,
    LoginRequiredException,
)

# ============================================================
# RATE LIMIT GLOBAL FLAG (FASE 2)
# ============================================================

RATE_LIMIT_DETECTED = False

# ============================================================
# BASE DIRECTORY
# ============================================================
# Root folder where all downloaded Instagram content is stored.
# Automatically adapts depending on the operating system.

BASE_FOLDER = (
    Path("F:/Instagram")
    if os.name == "nt"
    else Path("/home/felipe/Downloads/Instagram")
)
BASE_FOLDER.mkdir(parents=True, exist_ok=True)

# ============================================================
# INSTALOADER CONFIGURATION
# ============================================================
# Features that increase ban risk are intentionally disabled.

L = instaloader.Instaloader(
    dirname_pattern=str(BASE_FOLDER / "{target}"),  # Base directory per profile
    save_metadata=False,  # No JSON metadata
    download_geotags=False,
    download_comments=False,
    post_metadata_txt_pattern="{caption}",  # Caption only
    max_connection_attempts=3,
)

# ============================================================
# SESSION CONFIGURATION
# ============================================================
# Instagram account used for login.
# The session is reused to reduce login frequency.

USER = "f.e.l.i.pesxi"

SCRIPT_DIR = Path(__file__).resolve().parent

SESSIONS_DIR = SCRIPT_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

INSTA_SESSION = SESSIONS_DIR / f"session-{USER}"

# ============================================================
# PROFILE LOADER
# ============================================================


def load_profiles_from_file(file_path="profiles.txt"):
    """
    Loads Instagram profile usernames from a text file.
    """
    profiles = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                profiles.append(line)
    except FileNotFoundError:
        print(f"Profiles file not found: {file_path}")
        sys.exit(1)

    return profiles


# ============================================================
# LOGGING UTILITY
# ============================================================
# Each profile gets its own log.txt file.
# Logs are appended, never overwritten.


def open_profile_log(username):
    """
    Opens (or creates) the profile log file.
    The file is opened in append mode.
    """
    log_path = BASE_FOLDER / username / "log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return open(log_path, "a", encoding="utf-8")


# ============================================================
# RATE LIMIT DETECTOR
# ============================================================


def is_rate_limit_error(error: Exception) -> bool:
    """
    Detects Instagram rate-limit / temporary block errors
    by inspecting the error message.
    """
    error_text = str(error).lower()

    indicators = [
        "please wait a few minutes",
        "rate limit",
        "temporarily blocked",
        "server error",
        "401 unauthorized",
        "too many requests",
    ]

    return any(indicator in error_text for indicator in indicators)


# ============================================================
# FASE 1
# ============================================================


def post_already_downloaded(base_folder, username, post):
    """
    Checks if a post was already downloaded by inspecting the filesystem.
    Works for photos, videos and carousels.
    """
    post_dir = base_folder / username / "posts"

    if not post_dir.exists():
        return False

    shortcode = post.shortcode

    # Any file containing the shortcode means it was downloaded
    for file in post_dir.iterdir():
        if shortcode in file.name:
            return True

    return False


# ============================================================
# SMART LOGIN
# ============================================================
# - Loads an existing session if available
# - Otherwise performs login and handles 2FA
# - Saves the session for future executions


def smart_login():
    try:
        if INSTA_SESSION.exists():
            print(f"Loading session from {INSTA_SESSION}...")
            L.load_session_from_file(USER, filename=str(INSTA_SESSION))
            print(f"Logged in as {USER}")
            return
    except Exception as e:
        print(f"Session load error: {e}. Performing fresh login.")

    password = os.environ.get("INSTA_PASSWORD") or getpass.getpass(
        f"Enter Password for {USER}: "
    )

    try:
        L.login(USER, password)
    except TwoFactorAuthRequiredException:
        code = input("[2FA] Enter the 6-digit code: ").strip()
        L.two_factor_login(code)
    except BadCredentialsException:
        print("❌ Wrong password.")
        sys.exit(1)
    except ConnectionException as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    print("✅ Login successful.")
    try:
        L.save_session_to_file(filename=str(INSTA_SESSION))
        print("Session saved.")
    except Exception as e:
        print(f"Warning: Could not save session: {e}")


# ============================================================
# MAIN DOWNLOAD FUNCTION
# ============================================================
# Downloads all allowed content from a profile
# Generates a detailed log entry per execution


def download_profile_data(target_username, cutoff_days=None):
    global RATE_LIMIT_DETECTED
    print(f"\n{'=' * 40}")
    print(f"📥 PROCESSING: {target_username}")
    print(f"{'=' * 40}")

    log = open_profile_log(target_username)
    start_time = datetime.datetime.now(datetime.timezone.utc)

    # Execution header
    log.write("\n" + "=" * 40 + "\n")
    log.write(f"PROFILE: {target_username}\n")
    log.write(f"DATE: {start_time}\n")
    log.write("=" * 40 + "\n\n")

    # --------------------------------------------------------
    # Load profile
    # --------------------------------------------------------

    # try:
    #     profile = instaloader.Profile.from_username(L.context, target_username)
    # except Exception as e:
    #     log.write(f"STATUS:\n  ✖ FAILED TO LOAD PROFILE: {e}\n")
    #     log.close()
    #     return

    # Load and validate profile
    try:
        profile = instaloader.Profile.from_username(L.context, target_username)

        if profile.is_private:
            log.write("STATUS:\n  PROFILE PRIVATE\n")
            log.close()
            print(f"{target_username} is private. Skipping.")
            return

    except QueryReturnedNotFoundException:
        log.write("STATUS:\n  PROFILE NOT FOUND\n")
        log.close()
        print(f"{target_username} does not exist. Skipping.")
        return

    except LoginRequiredException:
        log.write("STATUS:\n  LOGIN REQUIRED OR SESSION EXPIRED\n")
        log.close()
        print("Login required or session expired.")
        sys.exit(1)

    # except Exception as e:
    #     log.write(f"STATUS:\n  FAILED TO LOAD PROFILE: {e}\n")
    #     log.close()
    #     print(f"Unexpected error loading {target_username}: {e}")
    #     return
    except Exception as e:
        if is_rate_limit_error(e):
            log.write("\nRATE LIMIT DETECTED WHILE LOADING PROFILE:\n")
            log.write(f"  {e}\n")
            log.write("  ACTION: SCRIPT STOPPED\n")
            log.close()
            sys.exit(0)

        log.write(f"STATUS:\n  FAILED TO LOAD PROFILE: {e}\n")
        log.close()
        return

    # --------------------------------------------------------
    # PROFILE PICTURE (HD)
    # --------------------------------------------------------
    log.write("PROFILE PICTURE:\n")
    try:
        L.download_profilepic(profile)
        log.write("  ✔ Downloaded (HD)\n\n")
    except Exception as e:
        log.write(f"  ✖ Error: {e}\n\n")

    # --------------------------------------------------------
    # STORIES (active only)
    # --------------------------------------------------------
    log.write("STORIES:\n")
    original_pattern = L.dirname_pattern

    try:
        L.dirname_pattern = str(BASE_FOLDER / target_username / "stories")
        L.download_stories(userids=[profile.userid])
        log.write("  Downloaded\n\n")

    except Exception as e:
        if is_rate_limit_error(e):
            log.write("\nRATE LIMIT DETECTED DURING STORIES:\n")
            log.write(f"  {e}\n")
            log.write("  ACTION: SCRIPT STOPPED\n")
            log.close()
            sys.exit(0)

        log.write(f"  Error: {e}\n\n")

    finally:
        L.dirname_pattern = original_pattern

    # --------------------------------------------------------
    # HIGHLIGHTS (DISABLED)
    # --------------------------------------------------------
    log.write("HIGHLIGHTS:\n")
    log.write("  ✖ Disabled (Instaloader bug ≥4.15)\n\n")

    # --------------------------------------------------------
    # POSTS / REELS
    # --------------------------------------------------------
    log.write("POSTS:\n")
    L.dirname_pattern = str(BASE_FOLDER / target_username / "posts")

    cutoff_date = None
    if cutoff_days:
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=cutoff_days
        )

    total = downloaded = skipped = skipped_existing = videos = photos = 0

    try:
        posts = profile.get_posts()
        # for i, post in enumerate(posts, 1):
        #     total += 1
        skipped_existing = 0
        for i, post in enumerate(posts, 1):
            total += 1

            # Stop when reaching cutoff date
            if cutoff_date and post.date_utc < cutoff_date:
                skipped += 1
                break

            # Phase 1: Skip already downloaded posts
            if post_already_downloaded(BASE_FOLDER, target_username, post):
                skipped_existing += 1
                continue

            # # Stop when reaching cutoff date
            # if cutoff_date and post.date_utc < cutoff_date:
            #     skipped += 1
            #     break

            try:
                L.download_post(post, target=target_username)
                downloaded += 1

                if post.is_video:
                    videos += 1
                else:
                    photos += 1

                # Short human-like pause
                time.sleep(random.uniform(3.5, 7.5))

                # Human micro-break every few posts
                if i > 10 and i % random.randint(7, 15) == 0:
                    nap = random.randint(20, 60)
                    print(f"   😴 Micro-break {nap}s")
                    time.sleep(nap)

            except ConnectionException:
                time.sleep(15)
            # except Exception as e:
            #     log.write(f"  ⚠️ Post error: {e}\n")

            except Exception as e:
                if is_rate_limit_error(e):
                    RATE_LIMIT_DETECTED = True

                    log.write("\nRATE LIMIT DETECTED:\n")
                    log.write(f"  {e}\n")
                    log.write("  ACTION: SCRIPT STOPPED TO PREVENT BAN\n")
                    log.write("=" * 40 + "\n")

                    print("\nRATE LIMIT DETECTED — STOPPING SCRIPT")
                    log.close()
                    sys.exit(0)

                log.write(f"  Post error: {e}\n")

    except Exception as e:
        log.write(f"  ✖ Error iterating posts: {e}\n")

    # Posts summary
    log.write(f"\n  Total scanned: {total}\n")
    log.write(f"  Downloaded: {downloaded}\n")
    log.write(f"  Skipped (already downloaded): {skipped_existing}\n")
    log.write(f"  Skipped (cutoff): {skipped}\n")
    log.write(f"  Videos: {videos}\n")
    log.write(f"  Photos/Carousels: {photos}\n\n")

    # Final status
    log.write("STATUS:\n  ✔ COMPLETED\n")
    log.write("=" * 40 + "\n")
    log.close()

    print(f"✅ Finished {target_username}")


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        smart_login()
        L.context.user_agent = "Instagram 219.0.0.12.117 Android"

        profiles = load_profiles_from_file("profiles.txt")

        # profiles = [
        #     "its.melus",
        #     "pandoralovex",
        #     "_vaniasse_",
        #     "paudipai",
        #     "itsmidna",
        #     "vickypalami",
        #     "fkcristina_",
        #     "vaniasse",
        #     "maryblog32",
        #     "emetsukii",
        #     "michtaquito",
        #     "_nataliamx",
        #     "abriguerra",
        #     "renrize",
        #     "ansichann",
        #     "soyevapartis",
        #     "meowrian_exe",
        #     "emikukiss",
        #     "iloveantito",
        #     "mictiatv",
        #     "rakkunvt",
        #     "vaniassemt",
        #     "soyamericaa",
        #     "santosmihg",
        #     "deargia",
        #     "abicita_.a",
        #     "atinycherry",
        #     "dannespino",
        #     "vekitk",
        #     "asleryz_",
        #     "soyivycol",
        #     "sin6n_",
        #     "rociodta",
        #     "nicsofiadiaz",
        #     "kalobetaa",
        #     "jmenuwu",
        #     "akanenonito",
        #     "airanmuwu",
        #     "ahgadi_qu",
        #     "verorebuwu",
        #     "thexgurl_",
        #     "xnephtunie",
        #     "yoyolen1",
        #     "akn_k0",
        #     "keniajosee",
        #     "keniajoc",
        #     "sweet.cosplay_",
        #     "vit4celestine",
        #     "conejito.gordo",
        #     "abycanz",
        #     "morritasq",
        # ]

        print(f"\nLoaded {len(profiles)} profiles.")
        print("1. Download SPECIFIC profile")
        print("2. Download ALL profiles (Bulk)")

        mode = input("Select mode (1 or 2): ").strip()

        if mode == "2" or mode.lower() == "all":
            # for i, user in enumerate(profiles):
            #     download_profile_data(user, cutoff_days=730)
            for i, user in enumerate(profiles):
                if RATE_LIMIT_DETECTED:
                    print("\nRate limit previously detected. Exiting.")
                    break

                download_profile_data(user, cutoff_days=730)

                if i < len(profiles) - 1:
                    wait = random.randint(90, 180)
                    print(f"\n💤 Cooling down for {wait} seconds...")
                    time.sleep(wait)
        else:
            for idx, name in enumerate(profiles, 1):
                print(f"{idx}. {name}")

            choice = int(input("\nEnter number: ").strip())
            download_profile_data(profiles[choice - 1])

    except KeyboardInterrupt:
        print("\n\n🛑 Script stopped by user.")
    except Exception as e:
        print(f"\n❌ Fatal Error: {e}")
