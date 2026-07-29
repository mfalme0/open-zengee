import time
import socket
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# --- CONFIGURATION ---
WLED_IP = '192.168.1.100'  # Put your WLED IP here
WLED_PORT = 21324          # Default WLED UDP port
OPENRGB_HOST = '127.0.0.1'
OPENRGB_PORT = 6742
SOURCE_DEVICE_NAME = 'Keyboard' # Change this to the OpenRGB device you want to copy
# ---------------------

def create_wled_packet(led_colors):
    """
    Formats colors into WLED UDP Realtime (DRGB) packet.
    Protocol 4: [4 (DRGB), Timeout (2s), R1, G1, B1, R2, G2, B2...]
    """
    # 4 is the protocol type (DRGB), 2 is the timeout in seconds
    packet = bytearray([4, 2]) 
    
    for color in led_colors:
        packet.append(color.red)
        packet.append(color.green)
        packet.append(color.blue)
    return packet

def main():
    # 1. Connect to OpenRGB
    try:
        client = OpenRGBClient(OPENRGB_HOST, OPENRGB_PORT)
        print(f"Connected to OpenRGB SDK")
    except Exception as e:
        print(f"Could not connect to OpenRGB: {e}")
        return

    # 2. Find the source device
    device = client.get_devices_by_name(SOURCE_DEVICE_NAME)
    if not device:
        print(f"Device '{SOURCE_DEVICE_NAME}' not found!")
        print("Available devices:")
        for d in client.devices:
            print(f" - {d.name}")
        return
    
    source = device[0]
    print(f"Syncing {SOURCE_DEVICE_NAME} ({len(source.leds)} LEDs) to WLED at {WLED_IP}")

    # 3. Setup UDP Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        while True:
            # Get current colors from the OpenRGB device
            # Note: We use .colors because it's updated by OpenRGB effects/plugins
            colors = source.colors
            
            # Create WLED UDP packet
            packet = create_wled_packet(colors)
            
            # Blast it to WLED
            sock.sendto(packet, (WLED_IP, WLED_PORT))
            
            # Small sleep to prevent CPU Maxing, but keep it high refresh (60fps = 0.016)
            time.sleep(0.01) 

    except KeyboardInterrupt:
        print("\nStopping bridge...")
    finally:
        sock.close()

if __name__ == "__main__":
    main()