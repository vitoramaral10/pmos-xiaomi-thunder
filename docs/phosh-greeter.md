# Phosh greeter bring-up

State: the greeter (greetd + phrog) renders, accepts a password and logs in.
The Phosh **user session** still resets the device shortly after login. The
device therefore boots to Weston; `greetd` is deliberately left out of every
runlevel so a failure can never turn into a boot loop.

## What had to be fixed

Five independent blockers, each hiding the next. Three are the same disease:
an edge userspace that assumes a kernel much newer than this vendor 4.19.

### 1. The display driver rejects its own buffers

`mtk_gem_prime_import()` only accepts DMA-BUFs it can import through Android's
ION allocator and returns `-EINVAL` for anything else. wlroots allocates a DRM
dumb buffer, exports it and re-imports it through PRIME before scan-out, so
phoc could never bring up the display.

The driver advertises `DRM_CAP_PRIME` with import support, which is a lie —
the same shape of bug as the Bluetooth `LMP_SYNC_TRAIN` feature bit.

Reproducing it takes 30 lines: create a dumb buffer, export it, re-import it.
On the *same* file descriptor it succeeds, because that only hits the per-file
PRIME handle cache. On a second descriptor of the same device it fails, which
is what wlroots does — its allocator re-opens the node on purpose.

Fixed by `fix-mtk-gem-prime-import-fallback.patch`: fall through to the generic
import instead of bailing out. Swapchain test failures went from 2012 to 0.

### 2. The greeter user cannot open the seat

`/run/seatd.sock` is `srwxrwx--- root seat`, and neither `greetd` nor the
regular user was in the `seat` group.

### 3. The on-screen keyboard aborts

`stevia` ships its GSettings schema in a separate `stevia-schemas` subpackage
that nothing pulled in. Without it the keyboard dies with a fatal
`GLib-GIO-ERROR`, and it is a *required* component of the session.

### 4. bubblewrap cannot mount anything

Alpine builds bubblewrap with `-Dassume_kernel` set to the current LTS, which
compiles out the `openat2` fallback. `openat2` is 5.6+, so on 4.19 every bind
mount fails with `ENOSYS` and nothing that uses bwrap works — including glycin,
which is how GTK4 loads SVG icons. Not even
`--debug-opt=force-openat-fallback` helps: the fallback is not in the binary.

Forked as `pmaports/temp/bubblewrap` without that option.

### 5. glib reports every file as missing

`g_local_file_query_exists()` calls `faccessat()` with `AT_SYMLINK_NOFOLLOW`.
Before 5.8 there is no `faccessat2()` and the old syscall takes no flags, so
musl returns `EINVAL` and glib concludes the file is absent — for every caller
of `g_file_query_exists()`.

Measured directly on the device:

    faccessat flags=0                      -> 0
    faccessat AT_EACCESS                   -> 0
    faccessat AT_SYMLINK_NOFOLLOW          -> -1 EINVAL

This killed the greeter: appstream decided its catalog had vanished (the files
are present and non-empty) and phrog died reading an uninitialised `GError`.
Upstream already works around the same `EINVAL` on Android and Solaris.

Forked as `pmaports/temp/glib`.

## Session environment

Both the greeter and the user session need the same environment, and neither
gets it by default. See `device-scripts/phrog-session-pixman` and
`device-scripts/phosh-session-thunder`.

- `LIBSEAT_BACKEND=seatd` — with the logind backend the session gets
  deactivated, phoc releases the display, and disabling the CRTC hangs the
  panel until the hardware watchdog resets the device. Weston has always used
  seatd and never falls over. Setting this removed every `Failed to disable
  CRTC` and `Broken pipe` from the logs.
- `XDG_CURRENT_DESKTOP=Phosh:GNOME` — `phosh-session` sets no desktop name and
  `phosh.desktop` carries no `DesktopNames=`, so `gnome-session` never matches
  `OnlyShowIn=GNOME` on `mobi.phosh.Shell` and the session spins forever
  without ever starting the shell.
- A short delay before the session takes the seat. Without it the greeter's
  phoc has not released `seat0` yet and seatd drops the new connection.
- pixman and cairo: the Mali-G57 has no free userspace driver on this kernel,
  so everything renders in software.

## Still open

After login the device resets during `gnome-session` startup, with no kernel
panic recorded — the hardware watchdog fires, which means a real hang. Ruled
out by measurement: the kernel patch (phoc alone survives 120 s of rendering),
`hang_detect` (disabled), memory (3.4 GB free), idle blanking (verified 0 in
effect), and the power key (`HandlePowerKey=ignore`).

The full session starts 17 required components at once against the greeter's
four. Three are natural suspects on this hardware: `gsd-usb-protection` (the
USB gadget configfs path already panics this kernel), `gsd-rfkill` and
`gsd-wwan`. A bisection down to shell + keyboard alone still reset the device,
so the burst itself is not obviously the trigger either.

## Unrelated kernel bug found on the way

`usb-signaller` panics the kernel while tearing down the USB gadget:

    sysfs_remove_file_ns -> device_remove_file -> gadgets_drop
    -> configfs_rmdir -> vfs_rmdir2 -> do_rmdir -> unlinkat

A NULL dereference in `sysfs_remove_file_ns`. Removed from the default runlevel.
This fits the USB networking being unreliable on this device.

## Debugging note

Logs from a session that resets the device cannot be kept on the device:
`/tmp` is tmpfs, and a newly created file on the rootfs is discarded as an
orphan inode by the boot-time fsck. Pre-creating the file survives, but the
output stays in the pipe buffer. Streaming each line off the device over the
network is the only method that captured the failure.
