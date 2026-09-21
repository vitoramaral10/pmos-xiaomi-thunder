#!/usr/bin/env python3
"""Verifica os artefatos do port postmarketOS xiaomi-thunder antes de qualquer flash.

Nao grava nada, nao fala com o celular. Le o APK do kernel, o boot.img exportado
e o rootfs, e confere cada campo contra o deviceinfo e contra o boot de fabrica.
"""
import hashlib
import os
import re
import struct
import subprocess
import sys
import tarfile

BASE = os.environ.get("PMOS_WORK", os.path.expanduser("~/pmos-work"))
DEVICEINFO = f"{BASE}/pmaports/device/downstream/device-xiaomi-thunder/deviceinfo"
STOCK_DTB = f"{BASE}/stock-backup/dtb.extracted.0"

falhas, avisos = [], []

def ok(msg):    print(f"  [OK]    {msg}")
def falha(msg): falhas.append(msg); print(f"  [FALHA] {msg}")
def aviso(msg): avisos.append(msg); print(f"  [AVISO] {msg}")
def titulo(msg): print(f"\n=== {msg} ===")

def ler_deviceinfo():
    di = {}
    with open(DEVICEINFO) as fh:
        for linha in fh:
            linha = linha.strip()
            if linha.startswith("deviceinfo_") and "=" in linha:
                chave, _, valor = linha.partition("=")
                di[chave] = valor.strip().strip('"')
    return di

def achar(diretorio, sufixos):
    if not os.path.isdir(diretorio):
        return []
    return sorted(
        os.path.join(diretorio, n)
        for n in os.listdir(diretorio)
        if n.endswith(sufixos)
    )

