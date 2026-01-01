import logging
import time
import threading
import flux_led
import voluptuous as vol
import asyncio
import sys
import ctypes
from ctypes import wintypes
import colorsys
import random

_LOGGER = logging.getLogger(__name__)

# -------------------- Alternative Dynamic Lighting Implementation --------------------
class WindowsAccentColorReader:
    """Get Windows accent color as fallback for Dynamic Lighting."""
    
    def __init__(self):
        self.last_color = (255, 255, 255)
        self.color_change_time = time.time()
        
    def get_accent_color(self):
        """Get Windows accent color using Windows API."""
        try:
            # Windows Registry approach
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"SOFTWARE\Microsoft\Windows\DWM")
            accent_color_value = winreg.QueryValueEx(key, "AccentColor")[0]
            winreg.CloseKey(key)
            
            # Convert DWORD to RGB
            r = (accent_color_value >> 0) & 0xFF
            g = (accent_color_value >> 8) & 0xFF  
            b = (accent_color_value >> 16) & 0xFF
            
            return (r, g, b)
        except:
            return None
    
    def get_wallpaper_dominant_color(self):
        """Simulate getting dominant color from wallpaper."""
        # This is a placeholder - in reality you'd analyze the wallpaper
        # For now, cycle through some nice colors
        colors = [
            (30, 144, 255),   # Dodger Blue
            (255, 20, 147),   # Deep Pink
            (50, 205, 50),    # Lime Green
            (255, 165, 0),    # Orange
            (138, 43, 226),   # Blue Violet
            (220, 20, 60),    # Crimson
            (0, 191, 255),    # Deep Sky Blue
            (255, 69, 0),     # Red Orange
        ]
        
        # Change color every 30 seconds
        index = int(time.time() / 30) % len(colors)
        return colors[index]
    
    def get_time_based_color(self):
        """Generate color based on time of day."""
        current_hour = time.localtime().tm_hour
        
        if 6 <= current_hour < 12:  # Morning - warm colors
            hue = 0.1 + (current_hour - 6) * 0.05  # Yellow to orange
        elif 12 <= current_hour < 18:  # Afternoon - bright colors
            hue = 0.5 + (current_hour - 12) * 0.05  # Cyan to blue
        elif 18 <= current_hour < 22:  # Evening - warm colors
            hue = 0.05 + (current_hour - 18) * 0.02  # Orange to red
        else:  # Night - cool colors
            hue = 0.8 - (current_hour if current_hour < 6 else current_hour - 24) * 0.05
        
        # Convert HSV to RGB
        r, g, b = colorsys.hsv_to_rgb(hue, 0.8, 1.0)
        return (int(r * 255), int(g * 255), int(b * 255))

class AlternativeDynamicLighting:
    """Alternative implementation when WinRT is not available."""
    
    def __init__(self):
        self.accent_reader = WindowsAccentColorReader()
        self.mode = "time_based"  # Options: accent, wallpaper, time_based, cycle
        self.last_update = 0
        self.current_color = (255, 255, 255)
        
    async def get_color(self):
        """Get current color based on selected mode."""
        now = time.time()
        
        # Update color every 5 seconds to avoid too frequent changes
        if now - self.last_update < 5:
            return self.current_color
            
        try:
            if self.mode == "accent":
                color = self.accent_reader.get_accent_color()
                if color:
                    self.current_color = color
            elif self.mode == "wallpaper":
                self.current_color = self.accent_reader.get_wallpaper_dominant_color()
            elif self.mode == "time_based":
                self.current_color = self.accent_reader.get_time_based_color()
            elif self.mode == "cycle":
                # Cycle through rainbow colors
                hue = (now / 10) % 1.0  # Complete cycle every 10 seconds
                r, g, b = colorsys.hsv_to_rgb(hue, 0.8, 1.0)
                self.current_color = (int(r * 255), int(g * 255), int(b * 255))
                
        except Exception as e:
            _LOGGER.error(f"Error getting alternative color: {e}")
            
        self.last_update = now
        return self.current_color

