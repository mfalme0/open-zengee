import logging
import socket
import struct
import flux_led
import numpy as np
import voluptuous as vol

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
            
            self.bulb.setRgb(rgb_data[0], rgb_data[1], rgb_data[2])
        except Exception as e:
            _LOGGER.error(f"Error sending data to bulb at {self._ip_address}: {e}")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    config = {
        "ip_address": "10.5.6.2",  # Change to your device IP
        "pixel_count": 1,
    }
    
    device = ZenggeDevice(config)
    listener = E131Listener(universe=1)

    device.activate()

    try:
        while True:
            rgb_data = listener.receive_packet()
            if rgb_data:
                device.flush(rgb_data)
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")
    finally:
        device.deactivate()
