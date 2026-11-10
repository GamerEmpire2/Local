from asyncio import subprocess
import argparse
import traceback
import tkinter as tk

from pypresence import Presence
from pypresence.types import ActivityType, StatusDisplayType
from ytmusicapi import YTMusic
from time import sleep, time
import os, sys, threading, queue, re

try:
    from pynput import keyboard
except Exception:
    keyboard = None

# Initialize YTMusic with browser.json
browser_file = 'browser.json'
if os.path.exists(browser_file):
    try:
        yt = YTMusic(browser_file)
        print(f"✓ YTMusic initialized with {browser_file}")
    except Exception as e:
        print(f"✗ Failed to initialize YTMusic: {e}")
        sys.exit(1)
else:
    print(f"✗ {browser_file} not found")
    sys.exit(1)

# Load bot ID from bot_id.txt
bot_id_file = 'bot_id.txt'
if os.path.exists(bot_id_file):
    with open(bot_id_file, 'r') as f:
        RPC_Key = f.read().strip()
    print(f"✓ Bot ID loaded from {bot_id_file}")
else:
    print(f"✗ {bot_id_file} not found")
    sys.exit(1)

Large_Image_Key = os.getenv("DISCORD_LARGE_IMAGE_KEY", "embedded_cover")

# Discord RPC helpers
RPC = None
last_history_error = None

def get_history():
    global last_history_error
    try:
        history = yt.get_history()
    except Exception as e:
        error = (type(e).__name__, str(e))
        if error != last_history_error:
            print(f"Error retrieving YouTube Music history ({type(e).__name__}): {e!r}")
            traceback.print_exc()
            print("If this is an authentication error, refresh browser.json using a signed-in YouTube Music session.")
        last_history_error = error
        return None

    if last_history_error is not None:
        print("YouTube Music history access restored")
        last_history_error = None
    return history

def close_rpc():
    global RPC
    if not RPC:
        return
    try:
        RPC.close()
        print("✓ RPC closed")
    except Exception as e:
        print(f"✗ Failed to close RPC: {e}")
        sleep(5)
        try:
            RPC.close()
            print("✓ RPC closed on retry")
        except Exception as e2:
            print(f"✗ Second RPC close attempt failed: {e2}")
    finally:
        RPC = None


def establish_rpc():
    global RPC
    try:
        RPC = Presence(RPC_Key)
        RPC.connect()
        print("✓ Discord RPC connected")
    except Exception as e:
        print(f"✗ Failed to connect Discord RPC: {e}")
        RPC = None
    return RPC


def recover_rpc():
    close_rpc()
    print("⏳ Waiting 5 seconds before retrying Discord RPC connection")
    sleep(5)
    return establish_rpc()

RPC = establish_rpc()

# State tracking
last_track_id = None
song_start_time = None
last_update_time = 0
duration_sec = 0
checks_without_change = 0
is_stuck = False
MAX_CHECKS_STUCK = 6

# Podcasts/artists to shorten titles for
SHORTEN_TITLE_FOR = [
    "Sinister",
    "another_podcast",
]

def is_podcast_artist(artist_name):
    if not artist_name:
        return False
    return any(podcast.lower() in artist_name.lower() for podcast in SHORTEN_TITLE_FOR)

def check_song_changed():
    global last_track_id
    history = get_history()
    if history:
        current_vid = history[0].get('videoId') or history[0].get('video_id')
        return current_vid != last_track_id
    return False

def is_song_exceeded():
    if song_start_time and duration_sec > 0:
        elapsed = int(time()) - song_start_time
        return elapsed > duration_sec
    return False

