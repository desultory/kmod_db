__version__ = "0.1.0"


from fnmatch import fnmatchcase
from pathlib import Path

from zenlib.util import colorize as c_

from .kmod_errors import UnknownAliasError

# Modules that are built-in and do not require a kmod
_BUILTIN_NO_KMOD = ["pcieport"]


class KmodEnumerators:
    """A mixin class to enumerate kernel modules and their metadata."""

    def detect_acpi_kmods(self) -> set[str]:
        """Returns a list of kernel modules which match current ACPI information."""
        acpi_devices = Path("/sys/bus/acpi/devices")

        if not acpi_devices.exists():
            raise FileNotFoundError("ACPI devices directory not found: /sys/bus/acpi/devices")

        modules = set()
        modaliases = set()
        for device in acpi_devices.iterdir():
            modalias_file = device / "modalias"
            if not modalias_file.exists():
                continue
            modaliases.add(modalias_file.read_text().strip().removeprefix("acpi:"))

        for module, matchers in self.acpi.items():
            for matcher in matchers:
                for modalias in modaliases:
                    if fnmatchcase(modalias, matcher):
                        self.logger.debug(f"Module {c_(module, 'magenta')} matches ACPI device {c_(modalias, 'cyan')}")
                        modules.add(module)
        return modules

    def detect_pci_kmods(self) -> set[str]:
        """Detects kernel modules that match the current PCI devices."""
        pci_devices = Path("/sys/bus/pci/devices")

        if not pci_devices.exists():
            raise FileNotFoundError("PCI devices directory not found: /sys/bus/pci/devices")

        modaliases = set()
        modules = set()
        for device in pci_devices.iterdir():
            modalias_file = device / "modalias"
            if not modalias_file.exists():
                continue
            modaliases.add(modalias_file.read_text().strip().removeprefix("pci:"))

        # Use he define module and matcher sets
        for module, matchers in self.pci.items():
            # Try each matcher against all of the modaliases
            for matcher in matchers:
                # Iterate over each modalias with the assocaited
                for modalias in modaliases:
                    if fnmatchcase(modalias, matcher):
                        self.logger.debug(f"Module {c_(module, 'magenta')} matches PCI device {c_(modalias, 'cyan')}")
                        modules.add(module)

        return modules

    def detect_dmi_kmods(self, dmi_str: str = None) -> set[str]:
        """Resolves DMI aliases to kernel modules based on the provided DMI string.
        If no DMI string is provided, it uses the system's DMI information.
        Returns a list of module names that match the DMI information.
        """
        if not dmi_str:
            try:
                dmi_str = Path("/sys/class/dmi/id/modalias").read_text().strip()
            except FileNotFoundError:
                raise FileNotFoundError("/sys/class/dmi/id/modalias file not found. Please provide a DMI string.")

        dmi_str = dmi_str.removeprefix("dmi:").strip()  # Remove the 'dmi:' prefix if present
        dmi_parts = [part for part in dmi_str.split(":") if part]  # Split by ':' and remove empty parts

        matching_modules = set()
        for module, matchers in self.dmi.items():
            for matcher in matchers:
                for n, part in enumerate(matcher):
                    if part == "*":
                        if n > len(dmi_parts) - 1:
                            break  # Wildcard matcher but dmi string is not long enough
                    if not fnmatchcase(dmi_parts[n], part):
                        break
                else:  # If we didn't break, all matchers matched
                    matching_modules.add(module)
                    self.logger.debug(f"Module {c_(module, 'magenta')} matches DMI string {c_(dmi_str, 'cyan')}")
                    break

        return matching_modules

    def get_blkdev_kmods(self, blkdev: str) -> set[str]:
        """Returns a set of kernel modules that match the given block device name."""
        blkdev_path = Path(f"/sys/class/block/{blkdev}")
        if not blkdev_path.exists():
            raise FileNotFoundError(f"Block device modalias file not found: {blkdev_path}")

        modules = set()
        dev_path = blkdev_path.resolve()
        while True:
            driver = dev_path / "driver"
            driver_name = None
            modalias = dev_path / "modalias"
            if driver.exists():
                driver_name = driver.readlink().name  # Read the symlink to get the driver name
                if driver_name in self.builtin or driver_name in _BUILTIN_NO_KMOD:
                    self.logger.debug(f"[{dev_path}]({c_(driver_name, 'magenta')}) is a builtin module, skipping.")
                else:
                    self.logger.debug(f"[{dev_path}] Found driver symlink: {driver_name}")
                    driver_module = driver.resolve() / "module"
                    if driver_module.exists():
                        modules.add(driver_module.readlink().name)  # Read the symlink to get the module name

            if modalias.exists():  # If the driver name is not available, try to read the modalias
                modalias_text = modalias.read_text().strip()
                try:
                    module = self.resolve_module_alias(modalias_text)
                    modules.add(module)
                except UnknownAliasError:
                    if driver_name in self.builtin:
                        self.logger.debug(
                            f"[{dev_path}]({c_(driver_name, 'magenta')}) Unknown alias for builtin module: {modalias_text}"
                        )
                    elif driver_name in _BUILTIN_NO_KMOD:
                        self.logger.debug(
                            f"[{dev_path}]({c_(driver_name, 'magenta')}) No kmod required for builtin module: {modalias_text}"
                        )
                    else:
                        try:
                            module = self.resolve_module_alias(driver_name)
                            modules.add(module)
                        except UnknownAliasError:
                            self.logger.warning(
                                f"[{dev_path}]({c_(driver_name, 'magenta')}) Unknown alias: {modalias_text}"
                            )

            parent = dev_path.parent
            if parent == dev_path or not parent.exists():
                break

            dev_path = parent

        return modules
