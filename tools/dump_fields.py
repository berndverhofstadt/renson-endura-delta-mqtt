#!/usr/bin/env python3
"""
Read every field from a live unit and show how it lines up with the catalog.

Useful for two things: checking a unit before wiring up MQTT, and extending
shared/fields.py for Endura Delta variants other than the reference model
(different sensor options report different field sets).

    python -m tools.dump_fields --host 192.168.1.60
    python -m tools.dump_fields --host 192.168.1.60 --show-published
    python -m tools.dump_fields --host 192.168.1.60 --probe-writable

--probe-writable establishes which fields accept writes by POSTing each field's
*own current value* back, so nothing changes. It skips identity and network
fields, and never touches the DANGEROUS ones - writing those stops the fans and
latches errors that need a power cycle to clear.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.validation import coerce_reading
from shared.fields import BY_NAME, DANGEROUS, ERROR_FIELD, FIELDS
from shared.renson_client import ReadOnlyFieldError, RensonClient, RensonError

# A no-op write is harmless, but re-applying network or identity settings could
# still nudge the device into reconfiguring itself, so leave them alone.
PROBE_SKIP_PREFIXES = ("Week program", "MAC", "Warranty", "Registration", "Static",
                       "DHCP", "Firmware", "Hardware", "Device type", "Error list",
                       "SD card", "System startup", "Date and time")

# Left out of the catalog on purpose, so do not suggest adding them: the week
# programme is a 7x6 schedule better edited in the app, the network settings are
# not the bridge's business, and Error list has its own handling.
EXPECTED_UNCATALOGUED = ("Week program", "Static", "DHCP", "Registration key", ERROR_FIELD)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--show-published", action="store_true",
                        help="Show the MQTT payload each reading would produce")
    parser.add_argument("--probe-writable", action="store_true",
                        help="Determine writability with no-op writes")
    args = parser.parse_args()

    client = RensonClient(args.host, port=args.port)
    try:
        readings = client.read_all()
    except RensonError as exc:
        raise SystemExit(f"cannot read from {args.host}: {exc}")

    print(f"{len(readings)} fields reported by {args.host}\n")

    known, unknown = [], []
    for (name, index), value in readings.items():
        (known if name in BY_NAME else unknown).append((name, index, value))

    print(f"-- in catalog ({len(known)}) --")
    for name, index, value in known:
        field = BY_NAME[name]
        line = f"  {name:45} {value!r}"
        if args.show_published:
            payload = coerce_reading(field, value)
            line += f"  -> {field.category}/{field.slug} = " + (
                repr(payload) if payload is not None else "SKIPPED")
        print(line)

    print(f"\n-- reported but not in catalog ({len(unknown)}) --")
    if not unknown:
        print("  (none)")
    for name, index, value in unknown:
        suffix = "" if name.startswith(EXPECTED_UNCATALOGUED) else "   <- consider adding to shared/fields.py"
        print(f"  {name:45} index={list(index)} {value!r}{suffix}")

    missing = [f.name for f in FIELDS if (f.name, f.index) not in readings]
    print(f"\n-- in catalog but not reported ({len(missing)}) --")
    print("  (none)" if not missing else
          "\n".join(f"  {name}" for name in missing))
    if missing:
        print("  These are hardware options this unit does not have; the bridge skips them.")

    if not args.probe_writable:
        return

    print("\n-- writability (no-op writes) --")
    writable, read_only = [], []
    for (name, index), value in sorted(readings.items()):
        if name.startswith(PROBE_SKIP_PREFIXES) or name in DANGEROUS:
            continue
        try:
            client.write_field(name, value, index)
            writable.append(name)
        except ReadOnlyFieldError:
            read_only.append(name)
        except RensonError as exc:
            print(f"  {name:45} probe failed: {exc}")

    print(f"\n  writable ({len(writable)}):")
    for name in writable:
        catalogued = BY_NAME.get(name)
        flag = "" if catalogued is None or catalogued.writable else "   <- catalog says read-only!"
        print(f"    {name}{flag}")
    print(f"\n  read-only ({len(read_only)}):")
    for name in read_only:
        catalogued = BY_NAME.get(name)
        flag = "" if catalogued is None or not catalogued.writable else "   <- catalog says writable!"
        print(f"    {name}{flag}")
    print(f"\n  not probed: {len(DANGEROUS)} dangerous + identity/network fields")


if __name__ == "__main__":
    main()
