# Phosh greeter bring-up

State: the greeter (greetd + phrog) renders, accepts a password and logs in,
and the full Phosh session reaches `RUNNING` with all of its GNOME components.
With kernel `r26` the session stays up: the power button blanks and unblanks
the screen, and the phone no longer switches itself off a minute into the
session. Since device `r11` the phone boots straight into the greeter. Weston
stays installed as a fallback, out of the boot sequence:
`rc-service weston-thunder start`.

## What had to be fixed

Fifteen blockers, each hiding the next, all fixed. Four are the same disease:
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

### 6. gnome-session never leaves its first startup phase

This is what the endless spinner after login actually was.

glib's child watch opens a pidfd for every child it spawns and reaps it with
`waitid(P_PIDFD, ...)`. `pidfd_open()` and `CLONE_PIDFD` arrived in 5.2/5.3 and
were backported into the Android 4.19 tree this kernel descends from;
`waitid(P_PIDFD)` arrived in 5.4 and was not. The mismatch is visible in the
kernel source: `kernel/fork.c` handles `CLONE_PIDFD`, while
`include/uapi/linux/wait.h` defines only `P_ALL` and `P_PID`.

So the pidfd is created, the poll fires when the child exits, and the reap
fails:

    GLib-WARNING: ../glib/gmain.c:6355: waitid(pid:3425, pidfd=13) failed:
    Invalid argument (22)

glib then hands the caller a wait status of `-1`, a value for which neither
`WIFEXITED()` nor `WIFSIGNALED()` holds. gnome-session's exit handler emits
neither `exited` nor `died`, so the app is never taken out of `pending_apps`
and the phase never ends:

    GsmManager: starting phase EARLY_INITIALIZATION
    GsmAutostartApp: starting xdg-user-dirs.desktop: command=xdg-user-dirs-update
    GLib-WARNING: waitid(...) failed: Invalid argument (22)
    GsmAutostartApp: (pid:3425) done (unknown:-1)
    (nothing, ever)

The child also stays a zombie, which is the other visible symptom.

Confirmed by taking that single autostart entry out of the way:
`EARLY_INITIALIZATION` then ends immediately and the session hangs one phase
later, on the two gnome-keyring apps, with the same warning twice. The bug is
in the child watch, not in any one component, so disabling components is not a
workaround.

Patched in the same fork, `pmaports/temp/glib`: probe the kernel once with
`WNOWAIT`, which consumes nothing, and fall back to glib's SIGCHLD path when
`waitid(P_PIDFD)` is missing.

Verified on the device with `glib-2.90.0-r2` installed. The session now walks
every phase instead of stopping at the first one:

    GsmManager: starting phase EARLY_INITIALIZATION
    GLib-DEBUG: waitid(P_PIDFD) is not supported by this kernel;
                falling back to the SIGCHLD child watch
    ... PRE_DISPLAY_SERVER, DISPLAY_SERVER, INITIALIZATION,
        WINDOW_MANAGER, PANEL, DESKTOP, APPLICATION, RUNNING

with `Phosh ready after 1.78s` and fifteen `gsd-*` components up — power,
media-keys, colour, keyboard, rfkill, sound, usb-protection and the rest —
plus `at-spi2-registryd`. The endless spinner is gone.

### 7. The session is not registered as graphical

greetd exports `XDG_SEAT`, `XDG_VTNR` and `XDG_SESSION_CLASS`, but not
`XDG_SESSION_TYPE`, so `pam_elogind` files the session as `Type=unspecified`
and gnome-session reports

    Could not get session id for session. Check that logind is properly
    installed and pam_systemd is getting used at login.

Fixed by giving `/etc/pam.d/greetd` a `pam_env` line ahead of `base-session`,
which is where `pam_elogind` lives, pointing at `/etc/greetd/environment`.
Measured on the device after the change: `Type=wayland`, `Class=user`,
`Seat=seat0`.

### 8. Blanking the screen scans out a freed buffer

Before the fixes below, the device went down while a Wayland session was up,
between about 50 seconds and about 5 minutes after it started, with nothing in
pstore. Everything here was caught by streaming the compositor log and the
kernel log off the device line by line. It turned out to be two unrelated
problems; this is the first.

Three occurrences, always the same shape:

    phosh-main: Phosh ready after 1.74s                       t+0 s
    phoc-wlroots: connector DSI-1: Failed to disable CRTC 64   t+51 s
    mtk_plane_atomic_disable, empty crtc state                 t+51 s
    mtk_iommu_isr ... <<TRANSLATION FAULT>>                    t+51 s
      port=L1_OVL_2L_RDMA0, iova=0xfd2d6000, pa=0x0
    ... the same, repeating, until the device dies

