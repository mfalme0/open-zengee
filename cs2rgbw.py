import json
import time
import threading
import socket
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
import flux_led

# --- CONFIGURATION ---
SECRET_KEY = "rx5w2bXmCCWJu6"
GSI_PORT = 5000
WLED_UDP_PORT = 21324
FLUX_PORT = 5577 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

class GameState:
    def __init__(self):
        self.last_kills = 0
        self.kill_event_time = 0
        self.game_active = False
        self.last_heartbeat = 0

game_state = GameState()

class DeviceManager:
    def __init__(self):
        self.assigned_devices = []

    def update_all(self, r, g, b, ammo, max_ammo, is_flashed):
        for dev in self.assigned_devices:
            threading.Thread(target=self._send_to_device, 
                             args=(dev, r, g, b, ammo, max_ammo, is_flashed), 
                             daemon=True).start()

    def _send_to_device(self, dev, r, g, b, ammo, max_ammo, is_flashed):
        try:
            # ROLE: AMMO COUNTER (WLED ONLY)
            # If we are NOT flashed, show the ammo. If we ARE flashed, show white.
            if dev['role'] == "ammo" and dev['type'] == "wled":
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                header = bytearray([2, 2])
                
                if is_flashed:
                    payload = bytearray([r, g, b] * 100) # Show flash on ammo strip too
                else:
                    if ammo is None or max_ammo is None: return
                    num_leds = 30 
                    on_leds = int((ammo / max_ammo) * num_leds) if max_ammo > 0 else 0
                    pixels = []
                    for i in range(num_leds):
                        if i < on_leds: pixels.extend([0, 200, 255])
                        else: pixels.extend([0, 0, 0])
                    payload = bytearray(pixels)
                
                sock.sendto(header + payload, (dev['ip'], WLED_UDP_PORT))

            # ROLE: GENERAL (ZENGGE & WLED)
            elif dev['role'] == "general":
                if dev['type'] == 'zengge':
                    dev['obj'].setRgb(r, g, b, persist=False)
                elif dev['type'] == 'wled':
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    header = bytearray([2, 2])
                    payload = bytearray([r, g, b] * 150)
                    sock.sendto(header + payload, (dev['ip'], WLED_UDP_PORT))
        except: pass

device_manager = DeviceManager()

def process_gsi(data):
    player = data.get("player", {})
    state = player.get("state", {})
    round_data = data.get("round", {})
    match_stats = player.get("match_stats", {})
    
    # --- 1. FLASHBANG (HIGHEST PRIORITY) ---
    # CS2 returns 'flashed' as a value from 0 to 255
    flash_alpha = state.get("flashed", 0)
    if flash_alpha > 0:
        # If flashed, return pure white at the intensity of the blindness
        return (flash_alpha, flash_alpha, flash_alpha), None, None, True

    # --- 2. KILL FLASH ---
    now = time.time()
    current_kills = match_stats.get("kills", 0)
    if current_kills > game_state.last_kills:
        game_state.kill_event_time = now
        game_state.last_kills = current_kills
    
    if now - game_state.kill_event_time < 0.6:
        return (0, 255, 120), None, None, False

    # --- 3. AMMO DATA ---
    weapons = player.get("weapons", {})
    ammo = None; max_ammo = None
    for w in weapons.values():
        if w.get("state") == "active":
            ammo = w.get("ammo_clip"); max_ammo = w.get("ammo_clip_max"); break

    # --- 4. ENVIRONMENTAL & HEALTH ---
    if state.get("burning", 0) > 0: rgb = (255, 45, 0)
    elif state.get("smoked", 0) > 0: rgb = (100, 100, 130)
    elif round_data.get("bomb") == "planted": rgb = (255, 0, 0)
    else:
        h = state.get("health", 100)
        if h <= 0: rgb = (0, 0, 0)
        elif h > 80: rgb = (0, 255, 0)
        elif h > 40: rgb = (255, 180, 0)
        else: rgb = (255, 0, 0)
        
    return rgb, ammo, max_ammo, False

class GSIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode('utf-8'))
            if data.get("auth", {}).get("key1") != SECRET_KEY:
                self.send_response(403); self.end_headers(); return
            
            app.after(0, lambda: app.set_game_status(True))
            rgb, ammo, m_ammo, is_flash = process_gsi(data)
            device_manager.update_all(rgb[0], rgb[1], rgb[2], ammo, m_ammo, is_flash)
        except: pass
        self.send_response(200); self.end_headers()
    def log_message(self, format, *args): return

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CS2 Smart LED Commander PRO")
        self.geometry("600x850")
        self.configure(bg="#0a0a0a")
        
        tk.Label(self, text="CS2 TACTICAL HUB", fg="#00ffcc", bg="#0a0a0a", font=("Impact", 32)).pack(pady=10)
        self.status_label = tk.Label(self, text="● SYSTEM STANDBY", fg="#555", bg="#0a0a0a", font=("Arial", 10, "bold"))
        self.status_label.pack()

        # Manual/Discovery UI
        manual_frame = tk.Frame(self, bg="#0a0a0a")
        manual_frame.pack(pady=10)
        self.manual_ip = tk.Entry(manual_frame, width=15, bg="#222", fg="white"); self.manual_ip.pack(side="left", padx=5)
        tk.Button(manual_frame, text="Add Flux (Manual)", command=lambda: self.manual_add("zengge")).pack(side="left", padx=2)
        tk.Button(manual_frame, text="Add WLED (Manual)", command=lambda: self.manual_add("wled")).pack(side="left", padx=2)

        self.list_frame = tk.LabelFrame(self, text=" Found Devices ", fg="white", bg="#0a0a0a", padx=10, pady=10)
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=5)
        self.device_listbox = tk.Listbox(self.list_frame, bg="#111", fg="#00ffcc", font=("Consolas", 10), borderwidth=0)
        self.device_listbox.pack(fill="both", expand=True)

        btn_frame = tk.Frame(self, bg="#0a0a0a")
        btn_frame.pack(fill="x", padx=20, pady=5)
        tk.Button(btn_frame, text="ASSIGN GENERAL", bg="#00ffcc", fg="black", font=("Arial", 9, "bold"), command=lambda: self.assign_role("general")).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(btn_frame, text="ASSIGN AMMO", bg="#0099ff", fg="white", font=("Arial", 9, "bold"), command=lambda: self.assign_role("ammo")).pack(side="left", expand=True, fill="x", padx=2)

        self.active_frame = tk.LabelFrame(self, text=" Active Setup ", fg="white", bg="#0a0a0a", padx=10, pady=10)
        self.active_frame.pack(fill="both", expand=True, padx=20, pady=5)
        self.active_display = tk.Text(self.active_frame, height=5, bg="#050505", fg="#00ffcc", font=("Consolas", 9))
        self.active_display.pack(fill="both")

        tk.Button(self, text="DEEP SCAN NETWORK", command=self.scan_network, bg="#222", fg="white").pack(pady=5, fill="x", padx=50)
        tk.Button(self, text="RESET ALL", command=self.clear_setup, bg="#441111", fg="white").pack(pady=5, fill="x", padx=100)

        self.found_devices = []
        self.game_connected = False

    def set_game_status(self, connected):
        game_state.last_heartbeat = time.time()
        if not self.game_connected:
            self.game_connected = True
            self.status_label.config(text="● CS2 LINK ACTIVE", fg="#00ff00")
            threading.Thread(target=self._monitor_heartbeat, daemon=True).start()

    def _monitor_heartbeat(self):
        while self.game_connected:
            if time.time() - game_state.last_heartbeat > 30:
                self.game_connected = False
                self.after(0, lambda: self.status_label.config(text="● CS2 LINK LOST", fg="#ff3333"))
                break
            time.sleep(5)

    def scan_network(self):
        self.device_listbox.delete(0, tk.END)
        threading.Thread(target=self.run_scan, daemon=True).start()

    def run_scan(self):
        try:
            for dev in flux_led.BulbScanner().scan(timeout=2.0):
                self.add_device("zengge", dev['ipaddr'], f"Zengge [{dev['ipaddr']}]")
        except: pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
            prefix = ".".join(s.getsockname()[0].split('.')[:-1]); s.close()
            threads = []
            for i in range(1, 255):
                t = threading.Thread(target=self.probe_ip, args=(f"{prefix}.{i}",))
                t.start(); threads.append(t)
                if i % 50 == 0: time.sleep(0.1)
            for t in threads: t.join(timeout=0.5)
        except: pass
        self.after(0, self.refresh_list)

    def probe_ip(self, ip):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                if s.connect_ex((ip, FLUX_PORT)) == 0: self.add_device("zengge", ip, f"Flux Bulb [{ip}]")
                elif s.connect_ex((ip, 80)) == 0:
                    r = requests.get(f"http://{ip}/json/info", timeout=0.6)
                    if "WLED" in r.text: self.add_device("wled", ip, f"WLED Strip [{ip}]")
        except: pass

    def manual_add(self, dtype):
        ip = self.manual_ip.get().strip()
        if ip: self.add_device(dtype, ip, f"Manual {dtype.upper()} [{ip}]"); self.refresh_list()

    def add_device(self, dtype, ip, name):
        if not any(d['ip'] == ip for d in self.found_devices):
            self.found_devices.append({"type": dtype, "ip": ip, "name": name})

    def refresh_list(self):
        self.device_listbox.delete(0, tk.END)
        for d in self.found_devices: self.device_listbox.insert(tk.END, d['name'])

    def assign_role(self, role):
        idx = self.device_listbox.curselection()
        if not idx: return
        dev_info = self.found_devices[idx[0]]
        device_manager.assigned_devices = [d for d in device_manager.assigned_devices if d['ip'] != dev_info['ip']]
        obj = flux_led.WifiLedBulb(dev_info['ip']) if dev_info['type'] == 'zengge' else None
        device_manager.assigned_devices.append({"ip": dev_info['ip'], "type": dev_info['type'], "role": role, "obj": obj})
        self.update_active_display()

    def clear_setup(self):
        device_manager.assigned_devices = []
        self.update_active_display()

    def update_active_display(self):
        self.active_display.delete('1.0', tk.END)
        for d in device_manager.assigned_devices:
            self.active_display.insert(tk.END, f"[{d['role'].upper()}] {d['type'].upper()} @ {d['ip']}\n")

if __name__ == "__main__":
    app = App()
    threading.Thread(target=lambda: HTTPServer(('', GSI_PORT), GSIHandler).serve_forever(), daemon=True).start()
    app.mainloop()