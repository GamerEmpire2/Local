"""Local-only YouTube Music Display"""
from __future__ import annotations
import os
import json
import time
import threading
import tkinter as tk
from tkinter import font, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
from ytmusicapi import YTMusic, OAuthCredentials
import ytmusicapi
import shutil
from pypresence import Presence
import ctypes
from tkinter import messagebox

ctypes.windll.kernel32.SetConsoleTitleW("YouTube Music Display - Local Console")

# Use same config dir as main app for convenience
LOCAL_APPDATA = os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
CONFIG_DIR = os.path.join(LOCAL_APPDATA, 'YouTubeMusicDisplay')
os.makedirs(CONFIG_DIR, exist_ok=True)

# Display settings (minimal)
WINDOW_WIDTH = 550
WINDOW_HEIGHT = 250
WINDOW_X = 100
WINDOW_Y = 100
WINDOW_OPACITY = 0.95
WINDOW_ALWAYS_ON_TOP = True
WINDOW_SHOW_DECORATIONS = False

# Update interval (seconds)
UPDATE_INTERVAL = 1.0 

def load_env_file():
    root = os.path.dirname(__file__)
    env = {}
    
    # Check for env.env first, then fallback to env.txt
    possible_files = ['env.env', 'env.txt']
    env_path = None
    
    for fname in possible_files:
        p = os.path.join(root, fname)
        if os.path.exists(p):
            env_path = p
            break
            
    if env_path:
        try:
            with open(env_path, 'r', encoding='utf-8') as ef:
                for line in ef:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        env[k.strip()] = v.strip()
        except Exception:
            pass

    # overlay real environment vars if present
    for key in ('Client_ID', 'Client_Secret', 'DISCORD_CLIENT_ID', 'DISCORD_LARGE_IMAGE_KEY'):
        val = os.getenv(key)
        if val:
            env[key] = val
    return env

ENV_VALUES = load_env_file()

DISCORD_CLIENT_ID = ENV_VALUES.get('DISCORD_CLIENT_ID')
DISCORD_LARGE_IMAGE_KEY = ENV_VALUES.get('DISCORD_LARGE_IMAGE_KEY')

def find_auth_file(name):
    p_cwd = os.path.join(os.getcwd(), name)
    if os.path.exists(p_cwd): return p_cwd
    p_script = os.path.join(os.path.dirname(__file__), name)
    if os.path.exists(p_script): return p_script
    p_config = os.path.join(CONFIG_DIR, name)
    if os.path.exists(p_config): return p_config
    return None

def find_local_now_playing():
    cwd = os.path.join(os.getcwd(), 'local_now_playing.json')
    cfg = os.path.join(CONFIG_DIR, 'local_now_playing.json')
    if os.path.exists(cwd): return cwd
    if os.path.exists(cfg): return cfg
    return None