`0xfd2d6000` is exactly the `dma_addr` the driver logged when phoc created its
GEM buffer, and the IOMMU dump shows domain 0 mapped only from `0xfdcc2000`
upwards. The overlay engine is still scanning out a buffer whose mapping is
gone.

The cause is in the vendor driver. `mtk_plane_atomic_disable()` sets
`pending.enable = false` and `pending.dirty = true`, then only pushes the
update when its private `state->crtc` is non-NULL. That field is assigned in
exactly one place, `mtk_crtc_get_plane_comp_state()`, reached only when
userspace has set the CRTC's MediaTek layer-blob property — something the
Android hardware composer does and a Wayland compositor never does. Even when
reached, `mtk_drm_crtc_plane_update()` skips the layer-off unless
`USER_SCEN_BLANK` is set; its own comment says the real disable happens in
`mtk_crtc_get_plane_comp_state()`.

Net effect: **on this driver, disabling a plane from a plain DRM atomic
compositor is a no-op.** The hardware keeps reading the last buffer it was
given — harmless while the compositor keeps feeding it, fatal the moment the
compositor blanks and frees it. Consistent with that, the fault bursts that
happen when one compositor hands over to another are survived: the incoming
compositor reprograms the overlay and the faults stop.

Legacy KMS is not a way out. `WLR_DRM_NO_ATOMIC=1` is honoured by this phoc
build — the string is in the binary — and the disable fails identically, so
the driver cannot turn the display off through either path. Before the fix below,
pressing the power button blanked through the same path and took the device
down too.

Fixed in the driver by `fix-mtk-plane-disable-without-layer-blob.patch`
(kernel `r24`): `mtk_plane_atomic_disable()` falls back to the CRTC the plane
was on when the layer-blob path never filled one in, and the CRTC update turns
the layer off outside `USER_SCEN_BLANK` too. Measured on `r24`: with no
compositor, DPMS off for 45 s and back on survives, and inside the Phosh
session the power button blanks and unblanks the panel cleanly.

Until device `r12` idle blanking and the lock were off as a dconf system
default, from before the fix. With blockers 10 and 11 fixed too, `r12` drops
it, so the screen blanks and locks by GNOME's defaults (5 minutes idle, then
lock). Tested with a 30-second idle delay and with the power button: the
screen goes dark, locks, and the touchscreen takes the password on wake.

### 9. UPower powers the phone off, because the battery reads 0%

The second problem is what the logs had called a "silent hang": the log stops
mid-stream, there is no kernel output, and the last compositor lines are

    [libseat] [libseat/backend/seatd.c:128] Could not flush connection: Broken pipe
    [backend/session/session.c:375] Failed to close device 1: Broken pipe

It is not a hang, and not a reset either. It is a clean shutdown.
`dbus-monitor` on the system bus caught it about 8 seconds into a session:

    :1.30 -> login1  CanHybridSleep
    :1.30 -> login1  CanHibernate
    :1.30 -> login1  PowerOff(false)
    login1 -> PrepareForShutdown "poweroff"

`:1.30` is `upowerd`, and that call sequence is its critical-battery fallback
chain. The fuel gauge reported `capacity=-1`, UPower read that as 0%, and as
soon as the session drew more than the 500 mA the USB port supplies, the
battery went to `Discharging` and UPower acted. That explains every symptom:
the log stops because shutdown takes the network down first, pstore is stale
because a real power-off loses RAM, the bootloader records
`androidboot.bootreason=usb` because the phone powers back on only because the
cable is in, and the timing varies with when the battery flips to discharging.
Unplugged, the phone would simply have stayed off.

The gauge reads `-1` because MediaTek's Gauge Master 3.0 computes the state of
charge in Android's `fuelgauged` daemon, which talks to the driver over
netlink. Nothing on postmarketOS answers, so nothing ever sets the UI state of
charge. The driver does carry a complete in-kernel copy of the algorithm
(`mtk_battery_recovery.c`: coulomb counting, OCV tables, the battery profile
from the device tree), which it only runs in recovery, where the daemon is
missing too.

Fixed by `fix-mtk-gauge-kernel-algo.patch` (kernel `r26`), which adds
`CONFIG_MTK_GAUGE_KERNEL_ALGO` and routes the five daemon-or-recovery decisions
in `mtk_battery.c` through it. The algorithm reports through the same
`SET_KERNEL_UISOC` command the daemon would use, so nothing above the driver
changes. The profile in the base device tree is Xiaomi's own, with the battery
ID read over ADC. Measured on `r26`:

