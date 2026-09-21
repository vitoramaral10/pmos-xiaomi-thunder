# postmarketOS on the Xiaomi `thunder` (Redmi 10 5G / POCO M4 5G)

A downstream postmarketOS port for the MediaTek **MT6833** (Dimensity 700)
handset that Xiaomi ships as **Redmi 10 5G** in some markets and **POCO M4 5G**
in others. Both share the codename `thunder` (also seen as `light`).

The headline result of this port: **the Wi-Fi works**, on a SoC whose
connectivity subsystem has no mainline support at all. Getting there took
reconstructing MediaTek's `gen4m` connectivity stack for this SoC and writing a
minimal replacement for the Android userspace daemon that drives it. That work
is written up in [docs/wifi-bringup.md](docs/wifi-bringup.md) — it is the part
of this repository most likely to be useful to someone else.

> **Status: work in progress.** This is a downstream port on a vendor 4.19
> kernel. It is not upstream-ready and is not a daily driver.

## What works

| Component | State | Notes |
|---|---|---|
| Display | works | software rendering only (pixman), no GPU acceleration |
| Touchscreen | works | needs the proprietary Novatek NT36672C firmware, see below |
| Wi-Fi | **works** | brought up at boot by an OpenRC service. 2.4/5 GHz, WPA2 and WPA3, ~133 Mbit/s measured over LAN. The factory MAC and RF calibration are available but off by default — see [wifi-bringup.md](docs/wifi-bringup.md#the-factory-mac-solved-mechanism-unusable-in-practice) |
| Audio (speaker) | works | headphone path written but untested |
| USB networking | works | RNDIS, the usual pmOS `172.16.42.1` |
| Charging | works | the battery charges; the **fuel gauge does not** report a level |
| Bluetooth | **does not work** | same chip as Wi-Fi, and its ROM patch *is* loaded into EMI — but no adapter appears under `/sys/class/bluetooth/`. The radio is up; the host-side HCI stack is missing |
| Modem | not started | |
| Cameras | not started | |

`weston` is started at boot by an OpenRC service, so the device comes up to a
graphical session, and `wifi-thunder` brings the radio up before
NetworkManager, so it associates on its own.

## Security note: read before installing this

This is a **bring-up port**, not a hardened system. Two things you are opting
into by installing it as-is:

- **`device-xiaomi-thunder` enables a passwordless root telnet on the USB
  link.** It exists because SSH does not work on this port yet — dropbear
  accepts the connection but never allocates a pty, so telnet is currently the
  only way in. It listens on the point-to-point USB network
  (`172.16.42.0/24`), which is not routed, so a remote attacker cannot reach
  it — but **anyone who plugs a cable into the device gets root, with no
  password and no prompt.** The `post-install` script marks it TEMPORARY and it
  should be removed the moment SSH works. If that trade is not acceptable to
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
docs/                            build, flash, Wi-Fi bring-up, vendor firmware
docs/diario-pt/                  the raw debugging journal, in Portuguese
tools/                           artifact verification before flashing
wiki/                            draft page for the postmarketOS wiki
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

## Licensing

See [LICENSING.md](LICENSING.md). Short version: kernel patches and the
connectivity source are GPL-2.0, the packaging follows pmaports (GPL-3.0), and
the scripts written for this port are GPL-3.0.
