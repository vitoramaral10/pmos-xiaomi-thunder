# Flashing

> **This wipes `userdata` — roughly 107 GB.** Photos, messages, apps, all of
> it. The point of no return is Phase 3. Everything before it is read-only or
> reversible.

The device is A/B. These instructions assume the active slot is `_a`; Phase 1
checks that.

## Phase 0 — Before anything

1. Back up whatever you care about. While the stock/LineageOS system still
   boots with ADB authorised, `adb pull` works.
2. **Back up the stock partitions.** At minimum `boot`, `vbmeta` and `dtbo` —
   they are your way back.
3. Battery above 50%.
4. A cable you trust, in a rear USB port.

## Phase 1 — Enter fastboot and check (read-only)

```sh
adb reboot bootloader
fastboot devices                        # must list the device
fastboot getvar current-slot            # expected: a
fastboot getvar partition-size:boot_a   # must be >= 0x2BA0000 (45.73 MB)
fastboot getvar partition-size:userdata # expected ~107 GB
fastboot getvar has-slot:boot           # expected: yes
```

**Decision gate.** If `current-slot` is not `a`, or `boot_a` is smaller than
your `boot.img`, stop — the plan changes. Nothing has been written yet and
`fastboot reboot` returns the device untouched.

If `has-slot:boot` answers `yes`, `fastboot flash boot` resolves to the active
slot on its own. If it answers `no` or comes back empty, name `boot_a`
explicitly in Phase 3.

## Phase 2 — Disable verification (AVB)

The device has `vbmeta_a`, `vbmeta_system_*` and `vbmeta_vendor_*`. An unsigned
`boot.img` is rejected while AVB is on, and the symptom is a bootloop or a
"dm-verity corruption" screen rather than anything informative. Hence this
phase comes first.

```sh
avbtool make_vbmeta_image --flags 2 --padding_size 2048 \
  --output /tmp/vbmeta-disabled.img

fastboot --disable-verity --disable-verification \
  flash vbmeta /tmp/vbmeta-disabled.img
```

`--padding_size 2048` is the device's `deviceinfo_flash_pagesize`.

**Reversible:** `fastboot flash vbmeta <your-backup>/vbmeta.img`.

## Phase 3 — Flash (POINT OF NO RETURN)

Verify the artifacts first:

```sh
PMOS_WORK=/path/to/pmbootstrap/work python3 tools/verify-artifacts.py
```

```sh
fastboot flash boot     /tmp/postmarketOS-export/boot.img
fastboot flash userdata /tmp/postmarketOS-export/xiaomi-thunder.img
```

- `boot.img` (~45.73 MB) replaces the kernel in the active slot.
- `xiaomi-thunder.img` (~1.31 GB) **erases all of `userdata`.** The image
  carries its own GPT with `pmOS_boot` (ext2) and `pmOS_root` (ext4); the
  initramfs finds them by the UUIDs baked into the boot.img cmdline. Both
  artifacts must come from the **same build** — that is what
  `verify-artifacts.py` checks.

`dtbo_a` is left alone. The DTB this port builds is byte-identical to the stock
base, so the factory dtbo overlays stay coherent. There is no postmarketOS dtbo
to flash.

## Phase 4 — First boot

```sh
fastboot reboot
```

Give it about two minutes; the first boot is slow. Signs of life from the host:

```sh
dmesg -w | grep -i usb        # device enumerating
ip link                       # a USB network interface appearing
ssh <user>@172.16.42.1        # credentials are whatever you set in pmbootstrap
```

If the USB network interface exists but has no address, bring it up on the host
side — after a re-enumeration NetworkManager sometimes drops the static
address:

```sh
nmcli connection up <your-usb-profile> ifname <iface>
```

**Never lock the bootloader.**

## Going back

```sh
fastboot flash boot   <your-backup>/boot.img
fastboot flash vbmeta <your-backup>/vbmeta.img
fastboot flash dtbo   <your-backup>/dtbo.img
fastboot reboot
```

That restores the factory boot chain. It does **not** restore your data —
`userdata` was overwritten in Phase 3.

## Rebooting into fastboot later, without touching the device

Use `device-scripts/reinicia-no-fastboot.py`. Measured: **8 seconds** from the
command to the device enumerating as `18d1:d00d`, interface class `ff/42/03`,
with `fastboot getvar product` answering `thunder`.

`reboot bootloader` does **not** work here, and an earlier version of this
document claimed it did. The bootloader was never the problem: `/bin/reboot` on
postmarketOS is a symlink to busybox, and **busybox ignores the argument
entirely** — it always calls `reboot(RB_AUTOBOOT)`. The word `bootloader` is
dropped silently, with no error and no warning, and the device reboots straight
back into pmOS.

The kernel has both hooks, confirmed in `/proc/kallsyms`: `rtc_mark_fast()`
(`drivers/misc/mediatek/rtc/mtk_rtc_common.c`) sets `RTC_FAST_BOOT = 0x1` in an
RTC spare register for the preloader to read, and `do_kernel_restart()` passes
the command string to the restart handlers. All that was missing was someone
passing the string — which needs the four-argument form of the `reboot()`
syscall, with `LINUX_REBOOT_CMD_RESTART2` and a pointer to the text. No libc
wrapper exposes that form (`reboot()` in both musl and glibc takes a single
argument), hence the raw syscall in the script.

`echo b > /proc/sysrq-trigger` cannot work either, for a different reason:
sysrq calls `emergency_restart()`, which skips the restart handlers and so
skips `rtc_mark_fast()`. It reboots, always into pmOS. Useful to know when a
wedged module blocks a clean shutdown and sysrq is your only way out.

One trap worth repeating: in normal operation the device enumerates as
`18d1:d001`, and `usb.ids` labels that pair "Nexus 4 (fastboot)". The label is
a lie — the pmOS RNDIS gadget reuses that ID. What tells the two apart is the
interface class: `e0/01/03` with `rndis_host` for the gadget, `ff/42/03` for
real fastboot.
