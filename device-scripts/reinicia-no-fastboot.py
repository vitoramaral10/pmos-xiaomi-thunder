#!/usr/bin/env python3
"""Reinicia o aparelho direto no fastboot, sem apertar botao nenhum.

POR QUE ISTO EXISTE
-------------------
"reboot bootloader" nao funciona neste sistema, e a razao nao e' o kernel.

O /bin/reboot do postmarketOS e' um link para o busybox, e o busybox ignora
qualquer argumento: ele chama sempre reboot(RB_AUTOBOOT).  A palavra
"bootloader" e' silenciosamente descartada -- sem erro, sem aviso.  O aparelho
reinicia normalmente e volta para o sistema, e fica parecendo que o bootloader
do MediaTek nao aceita entrada remota.

Aceita.  O kernel deste aparelho tem os dois ganchos necessarios, conferidos em
/proc/kallsyms:

    rtc_mark_fast       <- grava a marca de fast boot no RTC
    do_kernel_restart   <- repassa a string de comando aos handlers

O que faltava era so' alguem passar a string.  Isso exige a chamada de sistema
reboot() na forma de quatro argumentos, com LINUX_REBOOT_CMD_RESTART2 e um
ponteiro para o texto -- e nenhum wrapper de libc expoe essa forma: a reboot()
da musl e da glibc recebe um argumento so'.  Dai a syscall crua.

E por isso tambem que "echo b > /proc/sysrq-trigger" nunca serviria: o sysrq
chama emergency_restart(), que pula os handlers -- e portanto pula o
rtc_mark_fast.  Reinicia, mas sempre no sistema.

USO
    reinicia-no-fastboot.py            -> fastboot
    reinicia-no-fastboot.py recovery   -> recovery
"""

import ctypes
import os
import sys

# include/uapi/linux/reboot.h
MAGIC1 = 0xFEE1DEAD
MAGIC2 = 672274793          # 0x28121969
CMD_RESTART2 = 0xA1B2C3D4

# arch/arm64 usa a tabela generica: __NR_reboot = 142
NR_REBOOT = 142


def main():
    alvo = sys.argv[1] if len(sys.argv) > 1 else "bootloader"

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.syscall.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_uint,
                             ctypes.c_uint, ctypes.c_char_p]

    print("sincronizando os discos")
    os.sync()

    print("reiniciando em '%s'" % alvo)
    r = libc.syscall(NR_REBOOT, MAGIC1, MAGIC2, CMD_RESTART2,
                     alvo.encode())
    # Se chegou aqui, nao reiniciou.
    err = ctypes.get_errno()
    print("a chamada voltou: %d, errno %d (%s)" % (r, err, os.strerror(err)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
