import logging
import socket
import struct
import flux_led
import numpy as np
import voluptuous as vol
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

_LOGGER = logging.getLogger(__name__)


UDP_PORT = 21324  
WLED_HTTP_PORT = 80

def get_local_ip():
    """Find the local IP address of the machine to report to SignalRGB."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        _LOGGER.warning("Could not determine local IP. Falling back to 127.0.0.1")
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

class WLEDUDPListener:
    """Listens for WLED Realtime UDP packets (WARLS/DRGB) on port 21324."""
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", UDP_PORT))
        self.packet_count = 0

    def receive_packet(self):
        """Receive a UDP packet and extract RGB data."""
        try:
            # WLED packets are small, 1024 is plenty
            data, _ = self.sock.recvfrom(1024)
            if len(data) < 2:
                return None
            
            protocol = data[0]
            rgb_data = None

            # Protocol 2: DRGB (Direct RGB)
            # Format: [2, Timeout, R, G, B, ...]
            if protocol == 2:
                if len(data) >= 5:
                    rgb_data = list(data[2:5]) 

            # Protocol 1: WARLS (WarLs)
            # Format: [1, Timeout, Index, R, G, B, ...]
            elif protocol == 1:
                # We assume the first LED in the packet (Index 0) is what we want
                if len(data) >= 6:
                    rgb_data = list(data[3:6])

            # Protocol 4: DNRGB (Direct Not-RGB) - This is what SignalRGB is sending
            # Format: [4, Timeout, Start_High, Start_Low, R, G, B, ...]
            elif protocol == 4:
                # FIX: Skip 4 bytes (Protocol, Timeout, StartHigh, StartLow) to get to RGB
                if len(data) >= 7:
                    rgb_data = list(data[4:7])

            if rgb_data:
                self.packet_count += 1
                # Log every 100th packet to verify data flow without spamming
                if self.packet_count % 100 == 0:
                    _LOGGER.info(f"UDP Packet #{self.packet_count}: Protocol {protocol}, RGB: {rgb_data}")
                return rgb_data
            
            return None

        except BlockingIOError:
            return None
        except Exception as e:
            _LOGGER.debug(f"Error receiving UDP packet: {e}")
            return None

class ZenggeDevice:
    """FluxLED device that receives color updates."""
    CONFIG_SCHEMA = vol.Schema({
        vol.Required("ip_address"): str,
        vol.Required("pixel_count", default=1): vol.All(int, vol.Range(min=1)),
    })

    def __init__(self, config):
        self._config = self.CONFIG_SCHEMA(config)
        self._ip_address = self._config["ip_address"]
        self.bulb = flux_led.WifiLedBulb(self._ip_address)
        self._is_active = False
        self.last_rgb = [0, 0, 0]
        self.update_count = 0

    def activate(self):
        try:
            self.bulb.turnOn()
            time.sleep(0.5)
            self._is_active = True
            current_state = self.bulb.getRgb()
            _LOGGER.info(f"Device at {self._ip_address} activated. Current RGB: {current_state}")
        except Exception as e:
            _LOGGER.error(f"Failed to activate device at {self._ip_address}: {e}")
            self._is_active = False

    def deactivate(self):
        try:
            self.bulb.turnOff()
            self._is_active = False
            _LOGGER.info(f"Device at {self._ip_address} deactivated.")
        except Exception as e:
            _LOGGER.error(f"Failed to deactivate device at {self._ip_address}: {e}")

    def flush(self, rgb_data):
        if not self._is_active:
            return
        try:
            if len(rgb_data) < 3:
                return
            
            r, g, b = rgb_data[0], rgb_data[1], rgb_data[2]
            
            if self.last_rgb == [r, g, b]:
                return

            self.update_count += 1
            
            if self.update_count % 50 == 0:
                _LOGGER.info(f"Update #{self.update_count}: Received RGB: ({r}, {g}, {b})")
            
            self.bulb.setRgb(r, g, b, persist=False)
            self.last_rgb = [r, g, b]
            
            if self.update_count == 1:
                _LOGGER.info(f"First color update sent successfully: RGB({r}, {g}, {b})")
            
        except Exception as e:
            _LOGGER.error(f"Error sending data to bulb at {self._ip_address}: {e}")

class WLEDEmulator(BaseHTTPRequestHandler):
    """Emulates a WLED device for SignalRGB."""

    def _get_info_dict(self):
        """Constructs the WLED info dictionary."""
        return {
            "ver": "0.13.3",
            "vid": 1,
            "leds": { "count": 1, "rgbw": False, "pin": [2], "pwr": 0, "maxpwr": 0, "bus": 0 },
            "str": False,
            "name": "FluxLED WLED",
            "udpport": UDP_PORT,
            "live": True,
            "effects": ["Solid"],
            "palettes": ["Default"],
            "arch": "esp8266",
            "core": "2_7_4_9",
            "freeheap": 10000,
            "uptime": int(time.time() - self.server.start_time),
            "opt": 1,
            "brand": "WLED",
            "product": "FluxLED Emulator",
            "mac": "00:11:22:33:44:55",
            "ip": self.server.local_ip
        }

    def _get_state_dict(self):
        """Constructs the WLED state dictionary."""
        device = self.server.device
        return {
            "on": device._is_active,
            "bri": 255,
            "transition": 0,
            "ps": -1, "pl": -1,
            "seg": [{
                "id": 0, "start": 0, "stop": 1, "len": 1,
                "on": True, "bri": 255,
                "col": [device.last_rgb, [0, 0, 0], [0, 0, 0]],
                "fx": 0, "sx": 128, "ix": 128, "pal": 0,
                "sel": True, "rev": False, "mi": False
            }]
        }

    def do_GET(self):
        path = self.path.rstrip('/')
        response_data = None
        
        if path == '/json/info':
            response_data = self._get_info_dict()
        elif path == '/json':
            response_data = {"state": self._get_state_dict(), "info": self._get_info_dict()}
            _LOGGER.info("SignalRGB requested /json (Keepalive)")

        if response_data:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.rstrip('/') == '/json/state':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                state = json.loads(post_data.decode('utf-8'))
                if 'seg' in state and state['seg'] and 'col' in state['seg'][0]:
                    colors = state['seg'][0]['col']
                    if colors and len(colors[0]) == 3:
                        self.server.device.flush(colors[0])

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success":true}')
            except Exception as e:
                _LOGGER.error(f"Error processing WLED POST state: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

class DeviceScanner:
    """Scans for FluxLED/Zengge devices on the local network."""
    def __init__(self, scan_timeout=5):
        self.scan_timeout = scan_timeout
        self.devices = []
        
    def discover_devices(self):
        """Scan the network."""
        _LOGGER.info("Scanning for FluxLED/Zengge devices...")
        try:
            discovered = flux_led.BulbScanner().scan(timeout=self.scan_timeout)
            self.devices = [dev['ipaddr'] for dev in discovered]
            for dev in discovered:
                _LOGGER.info(f"Found FluxLED device at: {dev['ipaddr']} (ID: {dev['id']})")
            return self.devices
        except Exception as e:
            _LOGGER.error(f"Error during device scan: {e}")
            return []

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    local_ip = get_local_ip()
    _LOGGER.info(f"Script running on local IP: {local_ip}")
    _LOGGER.info(f"Configure SignalRGB WLED Device IP to: {local_ip}")

    scanner = DeviceScanner()
    devices = scanner.discover_devices()
    
    if not devices:
        _LOGGER.error("No FluxLED/Zengge devices found.")
        return

    active_device_ip = devices[0]
    _LOGGER.info(f"Controlling FluxLED device at {active_device_ip}")
    
    device = ZenggeDevice({"ip_address": active_device_ip})
    listener = WLEDUDPListener() 

    device.activate()

    try:
        http_server = HTTPServer(("", WLED_HTTP_PORT), WLEDEmulator)
        http_server.start_time = time.time()
        http_server.device = device
        http_server.local_ip = local_ip
        
        wled_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        wled_thread.start()
        _LOGGER.info(f"WLED emulator started on port {WLED_HTTP_PORT}")
        _LOGGER.info(f"Listening for UDP Color Data on port {UDP_PORT}...")
    except PermissionError:
        _LOGGER.error(f"Permission denied for port {WLED_HTTP_PORT}. Try running with 'sudo'.")
        return
    except OSError as e:
        _LOGGER.error(f"Failed to start server: {e}")
        return

    try:
        while True:

            rgb_data = listener.receive_packet()
            if rgb_data:
                device.flush(rgb_data)
            else:

                time.sleep(0.0001)
    
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")
    finally:
        device.deactivate()
        http_server.shutdown()

if __name__ == '__main__':
    main()