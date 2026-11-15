"""Which Linux family this is, so messages name the right install command.

install.sh has the same package table (keep them in sync).
"""

import os
import shutil

# What FloatNote needs -> package names per package manager.
PACKAGES = {
    "apt": {"portaudio": "libportaudio2", "gobject": "python3-gi", "gtk": "gir1.2-gtk-3.0",
            "venv": "python3-venv", "clipboard": "wl-clipboard xclip", "sound": "pipewire-bin"},
    "dnf": {"portaudio": "portaudio", "gobject": "python3-gobject", "gtk": "gtk3",
            "venv": "", "clipboard": "wl-clipboard xclip", "sound": "pipewire-utils"},
    "pacman": {"portaudio": "portaudio", "gobject": "python-gobject", "gtk": "gtk3",
               "venv": "", "clipboard": "wl-clipboard xclip", "sound": "pipewire"},
    "zypper": {"portaudio": "libportaudio2", "gobject": "python3-gobject python3-gobject-Gdk",
               "gtk": "typelib-1_0-Gtk-3_0", "venv": "", "clipboard": "wl-clipboard xclip",
               "sound": "pipewire-tools"},
}

_INSTALL = {"apt": "sudo apt install", "dnf": "sudo dnf install", "pacman": "sudo pacman -S --needed",
            "zypper": "sudo zypper install", "rpm-ostree": "sudo rpm-ostree install"}


def is_atomic() -> bool:
    """Fedora Silverblue/Kinoite and other image-based systems."""
    return os.path.exists("/run/ostree-booted")


def package_manager() -> str | None:
    """'apt', 'dnf', 'pacman', 'zypper' or None."""
    for manager, tool in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman"), ("zypper", "zypper")):
        if shutil.which(tool):
            return manager
    if is_atomic():
        return "dnf"  # package names are Fedora's; installed with rpm-ostree
    return None


def install_hint(*needs: str) -> str:
    """'sudo dnf install portaudio' for the given needs ('portaudio', 'clipboard', …)."""
    manager = package_manager()
    if manager is None:
        return "install " + " and ".join(needs) + " with your package manager"
    names = " ".join(p for need in needs if (p := PACKAGES[manager][need]))
    return f"{_INSTALL['rpm-ostree' if is_atomic() else manager]} {names}"


def input_group_hint() -> str:
    """Command that gives the user keyboard access."""
    if is_atomic():  # the group lives in /usr/lib/group, usermod only sees /etc/group
        return ("grep -q '^input:' /etc/group || grep '^input:' /usr/lib/group | sudo tee -a /etc/group; "
                "sudo usermod -aG input $USER")
    return "sudo usermod -aG input $USER"
