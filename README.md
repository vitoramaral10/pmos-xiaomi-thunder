# postmarketOS on the Xiaomi `thunder` (Redmi 10 5G / POCO M4 5G)

A downstream postmarketOS port for the MediaTek **MT6833** (Dimensity 700)
handset that Xiaomi ships as **Redmi 10 5G** in some markets and **POCO M4 5G**
in others. Both share the codename `thunder` (also seen as `light`).

The headline result of this port: **Wi-Fi and Bluetooth both work**, on a SoC
whose connectivity subsystem has no mainline support at all. Getting there took
reconstructing MediaTek's `gen4m` connectivity stack for this SoC, writing a
minimal replacement for the Android userspace daemon that drives it, and then
bridging a driver that only speaks to Android's stack into BlueZ. Those two
write-ups — [docs/wifi-bringup.md](docs/wifi-bringup.md) and
[docs/bluetooth-bringup.md](docs/bluetooth-bringup.md) — are the part of this
repository most likely to be useful to someone else.

> **Status: work in progress.** This is a downstream port on a vendor 4.19
> kernel. It is not upstream-ready and is not a daily driver.

The device page on the official wiki is
**[Xiaomi POCO M4 5G / Redmi 10 5G (xiaomi-thunder)](https://wiki.postmarketos.org/wiki/Xiaomi_POCO_M4_5G_/_Redmi_10_5G_(xiaomi-thunder))**.

## What works

| Component | State | Notes |
|---|---|---|
| Display | works | software rendering only (pixman), no GPU acceleration |
| Touchscreen | works | needs the proprietary Novatek NT36672C firmware, see below |
| Wi-Fi | **works** | brought up at boot by an OpenRC service. 2.4/5 GHz, WPA2 and WPA3, ~133 Mbit/s measured over LAN. The factory MAC and RF calibration are available but off by default — see [wifi-bringup.md](docs/wifi-bringup.md#the-factory-mac-solved-mechanism-unusable-in-practice) |
| Audio (speaker) | works | headphone path written but untested |
| USB networking | works | RNDIS, the usual pmOS `172.16.42.1` |
| Battery | **works** | charges, and since kernel `r26` the fuel gauge reports a level: it counts down unplugged and survives a reboot. Since `r31` it reaches 100% when charging ends. The Gauge Master 3.0 algorithm runs in the kernel instead of Android's `fuelgauged` — see [phosh-greeter.md](docs/phosh-greeter.md), blockers 9 and 14 |
| Phosh | **works** | the device boots into the greeter and the session stays up. The screen blanks and locks on idle or with the power button, with the backlight off, and the touchscreen works again on wake. The scale is fixed at 3, which keeps software rendering usable. Kernel `r30` fixes the polkit checks behind the power menu. Software rendering only, and no brightness control yet — see [phosh-greeter.md](docs/phosh-greeter.md) |
| Bluetooth | **works** | brought up at boot by an OpenRC service. Scanning and pairing verified against a Linux host, BR/EDR and LE, coexisting with Wi-Fi. Factory address read from `nvdata` at run time. **Audio does not play** — A2DP negotiates and the link carries the stream, but the device has no audio session to consume it; see [bluetooth-bringup.md](docs/bluetooth-bringup.md#audio-negotiates-but-nothing-plays) |
| Modem | not started | |
| Cameras | not started | |

The device boots into the Phosh greeter, and `wifi-thunder` brings the radio
up before NetworkManager, so it associates on its own. Weston is still
available as a fallback through its OpenRC service, `weston-thunder`, which is
no longer in the boot sequence.

## Security note: read before installing this

This is a **bring-up port**, not a hardened system. Two things you are opting
into by installing it as-is:

- **`device-xiaomi-thunder` enables a passwordless root telnet on the USB
  link.** SSH with key authentication works over Wi-Fi, but over the USB link
  the SSH key exchange stalls — the RNDIS link loses large TCP segments — so
  telnet is the only way in over the cable, and the recovery path when Wi-Fi
  is down. It listens on the point-to-point USB network
  (`172.16.42.0/24`), which is not routed, so a remote attacker cannot reach
  it — but **anyone who plugs a cable into the device gets root, with no
  password and no prompt.** The `post-install` script marks it TEMPORARY and it
  should be removed once SSH works over the cable too. If that trade is not acceptable to
  you, strip that section from
  `pmaports/device-xiaomi-thunder/device-xiaomi-thunder.post-install` before
  building.
- **Verified boot is disabled** during flashing (see
  [docs/flashing.md](docs/flashing.md)), because an unsigned `boot.img` is
  otherwise rejected. The device will boot anything you give it afterwards.

Neither is a defect to report — both are deliberate, and both are the normal
state of a downstream port at this stage. They are written down here so the
choice is yours and not a surprise.

## What is deliberately **not** in this repository

No proprietary firmware blobs. Specifically absent:

- `nt36672c_tm_01_ts_fw.bin` and `nt36672c_tm_01_ts_mp.bin` — Novatek
  touchscreen firmware
- the MediaTek connectivity firmware (`soc2_2_ram_{mcu,wifi,bt}_*.bin`,
  `WIFI_RAM_CODE_*`)
- MediaTek/Xiaomi audio parameter XML
- any stock ROM image or partition dump

These are extracted from the stock ROM of your own device.
[docs/vendor-firmware.md](docs/vendor-firmware.md) explains how to get them,
and the packaging expects you to drop them in yourself.

The MediaTek connectivity **source** tarball
(`pmaports/linux-xiaomi-thunder/mtk-connectivity-gen4m-mt6833-1.tar.gz`) *is*
included: it is 763 files of GPL-2.0 kernel source, zero binaries, assembled
from public vendor trees.

## Layout

```
pmaports/linux-xiaomi-thunder/   kernel package: APKBUILD, config, patches
pmaports/device-xiaomi-thunder/  device package (minus the firmware blobs)
device-scripts/                  what runs on the device itself
docs/                            build, flash, Wi-Fi and Bluetooth bring-up, vendor firmware
docs/diario-pt/                  the raw debugging journal, in Portuguese
tools/                           artifact verification before flashing
wiki/                            source of the published postmarketOS wiki page
```

`docs/diario-pt/` is kept in the language it was written in. It is a working
log, not polished documentation: every dead end, every wrong assumption and
every register dump, in order. If the English write-ups leave you short, the
answer is probably in there.

## Getting started

1. [docs/vendor-firmware.md](docs/vendor-firmware.md) — extract the blobs from
   your own device first, nothing else works without them
2. [docs/building.md](docs/building.md) — build with pmbootstrap
3. [docs/flashing.md](docs/flashing.md) — **read this before flashing**, it
   wipes `userdata`
4. [docs/building.md#installing-the-device-scripts](docs/building.md#installing-the-device-scripts)
   — the packages do not install `device-scripts/`, and without them the device
   boots to a bare console with no compositor and no Wi-Fi

## The postmarketOS wiki page

This port has a page on the official wiki:
**[Xiaomi POCO M4 5G / Redmi 10 5G (xiaomi-thunder)](https://wiki.postmarketos.org/wiki/Xiaomi_POCO_M4_5G_/_Redmi_10_5G_(xiaomi-thunder))**

`wiki/xiaomi-thunder.mediawiki` in this repository is the source of that page.
It covers the four kernel patches the port needs, the `deviceinfo` parameters
(including the 4096-byte sector geometry), flashing on an A/B device with
verified boot disabled, and the open issues.

**Keep the two in sync in this direction: edit the file here, then paste it
into the wiki.** If you edit the wiki directly, copy the result back into this
file, or the next paste from here silently reverts your change.

Two things the wiki's `Template:Infobox device` will bite you with, both of
which cost time on the first upload:

- `booting = yes` is required, or the template **hides the entire feature
  table** — the page renders with hardware specs only and nothing about what
  works.
- Unknown parameter names fail silently. It is `status_screen` (not
  `status_display`), `status_touch` (not `status_touchscreen`) and
  `releaseyear` (not `released`). A wrong name renders as nothing, with no
  warning.

Feature values are `Y` / `P` / `N` / `-` (not applicable) or blank (untested).
Since this port is not in pmaports, the page sets `packaged = no` and leaves
`category` empty.

## Licensing

See [LICENSING.md](LICENSING.md). Short version: kernel patches and the
connectivity source are GPL-2.0, the packaging follows pmaports (GPL-3.0), and
the scripts written for this port are GPL-3.0.
