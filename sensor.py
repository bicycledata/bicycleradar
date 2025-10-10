import asyncio
from multiprocessing.connection import Connection

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

from bicycleinit.BicycleSensor import BicycleSensor


def bin2dec(n):
    """
    Convert floating point binary (exponent=-2) to decimal float.
    """
    fractional_part = 0.0
    if n & 1 > 0:
        fractional_part += 0.25
    if n & 2 > 0:
        fractional_part += 0.5
    return fractional_part + (n>>2)

def notification_handler(sensor, characteristic: BleakGATTCharacteristic, data: bytearray):
    """
    Simple notification handler which processes the data received into a
    CSV row and prints it into a file.
    """

    target_id_mask = 0b11111100 # mask that reveals first 6 bits; use '&' with value
    target_ids = [0 for x in range(6)]
    target_ranges = [0 for x in range(6)] # 6 targets, each 3 bytes (info, range, speed)
    target_speeds = [0.0 for x in range(6)]
    bin_target_speeds = ["" for x in range(6)]

    # data is a bytearray
    intdata = [x for x in data]
    j = 0 # target index
    for i, dat in enumerate(intdata[1:]): # ignore flags in pos 0
        if i%3 == 0: # each target has 3 bytes
            j = i//3
            target_ids[j] = (dat & target_id_mask)
        elif i%3 == 1:
            target_ranges[j] = dat
        else:
            target_speeds[j] = bin2dec(dat)
            bin_target_speeds[j] = format(dat, '08b')

    if target_ids[0] == 0:
        return # no targets detected, don't log

    data_row = [f'"{target_ids}"', f'"{target_ranges}"', f'"{target_speeds}"', f'"{bin_target_speeds}"']
    sensor.write_measurement(data_row)

async def scan(radar_mac):
    """
    Scan for the correct Varia.
    """
    return await BleakScanner.find_device_by_address(radar_mac)


async def connect(sensor, device, char_uuid):
    """
    Connect to the correct Varia.
    """
    # pair with device if not already paired
    async with BleakClient(device, pair=True) as client:
        sensor.send_msg("Varia connected.")
        await client.start_notify(char_uuid, lambda c, d: notification_handler(sensor, c, d))
        await asyncio.Future()  # run indefinitely

async def radar(sensor, radar_mac, char_uuid):
    """
    Main radar function that coordinates communication with Varia radar.
    """
    varia = await scan(radar_mac) # find the BLEDevice we are looking for
    if not varia:
        sensor.send_msg("Device not found")
        return

    await connect(sensor, varia, char_uuid)

def main(bicycleinit: Connection, name: str, args: dict):
    sensor = BicycleSensor(bicycleinit, name, args)

    radar_mac = args.get('address')
    char_uuid = args.get('char_uuid')
    if not radar_mac:
        sensor.send_msg('Error: Missing required config parameter: "address"')
        return
    if not char_uuid:
        sensor.send_msg('Error: Missing required config parameter: "char_uuid"')
        return

    sensor.write_header(['target_ids', 'target_ranges', 'target_speeds', 'bin_target_speeds'])

    # Run the radar logic in the asyncio event loop
    try:
        asyncio.run(radar(sensor, radar_mac, char_uuid))
    except Exception as e:
        sensor.send_msg(f"Radar loop error: {e}")

    sensor.shutdown()

if __name__ == "__main__":
    main(None, "radar", {})