def update_discord(force_update=False, paused_forced=False, force_restart=False, force_previous=False):
    global last_track_id, song_start_time, last_update_time, duration_sec, is_stuck
    history = get_history()
    if not history:
        return
    if RPC is None:
        if not establish_rpc():
            return
    try:
        track = history[0]
        title = track.get('title', 'Unknown')
        artist = ''
        vid = track.get('videoId') or track.get('video_id')
        image_url = track.get('thumbnails', [{}])[-1].get('url', 'ytmusic_logo')

        # Update last track id and start time
        if vid != last_track_id:
            last_track_id = vid
            song_start_time = int(time())
        elif force_restart:
            # User pressed previous after 5 seconds, restart current track in Discord.
            song_start_time = int(time())

        if force_previous:
            # Force re-read the track change from history on the next update.
            last_track_id = None

        # Parse duration
        duration_sec = 0
        if 'duration' in track and track['duration']:
            try:
                if isinstance(track['duration'], int):
                    duration_sec = track['duration']
                elif isinstance(track['duration'], str):
                    parts = track['duration'].split(':')
                    if len(parts) == 2:
                        duration_sec = int(parts[0]) * 60 + int(parts[1])
            except Exception:
                duration_sec = 0

        if duration_sec > 10800:
            duration_sec = 10800

        # Build artist string
        if 'artists' in track and track['artists']:
            artists_list = []
            for artist_info in track['artists']:
                if isinstance(artist_info, dict) and 'name' in artist_info:
                    name = artist_info['name']
                elif isinstance(artist_info, str):
                    name = artist_info
                else:
                    continue
                if not re.match(r'^\d{1,2}/\d{1,2}/\d{4}', name) and not re.match(r'^\d{4}', name):
                    artists_list.append(name)
            if artists_list:
                artist = ', '.join(artists_list)
            else:
                a = track.get('artists', [{}])[0]
                artist = a.get('name') if isinstance(a, dict) else str(a)

        display_title = title
        if is_podcast_artist(artist):
            display_title = title[:50] + '...' if len(title) > 50 else title

        buttons = []
        if vid:
            yt_music_url = f"https://music.youtube.com/watch?v={vid}"
            buttons.append({"label": "Listen on YouTube Music", "url": yt_music_url})
            buttons.append({"label": "Open Github", "url": "https://github.com/Tony68851122/YTMusic-To-Discord"})

        kwargs = {
            'status_display_type': StatusDisplayType.DETAILS,
            'activity_type': ActivityType.LISTENING,
            'details': f"Listening to {display_title[:127]}",
            'state': f"by {artist[:127]}",
            'large_image': Large_Image_Key,
            'small_image': image_url,
            'buttons': buttons if buttons else None
        }

        if paused_forced or is_stuck:
            kwargs['details'] = f'{display_title[:127]} - Paused'
            kwargs['state'] = f"{artist[:127]}"
        else:
            if duration_sec > 0 and song_start_time:
                end_time = song_start_time + duration_sec
                kwargs['start'] = song_start_time
                kwargs['end'] = end_time
                elapsed = int(time()) - song_start_time
                print(f"Duration: {duration_sec}s | Elapsed: {elapsed}s | Time bar: {song_start_time} → {end_time}")

        RPC.update(**kwargs)
        print(f"Updated Discord: {title} - {artist}")
        last_update_time = int(time())
    except Exception as e:
        print(f"Error updating Discord ({type(e).__name__}): {e!r}")
        traceback.print_exc()
        if recover_rpc():
            try:
                RPC.update(**kwargs)
                print(f"Updated Discord after reconnect: {title} - {artist}")
                last_update_time = int(time())
            except Exception as err2:
                print(f"Retry after reconnect failed ({type(err2).__name__}): {err2!r}")
                traceback.print_exc()
    

# Media key listener using a queue
media_q = queue.Queue()
def _on_press(key):
    try:
        if keyboard and key in (keyboard.Key.media_play_pause, keyboard.Key.media_next, keyboard.Key.media_previous):
            media_q.put(key)
            print(f"Media key pressed: {key}")
    except Exception:
        pass

listener = None
if keyboard:
    listener = keyboard.Listener(on_press=_on_press)
    listener.daemon = True
    listener.start()