class LocalMusicOverlay:
    def __init__(self, root):
        self.root = root
        self.root.title('YouTube Music Display (Local)')
        self.root.attributes('-topmost', WINDOW_ALWAYS_ON_TOP)
        self.root.attributes('-alpha', WINDOW_OPACITY)
        self.root.geometry(f'{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{WINDOW_X}+{WINDOW_Y}')
        root.iconbitmap(default='.\\icon.ico')
        if not WINDOW_SHOW_DECORATIONS:
            try:
                self.root.attributes('-toolwindow', True)
            except Exception:
                pass

        self.root.configure(bg='#1a1a1a')

        self.image_cache = {}
        self.now_playing = None
        self.yt = None
        
        # --- TIMING VARIABLES FOR SIMULATION ---
        self.last_track_title = ""
        self.simulated_progress = 0
        self.last_update_time = time.time()
        
        # New variable to prevent Discord spamming
        self.last_sent_discord_track = None
        # ---------------------------------------

        self.discord_client = None

        # 1. Initialize YTMusic
        self.init_ytmusic()

        # 2. Initialize Discord Rich Presence
        self.init_discord()

        self.create_ui()

        # Start background thread
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def on_closing():
        if messagebox.askokcancel("Quit", "Do you want to close the YTMusic Display?"):
            # Put any cleanup code here (like disconnecting Discord)
            root.destroy()

            # This tells the window to call 'on_closing' when the X is clicked
        # root.protocol("WM_DELETE_WINDOW", on_closing)

    def init_discord(self):
        """Initialize Discord RPC separately from YTMusic logic."""
        try:
            if DISCORD_CLIENT_ID:
                self.discord_client = Presence(DISCORD_CLIENT_ID)
                self.discord_client.connect()
                print(f"✓ Discord Rich Presence connected (ID: {DISCORD_CLIENT_ID})")
            else:
                print("ℹ Discord Rich Presence not configured (DISCORD_CLIENT_ID missing in env file)")
        except Exception as e:
            print(f"Discord connection warning: {e}")
            self.discord_client = None

    def init_ytmusic(self):
        """Attempt to initialize YTMusic using local auth files and env credentials."""
        try:
            oauth_file = find_auth_file('oauth.json')
            browser_file = find_auth_file('browser.json')
            authjson_file = find_auth_file('auth.json')

            if oauth_file:
                client_id = ENV_VALUES.get('Client_ID')
                client_secret = ENV_VALUES.get('Client_Secret')
                if client_id and client_secret:
                    try:
                        creds = OAuthCredentials(client_id=client_id, client_secret=client_secret)
                        print(f"creds: {creds}")
                        self.yt = YTMusic(oauth_file, oauth_credentials=creds)
                        print(f"✓ Initialized YTMusic using {oauth_file} with OAuth credentials")
                        return
                    except Exception:
                        self.yt = None

            if browser_file:
                try:
                    self.yt = YTMusic(browser_file)
                    print(f"✓ Initialized YTMusic using {browser_file}")
                    return
                except Exception:
                    self.yt = None

            if authjson_file:
                try:
                    self.yt = YTMusic(authjson_file)
                    print(f"✓ Initialized YTMusic using {authjson_file}")
                    return
                except Exception:
                    self.yt = None
        except Exception as e:
            print(f"YTMusic init error: {e}")
            self.yt = None

    def update_discord_presence(self, music_info):
        """Update Discord Rich Presence with current song info (Milliseconds)"""
        client = getattr(self, 'discord_client', None)
        if not client:
            return

        try:
            title = music_info.get('title', 'Unknown')
            artist = music_info.get('artist', 'Unknown Artist')
            
            # Prevent updating Discord every second (avoids flickering)
            if title == self.last_sent_discord_track:
                return

            self.last_sent_discord_track = title

            # Get duration and progress in seconds (as floats or ints)
            duration_sec = float(music_info.get('duration', 0))
            progress_sec = float(music_info.get('progress', 0))
            
            # --- BUILD DISCORD PAYLOAD ---
            kwargs = {
                'details': title[:127],
                'state': f"by {artist}"[:127],
                'large_text': "YouTube Music",
            }

            if DISCORD_LARGE_IMAGE_KEY:
                kwargs['large_image'] = DISCORD_LARGE_IMAGE_KEY

            # --- TIME BAR LOGIC (MILLISECONDS) ---
            # if duration_sec > 0:
            #     # Current time in seconds
            #     now = time.time()
                
            #     # 1. Calculate Start Time in Milliseconds
            #     # (Current Time - Progress) * 1000
            #     start_timestamp_ms = int(now * 1000)
                
            #     # 2. Calculate End Time in Milliseconds
            #     # Start + (Duration * 1000)
            #     end_timestamp_ms = int(start_timestamp_ms + (duration_sec * 1000))

            #     now = (duration_sec - duration_sec) + 1000 * (progress_sec / 1000)
                
            #     os.system("cls")  # Clear console for readability
            #     print(f"Discord Timestamps: start={start_timestamp_ms}, end={end_timestamp_ms}")
            #     print(f"Discord Duration: {duration_sec}s, Progress: {progress_sec}s")
            #     print(f"Discord Now: {now}")

            #     kwargs['start'] = now
            #     kwargs['end'] = duration_sec
            
            # Send update
            client.update(**kwargs)
            print(f"Updated Discord: {title} ({duration_sec}s)")
            
        except Exception as e:
            print(f"Discord update error: {e}")
            self.last_sent_discord_track = None

    def start_auth_flow(self):
        try:
            self.auth_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        def _auth():
            try:
                client_id = ENV_VALUES.get('Client_ID')
                client_secret = ENV_VALUES.get('Client_Secret')
                if not client_id or not client_secret:
                    try:
                        client_id = simpledialog.askstring('Client ID', 'Enter YouTube Music Client ID:')
                        client_secret = simpledialog.askstring('Client Secret', 'Enter YouTube Music Client Secret:')
                        if not client_id or not client_secret:
                            messagebox.showerror('Authentication', 'Client ID and Client Secret are required.')
                            return
                    except Exception as e:
                        messagebox.showerror('Authentication', f'Error: {e}')
                        return

                auth_path = os.path.join(CONFIG_DIR, 'auth.json')
                try:
                    ytmusicapi.setup_oauth(filepath=auth_path, client_id=client_id, client_secret=client_secret)
                except Exception as e:
                    messagebox.showerror('Authentication Error', f'Failed to run setup_oauth: {e}')
                    return

                try:
                    if os.path.exists(auth_path):
                        try: shutil.copy(auth_path, os.path.join(os.getcwd(), 'auth.json'))
                        except: pass
                        try: shutil.copy(auth_path, os.path.join(os.path.dirname(__file__), 'auth.json'))
                        except: pass
                except: pass

                messagebox.showinfo('Authentication', 'Authentication complete — auth.json created.')
                self.init_ytmusic()
            finally:
                try: self.auth_btn.config(state=tk.NORMAL)
                except: pass

        threading.Thread(target=_auth, daemon=True).start()

    def create_ui(self):
        main_frame = tk.Frame(self.root, bg='#1a1a1a')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        content_frame = tk.Frame(main_frame, bg='#1a1a1a')
        content_frame.pack(fill=tk.X)

        self.art_label = tk.Label(content_frame, bg='#1a1a1a')
        self.art_label.grid(row=0, column=0, rowspan=3, sticky='nw', padx=(0,10))

        title_font = font.Font(family='Segoe UI', size=12, weight='bold')
        self.title_label = tk.Label(content_frame, text='Now Playing', font=title_font, fg='#1DB954', bg='#1a1a1a')
        self.title_label.grid(row=0, column=1, sticky='w')

        song_font = font.Font(family='Segoe UI', size=14, weight='bold')
        self.song_label = tk.Label(content_frame, text='Waiting for local data...', font=song_font, fg='#ffffff', bg='#1a1a1a', wraplength=420, justify=tk.LEFT)
        self.song_label.grid(row=1, column=1, sticky='w', pady=(5, 0))

        artist_font = font.Font(family='Segoe UI', size=10)
        self.artist_label = tk.Label(content_frame, text='', font=artist_font, fg='#b3b3b3', bg='#1a1a1a', wraplength=420, justify=tk.LEFT)
        self.artist_label.grid(row=2, column=1, sticky='w')

        duration_font = font.Font(family='Segoe UI', size=9)
        self.duration_label = tk.Label(main_frame, text='0:00 / 0:00', font=duration_font, fg='#888888', bg='#1a1a1a')
        self.duration_label.pack(anchor='w', pady=(8, 3))

        progress_frame = tk.Frame(main_frame, bg='#1a1a1a')
        progress_frame.pack(fill=tk.X, padx=0, pady=(0, 5))

        self.progress_canvas = tk.Canvas(progress_frame, height=8, bg='#1a1a1a', highlightthickness=0)
        self.progress_canvas.pack(fill=tk.X)
        self.progress_bg = self.progress_canvas.create_rectangle(0,0,550,8, fill='#333333', outline='#333333')
        self.progress_fill = self.progress_canvas.create_rectangle(0,0,0,8, fill='#1DB954', outline='#1DB954')

        button_frame = tk.Frame(main_frame, bg='#1a1a1a')
        button_frame.pack(fill=tk.X, padx=0, pady=(10, 0))

        browse_btn = tk.Button(button_frame, text='Open Local Now Playing JSON', command=self.browse_local_json, bg='#444444', fg='#ffffff', border=0, padx=8, pady=5, cursor='hand2')
        browse_btn.pack(side=tk.RIGHT, padx=5)

        self.auth_btn = tk.Button(button_frame, text='Authenticate (Browser)', command=self.start_auth_flow, bg='#555555', fg='#ffffff', border=0, padx=8, pady=5, cursor='hand2')
        self.auth_btn.pack(side=tk.RIGHT, padx=5)

    def browse_local_json(self):
        path = filedialog.askopenfilename(title='Select local_now_playing.json', filetypes=[('JSON files','*.json'), ('All files','*.*')])
        if not path: return
        try:
            dest = os.path.join(CONFIG_DIR, 'local_now_playing.json')
            with open(path, 'r', encoding='utf-8') as src, open(dest, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            messagebox.showinfo('Local Now Playing', f'Copied to {dest}')
        except Exception as e:
            messagebox.showwarning('Copy failed', str(e))

    def load_now_playing(self):
        path = find_local_now_playing()
        if not path: return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            title = data.get('title', 'Unknown')
            artist = data.get('artist', '')
            duration = int(data.get('duration', 0) or 0)
            progress = int(data.get('progress', 0) or 0)
            image_path = data.get('image_path')
            return {'title': title, 'artist': artist, 'duration': duration, 'progress': progress, 'image_path': image_path}
        except Exception:
            return None

    def get_now_playing_from_yt(self):
        if not getattr(self, 'yt', None): return None
        try:
            # Try History
            try:
                history = self.yt.get_history()
                if history and len(history) > 0:
                    track = history[0]
                    title = track.get('title', 'Unknown')
                    artist = ''
                    if 'artists' in track and track['artists']:
                        artists_list = []
                        for artist_info in track['artists']:
                            if isinstance(artist_info, dict) and 'name' in artist_info: artists_list.append(artist_info['name'])
                            elif isinstance(artist_info, str): artists_list.append(artist_info)
                        artist = ', '.join(artists_list)

                    duration = 0
                    if 'duration' in track and track['duration']:
                        try:
                            if isinstance(track['duration'], int): duration = track['duration']
                            elif isinstance(track['duration'], str):
                                parts = track['duration'].split(':')
                                if len(parts) == 2: duration = int(parts[0]) * 60 + int(parts[1])
                        except: duration = 0

                    image_url = None
                    vid = track.get('videoId') or track.get('video_id')
                    try:
                        if vid:
                            song_info = self.yt.get_song(vid)
                            if song_info and isinstance(song_info, dict):
                                vd = song_info.get('videoDetails') or {}
                                if vd and isinstance(vd, dict):
                                    th = vd.get('thumbnail') or vd.get('thumbnails')
                                    if isinstance(th, dict) and 'thumbnails' in th and th['thumbnails']:
                                        image_url = th['thumbnails'][-1].get('url')
                                if not image_url and 'thumbnail' in song_info:
                                    th = song_info.get('thumbnail')
                                    if isinstance(th, list) and th:
                                        image_url = th[-1].get('url') if isinstance(th[-1], dict) else th[-1]
                    except: image_url = None

                    return {'title': title, 'artist': artist, 'duration': duration, 'progress': 0, 'is_playing': True, 'videoId': vid, 'image_url': image_url}
            except: pass
            return None
        except: return None

    def update_loop(self):
        while True:
            try:
                current_time = time.time()
                time_delta = current_time - self.last_update_time
                self.last_update_time = current_time

                info = None
                if getattr(self, 'yt', None):
                    try: info = self.get_now_playing_from_yt()
                    except: info = None

                if not info: info = self.load_now_playing()

                if info:
                    # --- SIMULATE PROGRESS ---
                    title = info.get('title', '')
                    duration = info.get('duration', 0)
                    
                    if title != self.last_track_title:
                        self.last_track_title = title
                        self.simulated_progress = 0
                    else:
                        if duration > 0 and self.simulated_progress < duration:
                            self.simulated_progress += time_delta
                    
                    if info.get('progress', 0) == 0:
                        info['progress'] = int(self.simulated_progress)
                    else:
                        self.simulated_progress = info['progress']

                    self.root.after(0, self._update_labels, info)
                else:
                    self.root.after(0, self._update_labels, {'title': 'Waiting for local data...', 'artist': '', 'duration': 0, 'progress': 0, 'image_path': None})
                
                time.sleep(UPDATE_INTERVAL)
            except Exception:
                time.sleep(1)

    def _update_labels(self, info):
        self.update_discord_presence(info)
        
        self.song_label.config(text=info.get('title', 'Unknown'))
        self.artist_label.config(text=info.get('artist', ''))

        duration = info.get('duration', 0)
        progress = info.get('progress', 0)

        def format_time(seconds):
            mins = int(seconds) // 60
            secs = int(seconds) % 60
            return f"{mins}:{secs:02d}"

        self.duration_label.config(text=f"{format_time(progress)} / {format_time(duration)}")

        if duration > 0:
            progress_percent = min(progress / duration, 1.0)
            progress_width = progress_percent * 520
        else:
            progress_width = 0
        self.progress_canvas.coords(self.progress_fill, 0,0, progress_width, 8)

        img_path = info.get('image_path')
        if img_path:
            try:
                if not os.path.isabs(img_path):
                    alt = os.path.join(os.getcwd(), img_path)
                    if os.path.exists(alt): img_path = alt
                    else:
                        alt2 = os.path.join(CONFIG_DIR, img_path)
                        if os.path.exists(alt2): img_path = alt2

                if img_path in self.image_cache:
                    photo = self.image_cache[img_path]
                elif os.path.exists(img_path):
                    img = Image.open(img_path).convert('RGBA')
                    img.thumbnail((96,96), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self.image_cache[img_path] = photo
                else: photo = None
                
                if photo:
                    self.art_label.config(image=photo)
                    self.art_image = photo
                else:
                    self.art_label.config(image='')
                    self.art_image = None
            except:
                self.art_label.config(image='')
                self.art_image = None
        else:
            self.art_label.config(image='')
            self.art_image = None

    def run(self):
        try:
            self.root.mainloop()
        finally:
            pass

if __name__ == '__main__':
    root = tk.Tk()
    overlay = LocalMusicOverlay(root)
    overlay.run()