# openmagic

This project provides an E1.31 (sACN) listener that receives RGB data packets and sends them to a FluxLED (Zengge) Wi-Fi smart bulb. It allows your smart LED device to be controlled using E1.31 protocols commonly used in lighting control software.

## Features
- Listens for E1.31 (sACN) packets on Universe 1
- Extracts RGB data and applies it to a FluxLED Wi-Fi bulb
- Supports real-time DMX control over Wi-Fi
- Simple configuration using Python

## Prerequisites
- A FluxLED-compatible Wi-Fi bulb (e.g., Zengge, MagicHome, etc.)
- Python 3.6+
- A network with multicast support for E1.31
- OpenRGB or an E1.31-compatible lighting control software

## Installation

1. Clone the repository:
   ```sh
   git clone https://github.com/your-repo/open-zengge.git
   cd open-zengge
   ```

2. Install required dependencies:
   ```sh
   pip install flux_led numpy voluptuous
   ```

## Configuration

Edit the `config` dictionary in the script:

```python
config = {
    "ip_address": "192.168.0.1",  # Change to your device's IP
    "pixel_count": 1,
}
```

Ensure your Wi-Fi LED bulb is on and reachable at the specified IP address.

## Running the Bridge

Run the script with:
```sh
python openmagic.py
```

The script will listen for incoming E1.31 packets and apply the RGB values to your FluxLED device.

## OpenRGB Setup
To use this with OpenRGB as an E1.31 device, configure it as follows:

- **Name:** FluxLED E1.31
- **IP (Unicast):** `127.0.0.1` or ( Your device's IP)
- **Start Universe:** `1`
- **Start Channel:** `1`
- **Number of LEDs:** `1`
- **Type:** `Single`
- **RGB Order:** `RGB`
- **Universe Size:** `512`

Once configured, OpenRGB will send RGB data to the script, which will forward it to the FluxLED bulb.
![openrgb config](https://imgur.com/a/6FXa3dH.png)

## Troubleshooting
- **Device not responding?** Ensure the IP address is correct and the device is powered on.
- **No E1.31 data received?** Check your network configuration to allow multicast traffic.
- **RGB colors incorrect?** Modify the `setRgb(r, g, b)` call in the script.

## License
MIT License. See `LICENSE` for details.

## Credits
Developed by mfalme. Contributions welcome!