- `capacity` went from `-1` to `100`, `Full` at 4.41 V, on the cable
- unplugged it counts down, 100 to 99% at about 13 minutes of uptime,
  `Discharging` at 451 mA, and UPower estimates 10.9 h
- after a reboot it resumes from the value kept in the RTC (98%) instead of
  starting over
- the Phosh session with a power-button lock and unlock survives with zero
  `PowerOff` calls, where it used to be powered off within 8 to 60 seconds

**Three wrong turns worth recording.** First, an A/B on the MediaTek idle
manager (`/proc/mtkfb`, `enable_idlemgr:0` and `:1`) looked conclusive — 236 s
alive with it off, dead 54 s after switching it back on — and it was wrong: the
next run, with the idle manager disabled from boot, reset anyway. What settled
it was that `mtk_plane_atomic_disable()` is a `drm_plane_helper_funcs` callback
reachable only from an atomic commit issued by userspace, while the vendor idle
manager never goes through drm_atomic at all.

Second, and worse, the liveness monitor used
`ps aux | grep -c "[p]hoc"` from a shell whose own command line contained the
string `phoc=`, so it counted itself and never reported the compositor as
gone. Half an hour of "the session is up" readings were the monitor watching
its own reflection. `pgrep -x phoc | wc -l` is what it should have been from
the start.


Third, a network-namespace leak looked like the trigger for the power-off: in
two sessions the last kernel line before the log stopped was a
`retire_sysctl_set` warning from `cleanup_net`. The leak is real and is fixed in
kernel `r25` (MediaTek registers `net.optr` in every namespace and never removes
it). But 30 namespaces created and destroyed on their own did not take the
device down. The warning came last only because a glycin sandbox exited while
the system was already shutting down.

A side note on the load average stuck at 15: `khungtaskd` names
`mdrt_thread`, `mivr_thread`, `gauge_timer_thr` and the `wdtk-*` watchdog
kickers. Those are vendor kthreads that sleep in state D by design, and
they account for the load. It is not a hang.

### 10. The screen goes black but the backlight stays on

With blanking working, the panel powered down and the backlight stayed lit
over it. The panel driver never touches the backlight: on Android the lights
HAL writes 0 to `lcd-backlight` when the screen goes off. The driver does try a
`pwm` GPIO on unprepare, but no device tree defines `pwm-gpios`, not even
Xiaomi's overlay, which is the `gpiod_set_value: invalid GPIO` warning on every
blank.

The backlight is only an LED class device, `/sys/class/leds/lcd-backlight`
(0 to 2047), and writing to it does reach the KTD3137 backlight chip. The panel
already announces its own power state on the vendor's DRM blank notifier chain
(`DRM_BLANK_POWERDOWN` / `DRM_BLANK_UNBLANK`), which the touchscreen was meant to
use. Fixed by `fix-mtk-backlight-follow-panel-blank.patch` (kernel `r27`): the
LED driver follows that chain, turns the chip off on blank, restores the level
on unblank, and holds any level written while blanked until the panel is back.

There is still no `/sys/class/backlight` device, so Phosh has no brightness
slider.

### 11. The touchscreen is dead after the first blank

The NT36672C touch controller is part of the display, so it resets with the
panel and needs `nvt_ts_resume()` once the panel is back. Its driver only
listens for framebuffer blank events, which no DRM compositor emits. The
`touchscreen-thunder-wake` service fires one at boot, and after the first blank
nothing ever did again. This was true from kernel `r24` on; nobody had touched
the screen after waking it.

Fixed by `fix-nvt-touch-follow-panel-blank.patch` (kernel `r28`): the touch
driver follows the same DRM blank chain as the backlight. On blank it suspends
the controller; on unblank it resumes it and reloads its firmware (about
120 ms). The burst of checksum errors that used to follow every blank is gone,
since the controller is now put to sleep instead of losing power under the
driver. Until then, `echo 4 > /sys/class/graphics/fb0/blank` followed by
`echo 0` wakes it by hand; the `4` matters, because without a suspend first the
resume is skipped as `Touch is already resume`.

### 12. The interface lags, and the panel lies about its refresh rate

Everything renders on the CPU (see *Session environment*), so each copy the
compositor makes counts. `phoc` sat at one full core. At the automatic scale of
2.67 clients render at 3 and phoc downscales every window on every frame, on a
single thread. Device `r13` ships `/etc/phosh/phoc.ini` with `scale = 3` for
`DSI-1`, so buffers arrive at their final size and phoc only copies them. The
file is read by both the Phosh session and the phrog greeter.

