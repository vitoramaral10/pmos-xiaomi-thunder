# Building

## Prerequisites

- [pmbootstrap](https://gitlab.postmarketos.org/postmarketOS/pmbootstrap)
- a checkout of [pmaports](https://gitlab.postmarketos.org/postmarketOS/pmaports)
- the vendor firmware blobs, see [vendor-firmware.md](vendor-firmware.md)

## Placing the packages

Copy the two package directories into your pmaports checkout:

```sh
cp -r pmaports/linux-xiaomi-thunder   "$PMAPORTS"/device/downstream/
cp -r pmaports/device-xiaomi-thunder  "$PMAPORTS"/device/downstream/
```

Then drop the touchscreen blobs you extracted next to the device APKBUILD:

```sh
cp nt36672c_tm_01_ts_fw.bin nt36672c_tm_01_ts_mp.bin \
   "$PMAPORTS"/device/downstream/device-xiaomi-thunder/
cd "$PMAPORTS"/device/downstream/device-xiaomi-thunder && abuild checksum
```

Without those two files `abuild` fails on a missing source.

> Do not `git add` them. They are proprietary. The upstream pmaports tree must
> not carry them either.

## Building

```sh
pmbootstrap build --lax linux-xiaomi-thunder
pmbootstrap build --lax device-xiaomi-thunder
pmbootstrap install
pmbootstrap export
```

`--lax` is needed because the kernel package intentionally does not track
upstream pmaports' stricter checks for downstream kernels.

If `pmbootstrap install` fails with `unable to select packages` naming an older
`-r` of a package, the rootfs chroot is stale. Zap it and rerun:

```sh
pmbootstrap zap
```

## Installing the device scripts

The packages install the kernel and the device package. They do **not** install
anything under `device-scripts/` — those are the userspace pieces that stand in
for Android services, and they have to be put on the device by hand.

Without them the device boots to a console with no compositor and no Wi-Fi.

```sh
# on the device
install -m755 sobe-wifi.sh wifi-nvram-push.py wmt-daemon.py wmt-loader.py \
              weston-thunder-launch sobe-weston le-reg.py /usr/local/bin/
install -m644 weston-thunder.ini /etc/
install -m755 init.d/weston-thunder      /etc/init.d/
install -m755 init.d/touchscreen-thunder-wake /etc/init.d/
install -m755 init.d/wifi-thunder        /etc/init.d/

rc-update add touchscreen-thunder-wake default
rc-update add weston-thunder            default
rc-update add wifi-thunder              default
```

The connectivity firmware also has to be in `/lib/firmware/` — see
[vendor-firmware.md](vendor-firmware.md).

What each service does:

| service | role |
|---|---|
| `touchscreen-thunder-wake` | unblanks the framebuffer, without which the touch controller never raises its interrupt |
| `weston-thunder` | starts the compositor with the pixman software renderer |
| `wifi-thunder` | runs the whole CONNSYS power-on before NetworkManager |

`le-reg.py` is a debugging tool (reads physical registers through `/dev/mem`),
not needed at runtime.

## Verifying before flashing

```sh
PMOS_WORK=/path/to/pmbootstrap/work python3 tools/verify-artifacts.py
```

This checks the generated `boot.img` against the `deviceinfo` offsets and
header version and confirms the rootfs UUIDs match. Run it before every flash —
a boot.img with the wrong load offsets on this platform gives you a black
screen and a fastboot round trip.

## Fast iteration: swapping a single module

Most of the Wi-Fi work touches only `wmt_drv.ko`. A full build, install, export
and flash cycle to test that is wasted time. Instead, pull the module out of the
built `.apk` and copy it onto the running device.

This is safe as long as **vermagic matches**. Bumping `pkgrel` does not change
vermagic — it feeds `KBUILD_BUILD_VERSION`, which lands in `UTS_VERSION` (the
`#21` in `/proc/version`), not `UTS_RELEASE`.

```sh
# on the host
tar -xzf .../linux-xiaomi-thunder-4.19.191-rNN.apk \
    lib/modules/4.19.191-perf/kernel/drivers/misc/mediatek/connectivity/wmt_drv/wmt_drv.ko
modinfo .../wmt_drv.ko | grep vermagic     # must match `uname -r` on the device
python3 -m http.server 8103 --bind 172.16.42.2
```

```sh
# on the device
K=/lib/modules/$(uname -r)/kernel/drivers/misc/mediatek/connectivity/wmt_drv/wmt_drv.ko
cp "$K" /root/wmt_drv.ko.bak
wget -O /tmp/wmt_drv.new http://172.16.42.2:8103/wmt_drv.ko
cp /tmp/wmt_drv.new "$K" && depmod -a
```

Then reboot — `wmt_drv` cannot be unloaded cleanly (see
[wifi-bringup.md](wifi-bringup.md)), and the ROM patch registration is
one-shot per module load, so a stale registration survives until the module is
reloaded.

Serving over HTTP matters: a 1.6 MB module through a base64-over-serial channel
is painfully slow, and once Wi-Fi works the device can just fetch it over the
network.
