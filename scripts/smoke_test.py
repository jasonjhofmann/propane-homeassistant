#!/usr/bin/env python3
"""Standalone live smoke test for pyneevo.

Logs into Nee-Vo and prints each tank's current telemetry — no Home Assistant
required. Useful for confirming credentials and the pyneevo API surface before
configuring the integration.

Usage:
    NEEVO_EMAIL=... NEEVO_PASSWORD=... python3 scripts/smoke_test.py
"""

import asyncio
import os
import sys

from pyneevo import NeeVoApiInterface

LITERS_PER_GALLON = 3.785411784


async def main() -> None:
    email = os.environ.get("NEEVO_EMAIL")
    password = os.environ.get("NEEVO_PASSWORD")
    if not email or not password:
        sys.exit("Set NEEVO_EMAIL and NEEVO_PASSWORD")

    api = await NeeVoApiInterface.login(email, password)
    tanks = await api.get_tanks_info()
    if not tanks:
        sys.exit("No tanks returned for this account")

    print(f"{len(tanks)} tank(s):\n")
    for tank in tanks.values():
        gallons = None
        if tank.level is not None and tank.tank_capacity:
            gallons = round(
                tank.level / 100.0 * tank.tank_capacity / LITERS_PER_GALLON, 1
            )
        print(tank.name)
        print(f"  level:    {tank.level} %")
        print(f"  capacity: {tank.tank_capacity} L")
        print(f"  est.:     {gallons} gal")
        print(f"  last:     {tank.data.get('LastReadingDate')}")
        if tank.tank_last_pressure is not None:
            unit = tank.tank_last_pressure_unit
            print(f"  pressure: {tank.tank_last_pressure} {unit}")


if __name__ == "__main__":
    asyncio.run(main())