else:
    print("pynput.keyboard not available; media keys disabled")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Update Discord Rich Presence from YouTube Music.")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="Start with repeat sync enabled (YouTube Music repeat must also be enabled).",
    )
    args = parser.parse_args()

    repeat_window = tk.Tk()
    repeat_window.title("Discord Repeat Sync")
    repeat_window.resizable(False, False)
    repeat_enabled = tk.BooleanVar(value=False)

    def set_repeat_enabled(enabled):
        repeat_enabled.set(enabled)

    tk.Checkbutton(
        repeat_window,
        text="Track is repeating",
        variable=repeat_enabled,
        command=lambda: set_repeat_enabled(repeat_enabled.get()),
    ).pack(padx=12, pady=(10, 4), anchor='w')
    tk.Label(
        repeat_window,
        text="Also enable repeat in YouTube Music.\nThis only syncs Discord's display.",
        justify='left',
    ).pack(padx=12, pady=(0, 10), anchor='w')
    ui_running = [True]
    set_repeat_enabled(args.repeat)

    def close_repeat_ui():
        ui_running[0] = False
        repeat_window.destroy()

    repeat_window.protocol("WM_DELETE_WINDOW", close_repeat_ui)

    # Initial update
    update_discord()

    try:
        while ui_running[0]:
            # Keep the small toggle window responsive while retaining the
            # existing two-second polling interval for playback state.
            for _ in range(20):
                repeat_window.update()
                sleep(0.1)
                if not ui_running[0]:
                    break
            if not ui_running[0]:
                break

            # Handle media key events
            try:
                while True:
                    k = media_q.get_nowait()
                    if keyboard and k == keyboard.Key.media_play_pause:
                        print("Media Play/Pause - forcing paused update")
                        update_discord(paused_forced=True)
                    elif keyboard and k == keyboard.Key.media_next:
                        print("Media Next - forcing update")
                        update_discord(force_update=True)
                    elif keyboard and k == keyboard.Key.media_previous:
                        print("Media Previous pressed")
                        elapsed = int(time()) - (song_start_time or int(time()))
                        if duration_sec > 0 and elapsed > 5:
                            print("Restarting current song in Discord")
                            update_discord(force_restart=True)
                        else:
                            print("Going to previous song in Discord")
                            update_discord(force_previous=True)
                    else:
                        print(f"Unhandled media key: {k}")
            except Exception:
                # queue empty
                pass

            # Check if song changed
            if check_song_changed():
                os.system('cls' if os.name == 'nt' else 'clear')
                print("🎵 Song changed detected!")
                checks_without_change = 0
                is_stuck = False
                update_discord()
            else:
                if is_song_exceeded():
                    if repeat_enabled.get():
                        print("🔁 Repeating track - restarting Discord progress timer")
                        checks_without_change = 0
                        is_stuck = False
                        update_discord(force_restart=True)
                    else:
                        if checks_without_change < 20:
                            checks_without_change += 1
                            print(f"⏱️ Past song duration - {checks_without_change}/{MAX_CHECKS_STUCK} checks")
                        else:
                            checks_without_change = 20
                            print("⏱️ Past song duration - waiting for change...")

                    if not repeat_enabled.get() and checks_without_change >= MAX_CHECKS_STUCK and not is_stuck:
                        is_stuck = True
                        os.system('cls' if os.name == 'nt' else 'clear')
                        print("⏸️ Song appears paused!")
                        update_discord(paused_forced=True)
                else:
                    checks_without_change = 0
                    is_stuck = False

            # Full update fallback every 15s
            if int(time()) - last_update_time >= 15:
                last_update_time = int(time())
                os.system('cls' if os.name == 'nt' else 'clear')
                update_discord()

            if int(time()) - last_update_time >= 1800:
                last_update_time = int(time())
                os.system('cls' if os.name == 'nt' else 'clear')
                print("⏱️ 30 minutes passed - forcing restart")
                subprocess.Popen([sys.executable, "Restart.py"])
                sys.exit(0)
        if listener:
            listener.stop()
        close_rpc()
    except KeyboardInterrupt:
        print("\n✓ Stopping Discord RPC...")
        if listener:
            try:
                listener.stop()
            except Exception:
                pass
        close_rpc()
    except Exception as e:
        print(f"Error: {e}")
        if RPC:
            try:
                RPC.close()
            except Exception:
                pass