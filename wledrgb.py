import logging
import socket
import struct
import threading
from zeroconf import ServiceBrowser, Zeroconf

_LOGGER = logging.getLogger(__name__)

# --- CONFIGURATION ---
UNIVERSE = 1
PIXEL_COUNT = 109      
NUM_CHANNELS = PIXEL_COUNT * 3
E131_PORT = 5568
WLED_UDP_PORT = 21324
WLED_TIMEOUT = 2       
# ---------------------

class WLEDManager:
    def __init__(self):
        self.devices = {}
        self.lock = threading.Lock()

    def add_device(self, ip):
        with self.lock:
            if ip not in self.devices:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.devices[ip] = sock
                _LOGGER.info(f">>> Connected to WLED at {ip}")

    def broadcast(self, rgb_payload):
        # --- THE FIX: RGB -> GBR MAPPING ---
        # Logic based on your report:
        # Hardware expects: Slot1=Green, Slot2=Blue, Slot3=Red
        
        data = bytearray(rgb_payload)
        for i in range(0, len(data), 3):
            if i + 2 < len(data):
                # Pull the original colors from OpenRGB
                r_in, g_in, b_in = data[i], data[i+1], data[i+2]
                
                # Re-assign them to the hardware's preferred order
                data[i]     = g_in  # Slot 1 gets Green
                data[i+1]   = b_in  # Slot 2 gets Blue
                data[i+2]   = r_in  # Slot 3 gets Red

        # WLED DRGB Header
        header = bytes([0x02, WLED_TIMEOUT])
        packet = header + data
        
        with self.lock:
            for ip, sock in self.devices.items():
                try:
                    sock.sendto(packet, (ip, WLED_UDP_PORT))
                except:
                    pass

class E131ToWLED:
    def __init__(self, manager):
        self.manager = manager
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.sock.bind(("", E131_PORT))

    def run(self):
        _LOGGER.info(f"BRIDGE ACTIVE")
        _LOGGER.info(f"Universe: {UNIVERSE} | LEDs: {PIXEL_COUNT}")
        _LOGGER.info(f"Mapping: Incoming Red -> Hardware Slot 3")
        
        while True:
            try:
                data, _ = self.sock.recvfrom(2048)
                if len(data) < 126: continue

                received_universe = struct.unpack('!H', data[113:115])[0]
                if received_universe != UNIVERSE: continue

                # Get the 327 bytes for 109 LEDs
                rgb_payload = data[126 : 126 + NUM_CHANNELS]
                
                if len(rgb_payload) >= NUM_CHANNELS:
                    self.manager.broadcast(rgb_payload[:NUM_CHANNELS])
            except Exception as e:
                _LOGGER.error(f"Loop error: {e}")

class WLEDDiscovery:
    def __init__(self, manager):
        self.manager = manager
        self.zeroconf = Zeroconf()

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            for addr in info.addresses:
                ip = socket.inet_ntoa(addr)
                self.manager.add_device(ip)

    def remove_service(self, *args): pass
    def update_service(self, *args): pass

def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    manager = WLEDManager()
    discovery = WLEDDiscovery(manager)
    browser = ServiceBrowser(discovery.zeroconf, "_wled._tcp.local.", discovery)
    bridge = E131ToWLED(manager)
    
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        discovery.zeroconf.close()

if __name__ == '__main__':
    main()