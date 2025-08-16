__version__ = "0.1.0"


from collections import defaultdict
from fnmatch import fnmatchcase
from pathlib import Path
from platform import uname
from re import search

from zenlib.logging import loggify
from zenlib.util import colorize as c_

from .kmod_enumerators import KmodEnumerators
from .kmod_errors import UnknownAliasError, UnknownKernelVersionError

# Modules that are built-in and do not require a kmod
_BUILTIN_NO_KMOD = ["pcieport"]


@loggify
class KmodDB(KmodEnumerators):
    """A class to manage kernel module metadata.
    Can be initailized with a kernel version, or uses the current kernel version.
    """

    @staticmethod
    def _get_kernel_versions() -> list[str]:
        """Returns a list of available kernel versions from /lib/modules."""
        return [d.name for d in Path("/lib/modules").iterdir() if d.is_dir() and d.exists()]

    @staticmethod
    def get_alias_keys(alias_str) -> dict:
        """Gets key value pairs from a kernel module alias string.
        example alias string:
            cpu:type:x86,ven0000fam0006mod002A:feature:* for module: rapl
            returns a dictionary with the keys:
                {"type": "x86,ven0000fam0006mod002A", "feature": "*"}
        """
        parts = alias_str.split(":")
        if len(parts) % 2 != 0:
            raise ValueError("Invalid alias string format, expected key:value pairs separated by ':'")
        keys = {}

        for i in range(0, len(parts), 2):
            key = parts[i].strip()
            value = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if key in keys:
                raise ValueError(f"Duplicate key found in alias string: {key}")
            keys[key] = value

        return keys

    def __init__(self, kernel_version: str = None, *args, **kwargs):
        self.kernel_version = kernel_version or uname().release
        self.builtin = set()  # Set to store builtin modules
        self.aliases = defaultdict(list)  # Dictionary where keys are module names and values are lists of aliases
        self.cpu = defaultdict(list)  # Dictionary where keys are module names and values are lists of CPU aliases
        self.dmi = defaultdict(list)  # Dictionary where keys are module names and values are lists of DMI aliases
        self.of = defaultdict(
            list
        )  # Dictionary for Open Firmware aliases, keys are module names, values are lists of matchers
        self.virtio = defaultdict(
            list
        )  # Dictionary for virtio aliases, keys are module names, values are lists of dicts of matcher keys and values
        self.ignored_busses = [
            "auxiliary",
            "cxl",
            "dax",
            "dfl",
            "dsa_tag",
            "eisa",
            "hdaudio",
            "hid",
            "idxd",
            "ieee1394",
            "input",
            "ip_set_bitmap",
            "ip_set_hash",
            "ip_set_list",
            "ishtp",
            "ledtrig",
            "mdio",
            "mei",
            "nd",
            "pcmcia",
            "sdio",
            "sdw",
            "serio",
            "ssb",
            "tbsvc",
            "typec",
            "pnp",
            "vfio_pci",
            "wmi",
        ]

        # List of busses that are considered plain and do not require special handling
        self.plain_busses = ["acpi", "devname", "i2c", "isa", "mhi", "usb", "scsi", "spi", "pci", "platform", "xen"]

        for bus in self.plain_busses:
            if getattr(self, bus, None) is not None:
                self.logger.warning(
                    f"Bus {c_(bus, 'yellow')} is already defined as an attribute, this may cause issues."
                )
            # Initialize each bus in the dictionary with a defaultdict of lists
            setattr(self, bus, defaultdict(list))

        self.get_builtin_module_info()  # Load builtin module info
        self.get_module_aliases()  # Process module alias information

    @property
    def kernel_version(self) -> str:
        """Returns the kernel version."""
        return self._kernel_version

    @kernel_version.setter
    def kernel_version(self, value: str):
        """Sets the kernel version, checking it's a valid version."""
        if value not in self._get_kernel_versions():
            raise UnknownKernelVersionError(
                f"Unknown kernel version: {value}. Available versions: {', '.join(self._get_kernel_versions())}"
            )
        self._kernel_version = value

    @property
    def modules_builtin_modinfo(self) -> Path:
        """Returns the path to the modules.builtin.modinfo file for the current kernel version."""
        builtin_modinfo = Path("/lib/modules") / self.kernel_version / "modules.builtin.modinfo"
        if not builtin_modinfo.exists():
            raise FileNotFoundError(
                f"[{c_(self.kernel_version, 'magenta')}] Builtin modinfo file does not exist: {c_(builtin_modinfo, 'red', bold=True)}"
            )
        return builtin_modinfo

    @property
    def modules_alias(self) -> Path:
        """Returns the path to the modules.alias file for the current kernel version."""
        alias_file = Path("/lib/modules") / self.kernel_version / "modules.alias"
        if not alias_file.exists():
            raise FileNotFoundError(
                f"[{c_(self.kernel_version, 'magenta')}] Kernel module alias file does not exist: {c_(alias_file, 'red', bold=True)}"
            )
        return alias_file

    def resolve_module_alias(self, alias: str, bus=None) -> str:
        """Resolves a kernel module alias to a module name. If the alias is not found, raises an UnknownAliasError."""
        for bus_name in self.plain_busses:
            if alias.startswith(bus_name + ":"):
                if bus and bus != bus_name:
                    self.logger.warning(
                        f"Alias {c_(alias, 'blue')} is for bus {c_(bus_name, 'yellow')}, but bus {c_(bus, 'yellow')} was requested."
                    )
                bus = bus_name
                alias = alias.removeprefix(bus_name + ":").strip()
                break

        if bus:
            if bus not in self.plain_busses:
                self.logger.warning(
                    f"Bus {c_(bus, 'yellow')} is not a plain bus, alias resolution may not work as expected."
                )
            else:
                self.logger.debug(f"Resolving alias {c_(alias, 'blue')} on bus {c_(bus, 'yellow')}")
                for module, matchers in getattr(self, bus).items():
                    for matcher in matchers:
                        if fnmatchcase(alias, matcher):
                            self.logger.debug(f"Resolved alias {c_(alias, 'blue')} to module {c_(module, 'cyan')}")
                            return module

        for module, aliases in self.aliases.items():
            for a in aliases:
                if fnmatchcase(alias, a):
                    print(a)
                    self.logger.debug(f"Resolved alias {c_(alias, 'blue')} to module {c_(module, 'cyan')}")
                    return module


        if module := self.resolve_of_alias(alias):
            return module

        if bus != "platform" and (platform_alias := self.resolve_module_alias(alias, bus="platform")):
            self.logger.debug(f"Resolved platform alias {c_(alias, 'blue')} to module {c_(platform_alias, 'cyan')}")
            return platform_alias

        raise UnknownAliasError(f"Kernel module alias not found: {c_(alias, 'red', bold=True)}")


    def resolve_of_alias(self, alias: str) -> str:
        """Resolves an Open Firmware alias to a kernel module name."""
        alias = alias.removeprefix("of:").strip()
        for module, matchers in self.of.items():
            for matcher in matchers:
                # First try to match the alias directly
                if fnmatchcase(alias, matcher):
                    self.logger.info(f"Resolved OF alias {c_(alias, 'blue')} to module {c_(module, 'cyan')}")
                    return module

                # If that fails, try to match without the vendor ID
                if "," not in alias and "," in matcher:
                    matcher_with_vendor = matcher.split(",")[-1]
                    if fnmatchcase(alias, matcher_with_vendor):
                        self.logger.info(
                            f"Resolved OF alias {c_(alias, 'blue')} to module {c_(module, 'magenta')}, ignoring vendor ID"
                        )
                        return module
        raise UnknownAliasError(f"Open Firmware alias not found: {c_(alias, 'red', bold=True)}")

    def resolve_pci_alias(self, modalias: str) -> str:
        """Resolves a PCI modalias to a kernel module name."""
        modalias = modalias.removeprefix("pci:").strip()
        for module, matchers in self.pci.items():
            for matcher in matchers:
                if fnmatchcase(modalias, matcher):
                    self.logger.info(f"Resolved PCI modalias {c_(modalias, 'blue')} to module {c_(module, 'cyan')}")
                    return module


    def get_builtin_module_info(self) -> None:
        """Gets the kernel module aliases from /lib/modules/<kernel_version>/modules.builtin.modinfo.
        populates self.aliases with the module aliases found in the file.
        """
        for line in self.modules_builtin_modinfo.read_bytes().split(b"\x00"):
            """ Lines are in the format <name>.<parameter>=<value>"""
            line = line.decode("utf-8", errors="ignore").strip()
            if not line or "." not in line or "=" not in line:
                continue
            name, parameter = line.split(".", 1)
            parameter, value = parameter.split("=", 1)

            if parameter != "alias":
                continue

            # simulate the alias processing as in modules.alias
            self.process_alias(f"{value.strip()} {name.strip()}")
            # add the module to the builtin set
            self.builtin.add(name.strip())

    def get_module_aliases(self):
        """Processes the kernel module aliases from /lib/modules/<kernel_version>/modules.alias."""
        for line in self.modules_alias.read_text().splitlines():
            """ Lines are in the format:
                alias <bus>:<alias> <module>
                """
            if not line.startswith("alias "):
                self.logger.debug(f"Skipping non-alias line: {line}")
                continue
            self.process_alias(line)

    def process_alias(self, alias_str: str) -> None:
        """Processes a single kernel module alias string ."""
        alias_str = alias_str.removeprefix("alias ").strip()
        alias_str, module = alias_str.split(" ", 1)

        try:  # Try to the the bus for the alias, if no bus is present, it's a plain alias
            bus, alias = alias_str.split(":", 1)
        except ValueError:
            bus = None
            self.aliases[module].append(alias_str.strip())
            return self.logger.debug(
                f"[{c_(module, 'magenta')}] Processing plain alias: {c_(alias_str.strip(), 'blue')}"
            )

        match bus:
            case bus if bus in self.ignored_busses or bus.replace("*", "") in self.ignored_busses:
                self.logger.debug(
                    f"Ignoring alias {c_(alias_str, 'blue')} for module {c_(module, 'magenta')} on bus {c_(bus, 'yellow')}"
                )
            case bus if bus in self.plain_busses or bus.replace("*", "") in self.plain_busses:
                self.process_simple_alias(alias, module, bus)
            case "acpi" | "acpi*":
                self._process_acpi_alias(alias, module)
            case "cpu":
                self._process_cpu_alias(alias, module)
            case "dmi" | "dmi*":
                self._process_dmi_alias(alias, module)
            case "of":
                self._process_of_alias(alias, module)
            case "virtio":
                self._process_virtio_alias(alias, module)
            case _:
                self.logger.error(f"Unknown bus type: {bus} in alias: {alias_str} for module: {module}")

    def process_simple_alias(self, alias: str, module: str, bus: str = None) -> None:
        """Adds a simple alias to the aliases dictionary for the given module.
        If the module is defined in self.simple_busses, it will be added to the attribute for that bus.
        """
        self.logger.debug(f"[{c_(module, 'magenta')}]({c_(bus or '-', 'yellow')}) Processing alias: {c_(alias, 'blue')}")
        if bus and bus in self.plain_busses:
            getattr(self, bus)[module].append(alias)
            return

        self.aliases[module].append(alias)

    def _process_cpu_alias(self, alias: str, module) -> None:
        """Processes CPU aliases from the kernel module aliases."""
        self.logger.debug(f"[{c_(module, 'magenta')}] Processing {c_('CPU', 'yellow')} alias: {c_(alias, 'blue')}")
        cpuinfo = self.get_alias_keys(alias)
        cpu_type = cpuinfo.pop("type")
        features = cpuinfo.pop("feature")
        if cpu_type == "*":
            if features == "*":
                self.aliases[module].append(alias)
                self.logger.info(f"Adding generic CPU alias: {alias} for module: {module}")
                return
            arch = "*"
            info = "*"
        else:
            arch, info = cpu_type.split(",", 1)
        match_info = {"arch": arch, "info": info, "features": features}
        self.cpu[module].append(match_info)

    def _process_dmi_alias(self, alias: str, module: str) -> None:
        """Processes DMI aliases, which are used to match hardware based on DMI information."""
        self.logger.debug(f"[{c_(module, 'magenta')}] Processing {c_('DMI', 'yellow')} alias: {c_(alias, 'blue')}")
        dmi_parts = [part for part in alias.split(":") if part]  # Split by ':' and remove empty parts
        self.dmi[module].append(dmi_parts)

    def _process_of_alias(self, alias: str, module: str) -> None:
        """Processes Open Firmware (OF) aliases from the kernel module aliases."""
        self.logger.debug(f"[{c_(module, 'magenta')}] Processing {c_('Open Firmware', 'yellow')} alias: {c_(alias, 'blue')}")

        if not alias.startswith("N*T*C"):
            self.logger.warning(f"OF alias {c_(alias, 'red')} does not start with  N*T*C, skipping.")
            return

        if alias.endswith("C*"):
            alias = alias.removesuffix("C*") + "*"  # Remove the C* suffix if present, but keep the wildcard

        matcher = alias.removeprefix("N*T*C")  # Remove the N*T*C prefix
        self.of[module].append(matcher)  # Store the matcher in the DMI aliases

    def _process_virtio_alias(self, alias: str, module: str) -> None:
        """Processes virtio aliases from the kernel module aliases.

        The alias line is in the format: d<device id>v<vendorid>
        """
        self.logger.debug(f"[{c_(module, 'magenta')}] Processing {c_('virtio', 'yellow')} alias: {c_(alias, 'blue')}")
        re_str = r"d(?P<device_id>[0-9a-fA-F\*]+)v(?P<vendor_id>[0-9a-fA-F\*]*)"
        match = search(re_str, alias)
        if match_info := {"device_id": match.group("device_id"), "vendor_id": match.group("vendor_id")}:
            self.virtio[module].append(match_info)
