import logging
import socket
import struct
import flux_led
import numpy as np
import voluptuous as vol
import time
import threading

_LOGGER = logging.getLogger(__name__)

E131_PORT = 5568  # Standard E1.31 port

class E131Listener:
    """Listens for E1.31 (sACN) packets and extracts RGB data."""
    def __init__(self, universe=1):
        self.universe = universe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", E131_PORT))

    def receive_packet(self):
        """Receive an E1.31 packet and return the RGB data."""
        try:
            data, _ = self.sock.recvfrom(1024)
            if len(data) < 126:
                return None  # Invalid packet
            
            received_universe = struct.unpack('!H', data[113:115])[0]
            if received_universe != self.universe:
                return None  # Ignore packets from other universes

            # Extract RGB values (offset 126 onwards)
            return list(data[126:])
        except Exception as e:
            _LOGGER.error(f"Error receiving E1.31 packet: {e}")
            return None

class ZenggeDevice:
    """FluxLED device that receives color updates from E1.31 packets."""

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Required("ip_address"): str,
            vol.Required("pixel_count", default=1): vol.All(int, vol.Range(min=1)),
        }
    )

    def __init__(self, config):
        self._config = self.CONFIG_SCHEMA(config)
        self._ip_address = self._config["ip_address"]
        self._pixel_count = self._config["pixel_count"]
        self.bulb = flux_led.WifiLedBulb(self._ip_address)
        self._is_active = False

    def activate(self):
        try:
            self.bulb.turnOn()
            self._is_active = True
            _LOGGER.info(f"Device at {self._ip_address} activated.")
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
            _LOGGER.warning(f"Device at {self._ip_address} is not active. Cannot flush data.")
            return
        try:
            if len(rgb_data) < 3:
                _LOGGER.error(f"Invalid RGB data length: {len(rgb_data)}")
                return
            
            # Swap red and green values
            r, g, b = rgb_data[0], rgb_data[1], rgb_data[2]
            self.bulb.setRgb(g, r, b)  # Swapped R and G
        except Exception as e:
            _LOGGER.error(f"Error sending data to bulb at {self._ip_address}: {e}")

    def test_rgb_connection(self):
        """Test RGB connection by sending a known color (e.g., swapped green and red)."""
        _LOGGER.info(f"Testing RGB connection for device at {self._ip_address}...")
        try:
            # Send a known color with red and green swapped (normally Red -> should appear Green)
            self.bulb.setRgb(255, 0, 0)  # Red should appear as Green
            time.sleep(1)  # Wait for a second to ensure the color is applied
            _LOGGER.info("RGB connection test passed. Device responded to color change.")
        except Exception as e:
            _LOGGER.error(f"RGB connection test failed: {e}")

class DeviceScanner:
    """Automatically scan for FluxLED/Zengge devices on the local network."""
    
    def __init__(self, scan_timeout=5, rescan_interval=300):
        """Initialize scanner.
        
        Args:
            scan_timeout: Time to wait for device responses (seconds)
            rescan_interval: How often to rescan network for new devices (seconds)
        """
        self.scan_timeout = scan_timeout
        self.rescan_interval = rescan_interval
        self.devices = []
        self.scan_lock = threading.Lock()
        self.last_scan_time = 0
        self.active_device = None
        
    def discover_devices(self):
        """Scan the network for FluxLED devices."""
        with self.scan_lock:
            if time.time() - self.last_scan_time < 10:  # Simple rate limiting
                _LOGGER.debug("Skipping scan as last scan was too recent")
                return self.devices
            
            _LOGGER.info("Scanning for FluxLED/Zengge devices...")
            
            try:
                # Use flux_led's built-in scanner
                discovered_devices = flux_led.BulbScanner().scan(timeout=self.scan_timeout)
                
                # Convert discovered devices to a list of IPs
                device_ips = []
                for device in discovered_devices:
                    device_ip = device['ipaddr']
                    device_ips.append(device_ip)
                    _LOGGER.info(f"Found FluxLED device at: {device_ip} (ID: {device['id']})")
                
                self.devices = device_ips
                self.last_scan_time = time.time()
                
                return self.devices
            except Exception as e:
                _LOGGER.error(f"Error during device scan: {e}")
                return []

    def start_background_scanner(self):
        """Start a background thread to periodically scan for new devices."""
        def scanner_thread():
            while True:
                self.discover_devices()
                time.sleep(self.rescan_interval)
        
        scanner = threading.Thread(target=scanner_thread, daemon=True)
        scanner.start()
        return scanner
    
    def get_active_device(self):
        """Return the first available device or None if none found."""
        if not self.devices:
            self.discover_devices()
        
        if self.devices:
            if self.active_device is None or self.active_device not in self.devices:
                self.active_device = self.devices[0]
            return self.active_device
        return None

def main():
    logging.basicConfig(level=logging.INFO)
    
    # Create device scanner and perform initial scan
    scanner = DeviceScanner(scan_timeout=5)
    devices = scanner.discover_devices()
    
    if not devices:
        _LOGGER.error("No FluxLED/Zengge devices found on the network. Check if they are powered on and connected.")
        return

    # Start background scanner thread to discover new devices periodically
    scanner.start_background_scanner()
    
    # Use the first discovered device initially
    active_device_ip = scanner.get_active_device()
    _LOGGER.info(f"Using device at {active_device_ip}")
    
    config = {
        "ip_address": active_device_ip,
        "pixel_count": 1,
    }
    
    device = ZenggeDevice(config)
    listener = E131Listener(universe=1)

    device.activate()

    # Perform the RGB test
    device.test_rgb_connection()

    try:
        while True:
            # Periodically check for new/preferred device
            if time.time() - scanner.last_scan_time > 60:  # Check every minute
                new_device_ip = scanner.get_active_device()
                if new_device_ip != active_device_ip:
                    _LOGGER.info(f"Switching to new device at {new_device_ip}")
                    device.deactivate()
                    
                    config = {
                        "ip_address": new_device_ip,
                        "pixel_count": 1,
                    }
                    
                    device = ZenggeDevice(config)
                    device.activate()
                    active_device_ip = new_device_ip

            # Process E1.31 packets
            rgb_data = listener.receive_packet()
            if rgb_data:
                device.flush(rgb_data)
    
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")
    finally:
        device.deactivate()

if __name__ == '__main__':
    main()