# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import platform
import re
import shlex
import sys


def is_windows():
    """Returns true if the system we are currently running on
    is a Windows system"""
    return sys.platform.startswith("win")


def get_linux_type():
    try:
        with open("/etc/os-release") as f:
            data = f.read()
    except EnvironmentError:
        return (None, None, None)

    os_vars = {}
    for line in data.splitlines():
        parts = line.split("=", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        value_parts = shlex.split(parts[1].strip())
        if not value_parts:
            value = ""
        else:
            value = value_parts[0]
        os_vars[key] = value

    name = os_vars.get("NAME")
    if name:
        name = name.lower()
        name = re.sub("linux", "", name)
        name = name.strip().replace(" ", "_")

    version_id = os_vars.get("VERSION_ID")
    if version_id:
        version_id = version_id.lower()

    return "linux", name, version_id


# Ideally we'd use a common library like `psutil` to read system information,
# but getdeps can't take third-party dependencies.


def _get_available_ram_linux():
    # TODO: Ideally, this function would inspect the current cgroup for any
    # limits, rather than solely relying on system RAM.
    with open("/proc/meminfo") as f:
        for line in f:
            try:
                key, value = line.split(":", 1)
            except ValueError:
                continue
            suffix = " kB\n"
            if key == "MemAvailable" and value.endswith(suffix):
                value = value[: -len(suffix)]
                try:
                    return int(value) // 1024
                except ValueError:
                    continue

    raise NotImplementedError("/proc/meminfo had no valid MemAvailable")


def _get_available_ram_macos() -> int:
    import ctypes.util

    libc = ctypes.CDLL(ctypes.util.find_library("libc"), use_errno=True)
    sysctlbyname = libc.sysctlbyname
    sysctlbyname.restype = ctypes.c_int
    sysctlbyname.argtypes = [
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    # TODO: There may be some way to approximate an availability
    # metric, but just use total RAM for now.
    memsize = ctypes.c_int64()
    memsizesize = ctypes.c_size_t(8)
    res = sysctlbyname(
        b"hw.memsize", ctypes.byref(memsize), ctypes.byref(memsizesize), None, 0
    )
    if res != 0:
        raise NotImplementedError(
            f"failed to retrieve hw.memsize sysctl: {ctypes.get_errno()}"
        )
    return memsize.value // (1024 * 1024)


def _get_available_ram_windows() -> int:
    import ctypes

    DWORD = ctypes.c_uint32
    QWORD = ctypes.c_uint64

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", DWORD),
            ("dwMemoryLoad", DWORD),
            ("ullTotalPhys", QWORD),
            ("ullAvailPhys", QWORD),
            ("ullTotalPageFile", QWORD),
            ("ullAvailPageFile", QWORD),
            ("ullTotalVirtual", QWORD),
            ("ullAvailVirtual", QWORD),
            ("ullExtendedVirtual", QWORD),
        ]

    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(ms)
    # pyre-ignore[16]
    res = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
    if res == 0:
        raise NotImplementedError("error calling GlobalMemoryStatusEx")

    # This is fuzzy, but AvailPhys is too conservative, and AvailTotal is too
    # aggressive, so average the two. It's okay for builds to use some swap.
    return (ms.ullAvailPhys + ms.ullTotalPhys) // (2 * 1024 * 1024)


def get_available_ram() -> int:
    """
    Returns a platform-appropriate available RAM metric in MiB.
    """
    if sys.platform == "linux":
        return _get_available_ram_linux()
    elif sys.platform == "darwin":
        return _get_available_ram_macos()
    elif sys.platform == "win32":
        return _get_available_ram_windows()
    else:
        raise NotImplementedError(
            f"platform {sys.platform} does not have an implementation of get_available_ram"
        )


class HostType(object):
    def __init__(self, ostype=None, distro=None, distrovers=None):
        if ostype is None:
            distro = None
            distrovers = None
            if sys.platform.startswith("linux"):
                ostype, distro, distrovers = get_linux_type()
            elif sys.platform.startswith("darwin"):
                ostype = "darwin"
            elif is_windows():
                ostype = "windows"
                distrovers = str(sys.getwindowsversion().major)
            else:
                ostype = sys.platform

        # The operating system type
        self.ostype = ostype
        # The distribution, if applicable
        self.distro = distro
        # The OS/distro version if known
        self.distrovers = distrovers
        machine = platform.machine().lower()
        if "arm" in machine or "aarch" in machine:
            self.isarm = True
        else:
            self.isarm = False

    def is_windows(self):
        return self.ostype == "windows"

    def is_arm(self):
        return self.isarm

    def is_darwin(self):
        return self.ostype == "darwin"

    def is_linux(self):
        return self.ostype == "linux"

    def as_tuple_string(self):
        return "%s-%s-%s" % (
            self.ostype,
            self.distro or "none",
            self.distrovers or "none",
        )

    def get_package_manager(self):
        if not self.is_linux() and not self.is_darwin():
            return None
        if self.is_darwin():
            return "homebrew"
        if self.distro in ("fedora", "centos", "centos_stream"):
            return "rpm"
        if self.distro.startswith(("debian", "ubuntu")):
            return "deb"
        return None

    @staticmethod
    def from_tuple_string(s):
        ostype, distro, distrovers = s.split("-")
        return HostType(ostype=ostype, distro=distro, distrovers=distrovers)

    def __eq__(self, b):
        return (
            self.ostype == b.ostype
            and self.distro == b.distro
            and self.distrovers == b.distrovers
        )
