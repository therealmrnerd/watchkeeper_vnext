import socket
import sys
import time

FPS = 30.0
DURATION = 2.5


def build_dmx(mode_arg: str, brightness: int):
    mode_arg = mode_arg.strip().upper()

    if mode_arg.startswith("S"):
        mode_type = "scene"
        value = int(mode_arg[1:])
    elif mode_arg.startswith("C"):
        mode_type = "chase"
        value = int(mode_arg[1:])
    else:
        mode_type = "scene"
        value = int(mode_arg)

    value &= 0xFF
    brightness &= 0xFF

    dmx = bytearray(7)
    if mode_type == "scene":
        dmx[0] = value
        dmx[1] = value
        dmx[2] = 0
        dmx[3] = 1
    else:
        dmx[0] = 0
        dmx[1] = 0
        dmx[2] = value
        dmx[3] = 2

    dmx[4] = 0
    dmx[5] = 0
    dmx[6] = brightness
    return dmx, mode_type, value


def build_artnet_packet(dmx: bytes, universe: int) -> bytes:
    packet = bytearray()
    packet.extend(b"Art-Net\x00")
    packet.extend((0x5000).to_bytes(2, "little"))
    packet.extend((14).to_bytes(2, "big"))
    packet.append(0)
    packet.append(0)

    u = universe & 0xFF
    uni = u & 0x0F
    subnet = (u >> 4) & 0x0F
    packet.append((subnet << 4) | uni)
    packet.append(0)
    packet.extend(len(dmx).to_bytes(2, "big"))
    packet.extend(dmx)
    return bytes(packet)


def main():
    if len(sys.argv) != 5:
        print("Usage: jinxsender.py <ip> <mode> <brightness_0_255> <universe_0_255>")
        sys.exit(1)

    ip = sys.argv[1]
    mode_arg = sys.argv[2]
    brightness = int(sys.argv[3]) & 0xFF
    universe = int(sys.argv[4]) & 0xFF

    dmx, mode_type, value = build_dmx(mode_arg, brightness)
    packet = build_artnet_packet(dmx, universe)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    frames = int(FPS * DURATION)
    interval = 1.0 / FPS

    print(
        f"Sending {frames} frames at {FPS} FPS (~{DURATION}s) to {ip}, "
        f"universe {universe}; mode={mode_type}, value={value}, brightness={brightness}"
    )

    for _ in range(frames):
        start = time.perf_counter()
        sock.sendto(packet, (ip, 6454))
        elapsed = time.perf_counter() - start
        sleep_time = interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    sock.close()
    print("Burst complete.")


if __name__ == "__main__":
    main()
