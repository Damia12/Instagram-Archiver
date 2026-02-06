"""
Instagram Archiver Script - FIXED & OPTIMIZED
==============================================

Purpose:
- Download ALL publicly available content from an Instagram profile:
  - Profile picture (HD)
  - Active stories
  - Posts (including Reels)
- Highlights are intentionally disabled due to a known Instaloader bug (≥4.15)

Key features:
- REALISTIC human-like anti-ban behavior (12-40s delays + smart breaks)
- Persistent login session (avoids repeated logins)
- Per-profile log file, cumulative and human-readable
- Windows / Linux compatible
- Daily limits for safety
- 429 error recovery system
- Checkpoint system for resume capability

IMPORTANT:
- This script does NOT bypass privacy settings.
- It only downloads content accessible to the logged-in account.

CHANGES FROM ORIGINAL:
- ✅ Fixed micro-break bug (was never triggering)
- ✅ Increased delays to realistic human timing (12-40s)
- ✅ Added warm-up delay before profile access
- ✅ Removed suspicious Android user agent
- ✅ Increased profile cooldown (5-10 minutes)
- ✅ Added daily safety limits
- ✅ Added 429 error recovery
- ✅ Added checkpoint system
- ✅ Improved logging
- ✅ Content-aware delays (videos vs photos)
"""

import random
import time
import instaloader
import os
from pathlib import Path
import getpass
import datetime
import sys
import json
from instaloader.exceptions import (
    TwoFactorAuthRequiredException,
    BadCredentialsException,
    ConnectionException,
    QueryReturnedNotFoundException,
    LoginRequiredException,
)

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
# ANTI-BAN CONFIGURATION (REALISTIC HUMAN BEHAVIOR)
# ============================================================
# Based on actual human browsing patterns on Instagram

# Delays based on content type (seconds)
POST_DELAYS = {
    "photo": (12, 25),  # Simple photos: 12-25s (read caption, view photo)
    "video": (18, 35),  # Videos: 18-35s (watch video)
    "carousel": (20, 40),  # Carousels: 20-40s (swipe through multiple images)
}

# Micro-breaks configuration
MICRO_BREAK = {
    "min": 90,  # Minimum break: 90s (1.5 minutes)
    "max": 240,  # Maximum break: 240s (4 minutes)
    "frequency": (4, 7),  # Take break every 4-7 posts
}

# Cooldown between different profiles
PROFILE_COOLDOWN = {
    "min": 300,  # Minimum: 5 minutes
    "max": 600,  # Maximum: 10 minutes
}

# Daily safety limits (prevents permanent bans)
DAILY_LIMITS = {
    "max_profiles": 15,  # Maximum 15 profiles per day
    "max_downloads": 200,  # Maximum 200 posts per execution
}

# Rate limit recovery
RATE_LIMIT_WAIT = 3600  # Wait 1 hour after 429 error

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

# USER = "f.e.l.i.pesxi"
USER = "ginger_dam_o"

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
        print(f"❌ Profiles file not found: {file_path}")
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
# CHECKPOINT SYSTEM
# ============================================================
# Allows resuming downloads after interruptions


