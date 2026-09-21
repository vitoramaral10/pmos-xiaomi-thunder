# Extracting the vendor firmware

None of the proprietary blobs are distributed here. You extract them from the
stock ROM of your own device. Everything below is read-only with respect to the
phone.

## What you need, and why

| File | Needed for | Lives in |
|---|---|---|
| `nt36672c_tm_01_ts_fw.bin` | touchscreen | `vendor` partition |
| `nt36672c_tm_01_ts_mp.bin` | touchscreen self-test | `vendor` partition |
| `soc2_2_ram_mcu_1_1_hdr.bin` | CONNSYS MCU | `vendor` partition |
| `soc2_2_ram_wifi_1_1_hdr.bin` | Wi-Fi | `vendor` partition |
| `soc2_2_ram_bt_1_1_hdr.bin` | Bluetooth | `vendor` partition |
| `WIFI_RAM_CODE_soc2_2_1_1.bin` | Wi-Fi firmware | `vendor` partition |

The Novatek NT36672C is a **host-download** touchscreen controller: the IC
holds no firmware of its own and the host uploads it on every boot. Without the
`.bin` the driver logs
`update_firmware_request: firmware load failed, ret=-2` and the touch interrupt
line is never raised.

The CONNSYS ROM patches are equally non-optional — the connectivity subsystem
has its own CPU and boots from DRAM. See
[wifi-bringup.md](wifi-bringup.md).

## `_1_1` versus `_1a_1`

The stock ROM ships two variants of each connectivity patch. They are picked by
the **A-die chip ID**, not by anything in the header — `u2HwVer`, `u2SwVer`,
the load address and the patch type are byte-identical between them, only the
build date differs. This port uses `_1_1`. If your unit has the other A-die,
try `_1a_1`.

## Getting them out, without root

The device ships a `super.img` with dynamic partitions. With an unlocked
bootloader:

```sh
# dump the super partition from fastboot, or pull the factory ROM
lpunpack super.img out/          # splits into vendor.img, system.img, ...
```

Then, for an ext4 `vendor.img`, no mounting and no root needed:

```sh
debugfs -R "dump /firmware/nt36672c_tm_01_ts_fw.bin nt36672c_tm_01_ts_fw.bin" vendor.img
debugfs -R "ls -l /firmware" vendor.img     # to browse
```

Paths vary by ROM build; `debugfs -R "ls -l /firmware"` is the way to find
them. On some builds the connectivity patches are under `/firmware/` and on
others under `/etc/firmware/`.

## The Wi-Fi NVRAM (MAC address and RF calibration)

Separate from the firmware blobs above, and **not** a file you copy out of the
stock ROM: it lives in the device's own `nvdata` partition and is unique to
each unit.

```sh
mount -o ro /dev/disk/by-partlabel/nvdata /mnt      # READ-ONLY, always
cp /mnt/APCFG/APRDEB/WIFI /lib/firmware/wifi_nvram.bin
umount /mnt
```

Mount it read-only and never write to it. It holds the factory RF calibration
for this specific radio; there is no way to regenerate it if you corrupt it.

The file is 2050 bytes, with the MAC address at offset 4. It is consumed by
[`device-scripts/wifi-nvram-push.py`](../device-scripts/wifi-nvram-push.py),
which hands it to the driver at bring-up.

Because it is per-unit data, **no MAC address or calibration blob belongs in
this repository** — the script reads whatever the device it runs on has.

Currently gated behind `/etc/thunder-wifi-nvram` and off by default, for
reasons explained in
[wifi-bringup.md](wifi-bringup.md#the-factory-mac-solved-mechanism-unusable-in-practice).

## Installing them

Touchscreen blobs go next to the device APKBUILD before building — see
[building.md](building.md).

The connectivity blobs go straight into `/lib/firmware/` on the device. That is
the path `request_firmware()` searches, and the path
[`device-scripts/wmt-daemon.py`](../device-scripts/wmt-daemon.py) reads the
patch headers from.

## Licensing

These files are proprietary to Novatek, MediaTek and Xiaomi. Extracting them
from a device you own for use on that device is one thing; redistributing them
is another. **Do not commit them to a public repository and do not submit them
to pmaports.**