def props_dtb(caminho):
    """model, compatible e contagem de nos de um DTB, via dtc."""
    try:
        dts = subprocess.run(
            ["dtc", "-I", "dtb", "-O", "dts", caminho],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as erro:
        return None, None, None, str(erro)
    modelo = compat = None
    for linha in dts.splitlines()[:40]:
        s = linha.strip()
        if s.startswith("model =") and modelo is None:
            modelo = s.split("=", 1)[1].strip(' ;"')
        if s.startswith("compatible =") and compat is None:
            compat = s.split("=", 1)[1].strip(' ;"')
    return modelo, compat, dts.count("{"), None

def verificar_apk(di):
    titulo("1. APK do kernel (r9)")
    todos = achar(f"{BASE}/work/packages/edge/aarch64", (".apk",))
    apks = [a for a in todos if "linux-xiaomi-thunder" in os.path.basename(a)]
    if not apks:
        falha("nenhum APK linux-xiaomi-thunder encontrado")
        return None
    apk = max(apks, key=lambda a: int(
        re.search(r"-r(\d+)\.apk$", a).group(1)))
    ok(f"{os.path.basename(apk)} ({os.path.getsize(apk)/1e6:.1f} MB)")

    esperado = f"boot/dtbs/{di['deviceinfo_dtb']}.dtb"
    with tarfile.open(apk, "r:gz") as tf:
        nomes = tf.getnames()
        if "boot/vmlinuz" in nomes:
            ok("contem boot/vmlinuz")
        else:
            falha("boot/vmlinuz ausente no APK")
        if esperado in nomes:
            ok(f"contem {esperado}  <- era a falha do r8")
            membro = tf.extractfile(esperado)
            destino = "/tmp/thunder-dtb-do-apk.dtb"
            with open(destino, "wb") as saida:
                saida.write(membro.read())
            return destino
        falha(f"{esperado} ausente no APK; presentes: "
              f"{[n for n in nomes if 'dtb' in n][:5]}")
    return None

def verificar_dtb(dtb_apk):
    titulo("2. DTB gerado x DTB de fabrica")
    if not dtb_apk:
        falha("sem DTB do APK para comparar")
        return
    m1, c1, n1, erro = props_dtb(dtb_apk)
    if erro:
        falha(f"nao foi possivel ler o DTB gerado: {erro}")
        return
    ok(f"gerado:  model={m1!r} compatible={c1!r} nos={n1} "
       f"({os.path.getsize(dtb_apk)} B)")
    if not os.path.exists(STOCK_DTB):
        aviso("DTB de fabrica ausente; comparacao pulada")
        return
    m2, c2, n2, _ = props_dtb(STOCK_DTB)
    ok(f"fabrica: model={m2!r} compatible={c2!r} nos={n2} "
       f"({os.path.getsize(STOCK_DTB)} B)")
    if m1 == m2 and c1 == c2:
        ok("model e compatible batem com o boot de fabrica")
    else:
        falha("model/compatible DIVERGEM do boot de fabrica")
    if n1 == n2:
        ok(f"contagem de nos identica ({n1})")
    else:
        aviso(f"contagem de nos difere: gerado={n1} fabrica={n2}")

def verificar_bootimg(di):
    titulo("3. boot.img exportado")
    candidatos = []
    for d in (f"{BASE}/work/chroot_native/tmp/export",
              "/tmp/postmarketOS-export",
              f"{BASE}/work/chroot_rootfs_xiaomi-thunder/boot"):
        candidatos += achar(d, (".img",))
    boot = next((c for c in candidatos
                 if os.path.basename(c).startswith("boot")), None)
    if not boot:
        falha(f"boot.img nao encontrado; vistos: "
              f"{[os.path.basename(c) for c in candidatos]}")
        return
    print(f"  arquivo: {boot} ({os.path.getsize(boot)/1e6:.2f} MB)")

    with open(boot, "rb") as fh:
        cab = fh.read(1660)
    if cab[:8] != b"ANDROID!":
        falha(f"magic errado: {cab[:8]!r} (esperado b'ANDROID!')")
        return
    ok("magic ANDROID! presente")

    (ksz, kaddr, rsz, raddr, ssz, saddr,
     tags, pagesize, hdrv) = struct.unpack("<9I", cab[8:44])
    cmdline = cab[64:64 + 512].split(b"\0")[0].decode(errors="replace")

    def confere(rotulo, lido, chave, fmt=hex):
        esperado = di.get(chave)
        if esperado is None:
            aviso(f"{rotulo}: {fmt(lido)} (sem referencia no deviceinfo)")
            return
        alvo = int(esperado, 0)
        if lido == alvo:
            ok(f"{rotulo} = {fmt(lido)}")
        else:
            falha(f"{rotulo} = {fmt(lido)}, deviceinfo diz {fmt(alvo)}")

    base = int(di.get("deviceinfo_flash_offset_base", "0"), 0)
    confere("header_version", hdrv, "deviceinfo_header_version", str)
    confere("page_size", pagesize, "deviceinfo_flash_pagesize", str)
    confere("kernel_addr", kaddr - base, "deviceinfo_flash_offset_kernel")
    confere("ramdisk_addr", raddr - base, "deviceinfo_flash_offset_ramdisk")
    confere("tags_addr", tags - base, "deviceinfo_flash_offset_tags")

    ok(f"kernel  = {ksz/1e6:.2f} MB")
    ok(f"ramdisk = {rsz/1e6:.2f} MB")
    if ksz == 0:
        falha("kernel_size = 0")
    if rsz == 0:
        falha("ramdisk_size = 0 (initramfs vazio)")

    esperada = di.get("deviceinfo_kernel_cmdline", "")
    if cmdline.strip() == esperada.strip():
        ok(f"cmdline confere: {cmdline!r}")
    else:
        aviso(f"cmdline = {cmdline!r}; deviceinfo = {esperada!r}")

    if hdrv == 2:
        dtb_sz, dtb_addr = struct.unpack("<IQ", cab[1648:1660])
        if dtb_sz > 0:
            ok(f"DTB embarcado no boot.img: {dtb_sz} B @ {hex(dtb_addr)}")
        else:
            falha("header v2 sem DTB embarcado (dtb_size = 0)")

def verificar_rootfs(di):
    titulo("4. rootfs exportado")
    imgs = []
    for d in (f"{BASE}/work/chroot_native/tmp/export",
              "/tmp/postmarketOS-export"):
        imgs += [c for c in achar(d, (".img",))
                 if not os.path.basename(c).startswith("boot")]
    if not imgs:
        falha("nenhuma imagem de rootfs encontrada")
        return
    for img in imgs:
        tam = os.path.getsize(img)
        ok(f"{os.path.basename(img)}: {tam/1e9:.2f} GB")
        tipo = subprocess.run(["file", "-b", img],
                              capture_output=True, text=True).stdout.strip()
        print(f"          tipo: {tipo[:100]}")
    print(f"\n  particao-alvo do rootfs (deviceinfo): "
          f"{di.get('deviceinfo_flash_fastboot_partition_rootfs')}")
    print(f"  particao-alvo do kernel  (deviceinfo): "
          f"{di.get('deviceinfo_flash_fastboot_partition_kernel')}")
    aviso("confira o tamanho da particao userdata no aparelho antes de gravar")

def main():
    print("Verificacao de artefatos — postmarketOS xiaomi-thunder")
    print("Somente leitura. Nenhum dado e enviado ao celular.")
    di = ler_deviceinfo()
    dtb = verificar_apk(di)
    verificar_dtb(dtb)
    verificar_bootimg(di)
    verificar_rootfs(di)

    titulo("Resultado")
    print(f"  falhas: {len(falhas)}   avisos: {len(avisos)}")
    for f in falhas:
        print(f"    FALHA: {f}")
    for a in avisos:
        print(f"    aviso: {a}")
    if falhas:
        print("\n  NAO GRAVE NADA NO CELULAR.")
        return 1
    print("\n  Artefatos consistentes. Flash continua exigindo sua autorizacao.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
