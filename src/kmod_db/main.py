#!/usr/bin/python3

from zenlib.util import get_kwargs

from .kmod_db import KmodDB

def main():
    arguments = [{"flags": ["--acpi"], "help": "Detect ACPI devices", "action": "store_true"},
                 {"flags": ["--pci"], "help": "Detect PCI devices", "action": "store_true"},
                 {"flags": ["--dmi"], "help": "Detect DMI devices", "action": "store_true"},
                 ]

    kwargs = get_kwargs("kmod_db", "kernel module database", arguments=arguments)
    acpi = kwargs.pop("acpi", False)
    pci = kwargs.pop("pci", False)
    dmi = kwargs.pop("dmi", False)

    db = KmodDB(**kwargs)

    if acpi:
        print(f"ACPI Kmods: {db.detect_acpi_kmods()}")
    if pci:
        print(f"PCI Kmods: {db.detect_pci_kmods()}")
    if dmi:
        print(f"DMI Kmods: {db.detect_dmi_kmods()}")