def save_checkpoint(username, last_processed_shortcode):
    """Save progress checkpoint"""
    checkpoint_file = BASE_FOLDER / username / ".checkpoint"
    with open(checkpoint_file, "w") as f:
        json.dump(
            {
                "last_shortcode": last_processed_shortcode,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            f,
        )


def load_checkpoint(username):
    """Load progress checkpoint if exists"""
    checkpoint_file = BASE_FOLDER / username / ".checkpoint"
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r") as f:
                return json.load(f)
        except:
            return None
    return None


def clear_checkpoint(username):
    """Clear checkpoint after successful completion"""
    checkpoint_file = BASE_FOLDER / username / ".checkpoint"
    if checkpoint_file.exists():
        checkpoint_file.unlink()


# ============================================================
# POST DOWNLOAD CHECK
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
# SESSION HEALTH CHECK
# ============================================================


def check_session_health():
    """Verifies that the session is still active"""
    try:
        # Attempt to get info of the logged-in user
        L.context.get_username_by_id(L.context.user_id)
        return True
    except:
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
            print(f"📂 Loading session from {INSTA_SESSION}...")
            L.load_session_from_file(USER, filename=str(INSTA_SESSION))
            print(f"✅ Logged in as {USER}")
            return
    except Exception as e:
        print(f"⚠️  Session load error: {e}. Performing fresh login.")

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
        print("💾 Session saved.")
    except Exception as e:
        print(f"⚠️  Warning: Could not save session: {e}")


# ============================================================
# RATE LIMIT HANDLER
# ============================================================


def handle_rate_limit_error(username, log):
    """
    Intelligent 429 error management.
    Instagram typically lifts the rate limit after 1-2 hours.
    """
    wait_time = RATE_LIMIT_WAIT

    print(f"\n⚠️  RATE LIMIT DETECTED for {username}")
    print(f"Instagram has temporarily blocked requests.")
    print(f"Waiting {wait_time // 60} minutes before resuming...\n")

    log.write(f"\nRATE LIMIT:\n")
    log.write(f"  Time: {datetime.datetime.now(datetime.timezone.utc)}\n")
    log.write(f"  Action: Pausing for {wait_time // 60} minutes\n\n")

    # Visual countdown
    for remaining in range(wait_time, 0, -60):
        mins = remaining // 60
        print(f"⏰ {mins} minutes remaining until retry...      ", end="\r")
        time.sleep(60)

    print("\n✅ Resuming operations...\n")


# ============================================================
# MAIN DOWNLOAD FUNCTION
# ============================================================
# Downloads all allowed content from a profile
# Generates a detailed log entry per execution


def download_profile_data(target_username, cutoff_days=None):
    print(f"\n{'=' * 50}")
    print(f"📥 PROCESSING: {target_username}")
    print(f"{'=' * 50}")

    # WARM-UP: Simulate human "browsing" before accessing profile
    warmup = random.uniform(8, 18)
    print(f"🔥 Warming up... {warmup:.1f}s")
    time.sleep(warmup)

    log = open_profile_log(target_username)
    start_time = datetime.datetime.now(datetime.timezone.utc)

    # Execution header
    log.write("\n" + "=" * 50 + "\n")
    log.write(f"PROFILE: {target_username}\n")
    log.write(f"DATE: {start_time}\n")
    log.write("=" * 50 + "\n\n")

    # --------------------------------------------------------
    # Load and validate profile
    # --------------------------------------------------------

    try:
        profile = instaloader.Profile.from_username(L.context, target_username)

        if profile.is_private:
            log.write("STATUS:\n  ⚠️  PROFILE IS PRIVATE\n")
            log.close()
            print(f"🔒 {target_username} is private. Skipping.")
            return

    except QueryReturnedNotFoundException:
        log.write("STATUS:\n  ❌ PROFILE NOT FOUND\n")
        log.close()
        print(f"❌ {target_username} does not exist. Skipping.")
        return

    except LoginRequiredException:
        log.write("STATUS:\n  ❌ LOGIN REQUIRED OR SESSION EXPIRED\n")
        log.close()
        print("❌ Login required or session expired.")
        sys.exit(1)

    except Exception as e:
        log.write(f"STATUS:\n  ❌ FAILED TO LOAD PROFILE: {e}\n")
        log.close()
        print(f"❌ Unexpected error loading {target_username}: {e}")
        return

    # --------------------------------------------------------
    # PROFILE PICTURE (HD)
    # --------------------------------------------------------
    log.write("PROFILE PICTURE:\n")
    try:
        L.download_profilepic(profile)
        log.write("  ✅ Downloaded (HD)\n\n")
        time.sleep(random.uniform(2, 5))  # Small delay after profile pic
    except Exception as e:
        log.write(f"  ❌ Error: {e}\n\n")

    # --------------------------------------------------------
    # STORIES (active only)
    # --------------------------------------------------------
    log.write("STORIES:\n")
    original_pattern = L.dirname_pattern
    try:
        L.dirname_pattern = str(BASE_FOLDER / target_username / "stories")
        L.download_stories(userids=[profile.userid])
        log.write("  ✅ Downloaded\n\n")
        time.sleep(random.uniform(3, 7))  # Small delay after stories
    except Exception as e:
        log.write(f"  ❌ Error: {e}\n\n")
    finally:
        L.dirname_pattern = original_pattern

    # --------------------------------------------------------
    # HIGHLIGHTS (DISABLED)
    # --------------------------------------------------------
    log.write("HIGHLIGHTS:\n")
    log.write("  ⚠️  Disabled (Instaloader bug ≥4.15)\n\n")

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
        log.write(f"  Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}\n\n")

    total = downloaded = skipped_existing = skipped_cutoff = videos = photos = 0

    # Checkpoint system
    checkpoint = load_checkpoint(target_username)
    skip_until_shortcode = checkpoint["last_shortcode"] if checkpoint else None
    if checkpoint:
        log.write(f"  ℹ️  Resuming from checkpoint: {skip_until_shortcode}\n\n")

    # Micro-break tracking (FIXED BUG)
    posts_downloaded_this_session = 0
    next_break_at = random.randint(*MICRO_BREAK["frequency"])

    try:
        posts = profile.get_posts()

        for post in posts:
            total += 1

            # Skip until we reach the checkpoint
            if skip_until_shortcode:
                if post.shortcode == skip_until_shortcode:
                    skip_until_shortcode = None
                    log.write(f"  ✅ Checkpoint reached, continuing from here\n")
                else:
                    continue

            # Stop when reaching cutoff date
            if cutoff_date and post.date_utc < cutoff_date:
                log.write(
                    f"  ℹ️  Reached cutoff date ({cutoff_date.strftime('%Y-%m-%d')})\n"
                )
                skipped_cutoff = total - downloaded - skipped_existing
                break

            # Skip already downloaded posts
            if post_already_downloaded(BASE_FOLDER, target_username, post):
                skipped_existing += 1
                continue

            # Safety limit
            if downloaded >= DAILY_LIMITS["max_downloads"]:
                log.write(
                    f"\n  ⚠️  Safety limit reached ({DAILY_LIMITS['max_downloads']} downloads)\n"
                )
                log.write(f"  Run the script again later to continue.\n")
                break

            try:
                L.download_post(post, target=target_username)
                downloaded += 1
                posts_downloaded_this_session += 1

                # Determine content type and set appropriate delay
                if post.is_video:
                    videos += 1
                    delay_range = POST_DELAYS["video"]
                    content_type = "video"
                elif post.mediacount > 1:
                    photos += 1
                    delay_range = POST_DELAYS["carousel"]
                    content_type = "carousel"
                else:
                    photos += 1
                    delay_range = POST_DELAYS["photo"]
                    content_type = "photo"

                # Save checkpoint after each successful download
                save_checkpoint(target_username, post.shortcode)

                # Intelligent delay based on content type
                delay = random.uniform(*delay_range)
                print(
                    f"   ⏸️  [{downloaded}/{DAILY_LIMITS['max_downloads']}] Waiting {delay:.1f}s ({content_type})..."
                )
                time.sleep(delay)

                # Micro-break (FIXED: now triggers correctly)
                if posts_downloaded_this_session >= next_break_at:
                    nap = random.randint(MICRO_BREAK["min"], MICRO_BREAK["max"])
                    print(f"   😴 Taking a break: {nap}s ({nap // 60}m {nap % 60}s)")
                    time.sleep(nap)

                    # Reset counter and generate new random interval
                    posts_downloaded_this_session = 0
                    next_break_at = random.randint(*MICRO_BREAK["frequency"])

            except ConnectionException as e:
                if "429" in str(e):
                    handle_rate_limit_error(target_username, log)
                    # Retry once after waiting
                    try:
                        L.download_post(post, target=target_username)
                        downloaded += 1
                        save_checkpoint(target_username, post.shortcode)
                    except:
                        log.write(f"  ❌ Failed after rate limit recovery\n")
                        break
                else:
                    print(f"   ⚠️  Connection issue, waiting 30s...")
                    log.write(f"  ⚠️  Connection error: {e}\n")
                    time.sleep(30)
            except Exception as e:
                log.write(f"  ⚠️  Post error: {e}\n")
                print(f"   ⚠️  Error: {e}")

    except ConnectionException as e:
        if "429" in str(e):
            handle_rate_limit_error(target_username, log)
        else:
            log.write(f"  ❌ Error iterating posts: {e}\n")
    except Exception as e:
        log.write(f"  ❌ Error iterating posts: {e}\n")

    # Posts summary
    log.write(f"\nSUMMARY:\n")
    log.write(f"  Total posts scanned: {total}\n")
    log.write(f"  Downloaded: {downloaded}\n")
    log.write(f"  Skipped (already downloaded): {skipped_existing}\n")
    log.write(f"  Skipped (cutoff date): {skipped_cutoff}\n")
    log.write(f"  Videos: {videos}\n")
    log.write(f"  Photos/Carousels: {photos}\n\n")

    # Clear checkpoint on successful completion
    if downloaded > 0 and skip_until_shortcode is None:
        clear_checkpoint(target_username)

    # Final status
    log.write("STATUS:\n  ✅ COMPLETED\n")
    log.write("=" * 50 + "\n")
    log.close()

    print(
        f"✅ Finished {target_username} - Downloaded: {downloaded}, Skipped: {skipped_existing}"
    )


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        smart_login()

        # NOTE: Removed custom user agent - using Instaloader's default
        # which is more reliable and less likely to trigger bans

        profiles = load_profiles_from_file("profiles.txt")

        print(f"\n{'=' * 50}")
        print(f"📋 Loaded {len(profiles)} profiles from profiles.txt")
        print(f"{'=' * 50}")
        print(f"\n⚙️  CURRENT SETTINGS:")
        print(
            f"  • Post delays: {POST_DELAYS['photo'][0]}-{POST_DELAYS['carousel'][1]}s"
        )
        print(
            f"  • Micro-breaks: {MICRO_BREAK['min']}-{MICRO_BREAK['max']}s every {MICRO_BREAK['frequency'][0]}-{MICRO_BREAK['frequency'][1]} posts"
        )
        print(
            f"  • Profile cooldown: {PROFILE_COOLDOWN['min'] // 60}-{PROFILE_COOLDOWN['max'] // 60} minutes"
        )
        print(
            f"  • Daily limits: {DAILY_LIMITS['max_profiles']} profiles, {DAILY_LIMITS['max_downloads']} posts"
        )
        print(f"\n{'=' * 50}\n")

        print("SELECT MODE:")
        print("1. Download SPECIFIC profile")
        print("2. Download ALL profiles (Bulk mode)")

        mode = input("\nSelect mode (1 or 2): ").strip()

        if mode == "2" or mode.lower() == "all":
            print(f"\n🚀 Starting BULK download mode...")
            print(
                f"⚠️  Processing up to {DAILY_LIMITS['max_profiles']} profiles with safety limits enabled\n"
            )

            profiles_processed = 0

            for i, user in enumerate(profiles):
                # Daily profile limit
                if profiles_processed >= DAILY_LIMITS["max_profiles"]:
                    print(
                        f"\n⚠️  Daily profile limit reached ({DAILY_LIMITS['max_profiles']} profiles)"
                    )
                    print("Resume tomorrow to continue safely.")
                    break

                # Check session health before each profile
                if not check_session_health():
                    print("⚠️  Session expired, re-logging...")
                    smart_login()

                download_profile_data(user, cutoff_days=730)
                profiles_processed += 1

                # Cooldown between profiles (except for the last one)
                if (
                    i < len(profiles) - 1
                    and profiles_processed < DAILY_LIMITS["max_profiles"]
                ):
                    wait = random.randint(
                        PROFILE_COOLDOWN["min"], PROFILE_COOLDOWN["max"]
                    )
                    minutes = wait // 60
                    seconds = wait % 60
                    print(
                        f"\n💤 Cooling down: {minutes}m {seconds}s until next profile..."
                    )

                    # Visual countdown
                    for remaining in range(wait, 0, -30):
                        mins = remaining // 60
                        secs = remaining % 60
                        print(
                            f"   ⏰ {mins:02d}:{secs:02d} remaining...      ", end="\r"
                        )
                        time.sleep(30)
                    print()  # New line after countdown

            print(
                f"\n✅ Bulk download completed! Processed {profiles_processed} profiles."
            )

        else:
            print("\nAVAILABLE PROFILES:")
            for idx, name in enumerate(profiles, 1):
                print(f"  {idx}. {name}")

            choice = int(input("\nEnter profile number: ").strip())
            if 1 <= choice <= len(profiles):
                download_profile_data(profiles[choice - 1])
            else:
                print("❌ Invalid selection")

    except KeyboardInterrupt:
        print("\n\n🛑 Script stopped by user.")
        print("💡 Use checkpoint system to resume later!")
    except Exception as e:
        print(f"\n❌ Fatal Error: {e}")
        import traceback

        traceback.print_exc()