# -------------------- Dynamic Lighting Color Reader --------------------
async def get_dynamic_lighting_color():
    """Fetch color using available method."""
    # Try WinRT first (will fail on Python 3.13)
    try:
        import winrt.windows.devices.lights as lights
        lamp = await lights.Lamp.get_default_async()
        if lamp:
            color = lamp.color
            return (color.r, color.g, color.b)
    except (ImportError, RuntimeError, Exception) as e:
        # Fall back to alternative method
        if not hasattr(get_dynamic_lighting_color, 'alt_lighting'):
            get_dynamic_lighting_color.alt_lighting = AlternativeDynamicLighting()
            _LOGGER.info("Using alternative dynamic lighting (Windows accent/time-based colors)")
        
        return await get_dynamic_lighting_color.alt_lighting.get_color()
    
    # Final fallback
    return (255, 255, 255)

# -------------------- Zengge Device --------------------
class ZenggeDevice:
    """FluxLED/MagicHome device controlled via Dynamic Lighting."""

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

    def flush(self, rgb):
        if not self._is_active:
            _LOGGER.warning(f"Device at {self._ip_address} is not active. Cannot flush data.")
            return
        try:
            r, g, b = rgb
            self.bulb.setRgb(r, g, b)
            _LOGGER.debug(f"Set RGB to ({r}, {g}, {b})")
        except Exception as e:
            _LOGGER.error(f"Error sending data to bulb at {self._ip_address}: {e}")

# -------------------- Device Scanner --------------------
class DeviceScanner:
    """Scan for FluxLED/Zengge devices on the network."""
    
    def __init__(self, scan_timeout=5, rescan_interval=300):
        self.scan_timeout = scan_timeout
        self.rescan_interval = rescan_interval
        self.devices = []
        self.scan_lock = threading.Lock()
        self.last_scan_time = 0
        self.active_device = None
        
    def discover_devices(self):
        with self.scan_lock:
            if time.time() - self.last_scan_time < 10:
                return self.devices
            
            _LOGGER.info("Scanning for FluxLED/Zengge devices...")
            try:
                discovered_devices = flux_led.BulbScanner().scan(timeout=self.scan_timeout)
                device_ips = []
                for device in discovered_devices:
                    device_ip = device['ipaddr']
                    device_ips.append(device_ip)
                    _LOGGER.info(f"Found FluxLED device at: {device_ip}")
                self.devices = device_ips
                self.last_scan_time = time.time()
                return self.devices
            except Exception as e:
                _LOGGER.error(f"Error during device scan: {e}")
                return []

    def start_background_scanner(self):
        def scanner_thread():
            while True:
                self.discover_devices()
                time.sleep(self.rescan_interval)
        
        scanner = threading.Thread(target=scanner_thread, daemon=True)
        scanner.start()
        return scanner
    
    def get_active_device(self):
        if not self.devices:
            self.discover_devices()
        
        if self.devices:
            if self.active_device is None or self.active_device not in self.devices:
                self.active_device = self.devices[0]
            return self.active_device
        return None

# -------------------- Main Loop --------------------
async def main():
    logging.basicConfig(level=logging.INFO)
    
    _LOGGER.info(f"Running on Python {sys.version}")
    _LOGGER.info("Note: Using alternative dynamic lighting due to Python 3.13 compatibility")
    
    scanner = DeviceScanner(scan_timeout=5)
    devices = scanner.discover_devices()
    
    if not devices:
        _LOGGER.error("No FluxLED/Zengge devices found.")
        return

    scanner.start_background_scanner()
    
    active_device_ip = scanner.get_active_device()
    _LOGGER.info(f"Using device at {active_device_ip}")
    
    config = {
        "ip_address": active_device_ip,
        "pixel_count": 1,
    }
    
    device = ZenggeDevice(config)
    device.activate()

    try:
        _LOGGER.info("Starting color sync loop...")
        while True:
            rgb = await get_dynamic_lighting_color()
            device.flush(rgb)
            await asyncio.sleep(0.5)  # Update every 0.5 seconds for alternative method
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")
    finally:
        device.deactivate()

if __name__ == '__main__':
    asyncio.run(main())