import os
import time
import logging
import threading
from twitchio.ext import commands
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

# =========================
# Logging
# =========================
logging.basicConfig(
    filename='twitch_rgb.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =========================
# OpenRGB Setup
# =========================
try:
    rgb_client = OpenRGBClient()
    logging.info(f"Connected to OpenRGB: {[d.name for d in rgb_client.devices]}")
except Exception as e:
    logging.error(f"Error connecting to OpenRGB: {e}")
    exit(1)

# =========================
# Animations
# =========================
animations = {
    "check_mark": [
        RGBColor(0, 255, 0), RGBColor(0, 200, 0), RGBColor(0, 150, 0)
    ],
    "police_lights": [
        RGBColor(255, 0, 0), RGBColor(0, 0, 255)
    ],
    "explosion": [
        RGBColor(255, 140, 0), RGBColor(255, 69, 0), RGBColor(255, 0, 0),
        RGBColor(80, 0, 0), RGBColor(0, 0, 0)
    ],
    "mini_explosion": [
        RGBColor(255, 200, 0), RGBColor(255, 100, 0), RGBColor(50, 0, 0)
    ]
}

def update_rgb_color(color):
    try:
        for device in rgb_client.devices:
            if "direct" in [m.name.lower() for m in device.modes]:
                device.set_mode("Direct")
            device.set_color(color)
    except Exception as e:
        logging.error(f"Error updating RGB: {e}")

def play_animation(name, frame_delay=0.15, repeat=1):
    frames = animations.get(name, [])
    if not frames:
        return
    def animate():
        for _ in range(repeat):
            for color in frames:
                update_rgb_color(color)
                time.sleep(frame_delay)
    threading.Thread(target=animate, daemon=True).start()

# =========================
# Twitch Bot Setup
# =========================
TWITCH_TOKEN = os.getenv("TWITCH_TOKEN") or "oauth:yg36g21bv7z3tnguir0trkpey6q2g6"
TWITCH_NICK = os.getenv("TWITCH_NICK") or "streamleds"
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL") or "joe_mfalme"

bot = commands.Bot(
    token=TWITCH_TOKEN,
    prefix="!",
    initial_channels=[TWITCH_CHANNEL]
)

# =========================
# Twitch Events
# =========================
@bot.event
async def event_ready():
    print(f"✅ Logged in as {bot.nick}")

@bot.event
async def event_message(message):
    if message.echo:
        return
    await bot.handle_commands(message)

# Test command in chat: !test check_mark
@bot.command(name="test")
async def test_command(ctx):
    parts = ctx.message.content.split()
    if len(parts) > 1 and parts[1] in animations:
        play_animation(parts[1], 0.15, 3)
        await ctx.send(f"🎨 Playing animation: {parts[1]}")
    else:
        await ctx.send(f"❌ Animation not found. Available: {', '.join(animations.keys())}")

# Example triggers
@bot.command(name="follower")
async def follower_event(ctx):
    play_animation("check_mark", 0.1, 3)

@bot.command(name="sub")
async def sub_event(ctx):
    play_animation("police_lights", 0.2, 6)

@bot.command(name="raid")
async def raid_event(ctx):
    play_animation("explosion", 0.1, 3)

@bot.command(name="cheer")
async def cheer_event(ctx):
    play_animation("mini_explosion", 0.1, 3)

if __name__ == "__main__":
    bot.run()
