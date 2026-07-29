import logging
import socket
import tinytuya
import time
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
# Put your Device IDs and Local Keys here. 
# The script will automatically find their IP addresses on the network.
TUYA_DEVICES_KEYS = {
    "YOUR_DEVICE_ID_1": "YOUR_LOCAL_KEY_1",
    "YOUR_DEVICE_ID_2": "YOUR_LOCAL_KEY_2",
}
TUYA_VERSION = 3.3  # Try 3.3 or 3.5

UDP_PORT = 21324  
WLED_HTTP_PORT = 80 # SignalRGB expects Port 80 for WLED

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
_LOGGER = logging.getLogger(__name__)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

class DeviceScanner:
    """Scans the local network for Tuya devices (The 'Autofind' logic)."""
    def discover(self):
        _LOGGER.info("Scanning for Tuya devices on the network...")
        # TinyTuya uses maxretry instead of timeout. 15 is a good default.
        devices = tinytuya.deviceScan(verbose=False, maxretry=15)
        
        found_list = []
        if not devices:
            _LOGGER.warning("No Tuya devices responded to the broadcast.")
            return []

        for ip in devices:
            dev = devices[ip]
            # Ensure the dictionary contains the IP and ID
            dev_id = dev.get('id', 'Unknown')
            dev_name = dev.get('name', 'Tuya Device')
            _LOGGER.info(f"Found Tuya Device: {dev_name} [ID: {dev_id}, IP: {ip}]")
            
            # Add IP to the dictionary so main() can use it
            dev['ip'] = ip
            found_list.append(dev)
            
        return found_list

class TuyaDeviceWrapper:
    """Handles connection and sending RGB colors to the physical bulb."""
    def __init__(self, dev_id, ip, key):
        self.device = tinytuya.BulbDevice(dev_id, ip, key)
        self.device.set_version(TUYA_VERSION)
        self.device.set_socketRetryLimit(1) 
        self._is_active = False
        self.last_rgb = [0, 0, 0]
        self.update_count = 0

    def activate(self):
        try:
            self.device.turn_on()
            self._is_active = True
            _LOGGER.info(f"Successfully linked to Tuya bulb at {self.device.address}")
        except Exception as e:
            _LOGGER.error(f"Failed to connect: {e}")

    def flush(self, rgb):
        if not self._is_active or self.last_rgb == rgb:
            return
        try:
            r, g, b = rgb
            self.device.set_colour(r, g, b)
            self.last_rgb = rgb
            self.update_count += 1
            if self.update_count % 100 == 0:
                _LOGGER.info(f"Sent {self.update_count} color updates to bulb.")
        except Exception as e:
            _LOGGER.debug(f"Update failed: {e}")

class WLEDUDPListener:
    """Receives lighting data from SignalRGB via UDP."""
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", UDP_PORT))
        self.sock.setblocking(False)

    def receive_packet(self):
        try:
            data, _ = self.sock.recvfrom(1024)
            if not data or len(data) < 2: return None
            
            protocol = data[0]
            # Protocol 4 = DNRGB (Standard for SignalRGB)
            if protocol == 4 and len(data) >= 7:
                return list(data[4:7])
            # Protocol 2 = DRGB
            elif protocol == 2 and len(data) >= 5:
                return list(data[2:5])
            return None
        except BlockingIOError:
            return None
        except Exception:
            return None

class WLEDEmulator(BaseHTTPRequestHandler):
    """Makes this script look like a WLED device to SignalRGB."""
    def _get_info(self):
        return {
            "ver": "0.13.3", "vid": 1,
            "leds": {"count": 1, "rgbw": False, "pin": [2], "pwr": 0, "maxpwr": 0, "bus": 0},
            "name": "Tuya-Bridge",
            "udpport": UDP_PORT, "live": True,
            "arch": "esp8266", "brand": "WLED", "product": "Bridge",
            "mac": "aabbccddeeff", "ip": self.server.local_ip
        }

    def do_GET(self):
        if self.path.startswith('/json'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"state": {"on": True, "bri": 255}, "info": self._get_info()}
            self.wfile.write(json.dumps(response).encode('utf-8'))
    def log_message(self, format, *args): return

def main():
    local_ip = get_local_ip()
    _LOGGER.info(f"Bridge starting on IP: {local_ip}")

    # 1. SCAN FOR DEVICES (The "Autofind")
    scanner = DeviceScanner()
    discovered_devices = scanner.discover()

    active_device = None

    # 2. MATCH DISCOVERED DEVICE TO A KEY IN YOUR CONFIG
    for dev in discovered_devices:
        dev_id = dev.get('id')
        if dev_id in TUYA_DEVICES_KEYS:
            key = TUYA_DEVICES_KEYS[dev_id]
            ip = dev.get('ip')
            _LOGGER.info(f"Matching ID {dev_id} found! Initializing bridge...")
            active_device = TuyaDeviceWrapper(dev_id, ip, key)
            break
    
    if not active_device:
        _LOGGER.error("No matching Tuya devices found. Check your TUYA_DEVICES_KEYS and ensure the bulb is on.")
        return

    active_device.activate()
    listener = WLEDUDPListener()

    # Start HTTP Server for SignalRGB Discovery
    try:
        httpd = HTTPServer(("", WLED_HTTP_PORT), WLEDEmulator)
        httpd.local_ip = local_ip
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        _LOGGER.info(f"WLED Emulator running on port {WLED_HTTP_PORT}")
    except PermissionError:
        _LOGGER.error("Port 80 requires Admin/Sudo. Run your terminal as Administrator.")
        return

    _LOGGER.info("Ready! SignalRGB should now see a 'WLED' device at this computer's IP.")
    
    try:
        while True:
            rgb = listener.receive_packet()
            if rgb:
                active_device.flush(rgb)
            time.sleep(0.01) # 100Hz cap to prevent Tuya overload
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")

if __name__ == '__main__':
    main()