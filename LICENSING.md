# Licensing

This repository mixes material under different licenses. Each file keeps the
license it came with.

| Path | License | Origin |
|---|---|---|
| `pmaports/linux-xiaomi-thunder/*.patch`, `*.diff`, `config-*` | GPL-2.0 | derived from Linux kernel source |
| `pmaports/linux-xiaomi-thunder/mtk-connectivity-gen4m-mt6833-2.tar.gz` | GPL-2.0 | MediaTek/Xiaomi kernel source, assembled from public vendor trees (657 files, no binaries). The `bt_drv/` directory comes from `mt6781-devs/android_kernel_xiaomi_mt6781` @ `lineage-23.2`, path `drivers/misc/mediatek/connectivity/bt/mt66xx/wmt/`; its `Makefile` was written for this port |
| `pmaports/linux-xiaomi-thunder/connectivity-Makefile-mt6833` | GPL-2.0 | derived from `MiCode/Xiaomi_Kernel_OpenSource` |
| `pmaports/*/APKBUILD` and packaging files | GPL-3.0 | follows postmarketOS pmaports |
| `device-scripts/`, `tools/`, `docs/` | GPL-3.0 | written for this port |

The kernel source this port builds against is
[`MiCode/Xiaomi_Kernel_OpenSource`](https://github.com/MiCode/Xiaomi_Kernel_OpenSource),
commit `a40ceab8943703f33e935cb0b86d0f69aa2044dd`, published by Xiaomi under
GPL-2.0.

**No proprietary firmware is distributed here.** See
[docs/vendor-firmware.md](docs/vendor-firmware.md).