A fractional scale set later in Settings brought the lag back and hung the
interface until a reboot. Device `r14` hides the Display panel: a
`Hidden=true` desktop entry under `/usr/share/xiaomi-thunder`, which
`phosh-session-thunder` puts first in `XDG_DATA_DIRS`. The file that
gnome-control-center ships stays untouched.

The panel driver also declared mode clocks that do not match
`htotal * vtotal * vrefresh`: the 60 Hz mode worked out to about 49 Hz, so
compositors paced frames against the wrong rate. Timing vblanks with
`DRM_IOCTL_WAIT_VBLANK` gives 60.5 Hz. `fix-panel-mode-clock-refresh.patch`
(kernel `r29`) sets each clock from the mode's own timings. The DSI link takes
its rate from a separate field, so only the advertised rate changes.

This makes the interface usable, but it is not 60 fps: that needs the GPU.

### 13. The power menu does nothing

Power off and Restart in the Phosh menu did nothing, and every polkit check
failed with `Process not found`. polkit 127 identifies a subject by its pidfd,
reading the `Pid:` line of `/proc/self/fdinfo/<fd>`. On this kernel fdinfo is
mode 0400, and `polkitd` drops privileges without an `exec`, which leaves the
process non-dumpable. The read fails with `EACCES`, which `strace` shows
directly. Upstream 5.14 changed this (`7bc3fa0172a4`, `1927e498aee1`):
fdinfo access is checked against ptrace read access instead of the file mode.
`backport-procfs-fdinfo-ptrace-read.patch` (kernel `r30`) backports that change.
`pkcheck --action-id org.freedesktop.login1.power-off` now authorizes the
greeter's phoc, and Power off and Restart work from the Phosh menu.

### 14. The battery never reaches 100%

With the gauge algorithm in the kernel (blocker 9), the level stopped at 99%
on the charger. The charger does fire its charge-full event (`battery full!`),
but the in-kernel algorithm has no handler for `FG_INTR_CHR_FULL`. It only
raises the displayed level on coulomb counter steps, and a full battery draws
too little current to take the last one. Android's `fuelgauged` handles the
event; the in-kernel copy never had to, because it only ran in recovery.

`fix-mtk-gauge-charge-full-uisoc.patch` (kernel `r31`) reports 100% on charge
full while the charger is present. The counter-based level is left as it is.
On discharge, `fgr_bat_int2_l_handler()` already scales its steps by
`ui_soc / soc`, so the two levels converge again.

### 15. An automatic update breaks the greeter

Once polkit worked (blocker 13), GNOME Software could run
`apk-polkit-rs`, and it applied an automatic update. glib and bubblewrap are
rebuilt for this kernel (blockers 4 and 5) and exist in no repository. apk
"downgraded" them to the Alpine builds. With the Alpine glib,
`waitid(P_PIDFD)` fails with `EINVAL` again. The on-screen keyboard dies at
start, and gnome-session gives up on the greeter:

    Unrecoverable failure in required component sm.puri.OSK0.desktop

All that is left on screen is a spinner. The greeter's stderr goes to `tty7`,
and `/dev/vcs7` is the quickest way to read it.

Device `r15` depends on `glib>=2.90.0-r2` and `bubblewrap>=0.13.0-r1`, so the
solver can no longer swap them. It also ships a dconf default,
`org.gnome.software download-updates=false`, that stops GNOME Software from
updating by itself. Manual updates still work.

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
- `seatd` in the `boot` runlevel. greetd does not declare it, and while the
  device booted to Weston it only came up as a dependency of the Weston
  service. With Weston out of the boot, greetd crashed at boot and left the
  screen black. The `boot` runlevel finishes before `default`, where greetd
  runs, so the order no longer depends on anything.
- A short delay before the session takes the seat. Without it the greeter's
  phoc has not released `seat0` yet and seatd drops the new connection.
- pixman and cairo: the Mali-G57 has no free userspace driver on this kernel,
  so everything renders in software.

## Still open

**The polkit agent.** phosh used to report

    Auth agent failed to register: Cannot determine session the caller is in

with the session correctly registered in elogind. It is most likely the same
fdinfo `EACCES` as blocker 13: polkitd could not resolve the calling process at
all. Since kernel `r30` the power menu works; whether the agent now registers
has still to be checked in a live session.

**GPU acceleration.** The Mali-G57 runs only under the vendor's kbase driver
(`/dev/mali0`), with no free userspace for it on this kernel.

**Brightness.** There is no `/sys/class/backlight` device, so Phosh has no
brightness slider.

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
