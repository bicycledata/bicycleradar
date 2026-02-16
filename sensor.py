import argparse
import asyncio
from multiprocessing.connection import Connection
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from bicycleinit.BicycleSensor import BicycleSensor


def bin2dec(n: int) -> float:
    """
    Convert floating point binary (exponent=-2) to decimal float.
    """
    fractional_part = 0.0
    if n & 1:
        fractional_part += 0.25
    if n & 2:
        fractional_part += 0.5
    return fractional_part + (n >> 2)


def notification_handler(sensor, characteristic: BleakGATTCharacteristic, data: bytearray):
    """
    Simple notification handler which processes the data received into a
    CSV row and prints it into a file.
    """

    target_id_mask = 0b11111100  # mask that reveals first 6 bits; use '&' with value

    target_ids = [0 for _ in range(6)]
    target_ranges = [0 for _ in range(6)]  # 6 targets, each 3 bytes (info, range, speed)
    target_speeds = [0.0 for _ in range(6)]
    bin_target_speeds = ["" for _ in range(6)]

    # data is a bytearray
    intdata = list(data)

    j = 0  # target index
    for i, dat in enumerate(intdata[1:]):  # ignore flags in pos 0
        if i % 3 == 0:  # each target has 3 bytes
            j = i // 3
            target_ids[j] = dat & target_id_mask
        elif i % 3 == 1:
            target_ranges[j] = dat
        else:
            target_speeds[j] = bin2dec(dat)
            bin_target_speeds[j] = format(dat, "08b")

    if target_ids[0] == 0:
        sensor.ping()
        return  # no targets detected, don't log

    data_row = [
        f'"{target_ids}"',
        f'"{target_ranges}"',
        f'"{target_speeds}"',
        f'"{bin_target_speeds}"'
    ]

    sensor.write_measurement(data_row)


async def find_varia(sensor, address: Optional[str] = None) -> Optional[BLEDevice]:
    """
    Scan for Garmin Varia radar.
    """
    sensor.send_msg(f"Scanning for Garmin Varia ({address})...")

    devices = await BleakScanner.discover(timeout=5.0)

    if address:
        for d in devices:
            if d.address.lower() == address.lower():
                sensor.send_msg(f"Found Varia by address {d.name} ({d.address})")
                return d
    else:
        for d in devices:
            if d.name and d.name.startswith("RVR"):
                sensor.send_msg(f"Found Varia by name {d.name} ({d.address})")
                return d

    return None


async def connect_loop(sensor, device: BLEDevice, char_uuid: str):
    """
    Connect to radar and auto-reconnect on disconnect.
    Compatible with older Bleak versions.
    """
    while True:
        try:
            sensor.send_msg(f"Connecting to {device.name} ({device.address})")

            async with BleakClient(device) as client:
                sensor.send_msg("Varia connected.")

                await client.start_notify(
                    char_uuid,
                    lambda c, d: notification_handler(sensor, c, d),
                )

                # Stay alive while connected
                while client.is_connected:
                    await asyncio.sleep(1)

        except Exception as e:
            sensor.send_msg(f"Connection error: {e}")

        sensor.send_msg("Disconnected.")
        return


async def radar_loop(sensor, address: Optional[str], char_uuid: str):
    """
    Continuously scan and connect.
    """
    while True:
        device = await find_varia(sensor, address)

        if not device:
            sensor.send_msg("No Varia found. Retrying in 3 seconds...")
            await asyncio.sleep(3)
            continue

        await connect_loop(sensor, device, char_uuid)


def main(bicycleinit: Connection, name: str, args: dict):
    sensor = BicycleSensor(bicycleinit, name, args)

    address = args.get("address")  # optional
    char_uuid = args.get("char_uuid")

    if not char_uuid:
        sensor.send_msg('Error: Missing required config parameter: "char_uuid"')
        return

    sensor.write_header([
        "target_ids",
        "target_ranges",
        "target_speeds",
        "bin_target_speeds"
    ])

    try:
        asyncio.run(radar_loop(sensor, address, char_uuid))
    except KeyboardInterrupt:
        sensor.send_msg("Shutting down radar (KeyboardInterrupt)")
    except Exception as e:
        sensor.send_msg(f"Radar loop error: {e}")
    finally:
        sensor.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="bicycleradar")

    parser.add_argument("--address", type=str, help="BLE device address (optional)", required=False)
    parser.add_argument("--uuid", type=str, help="BLE characteristic UUID (required)", required=True)

    parsed_args = parser.parse_args()

    args = {
        "address": parsed_args.address,
        "char_uuid": parsed_args.uuid,
    }

    main(None, "radar", args)
