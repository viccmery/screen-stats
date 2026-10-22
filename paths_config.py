from pathlib import Path
import os
import getpass
import socket


# ---------------------------------------------------------------------
# User / machine detection
# ---------------------------------------------------------------------

USERNAME = os.environ.get("USER") or getpass.getuser()
HOSTNAME = socket.gethostname()

RUNNING_ON_NEMO = (
    HOSTNAME.startswith("login")
    or HOSTNAME.startswith("cn")
    or Path("/nemo/lab/windingm").exists()
)

RUNNING_ON_MAC = Path("/Volumes/lab-windingm").exists()


# ---------------------------------------------------------------------
# Root paths
# ---------------------------------------------------------------------

if RUNNING_ON_NEMO:
    LAB_ROOT = Path("/nemo/lab/windingm")
    USER_ROOT = LAB_ROOT / "home/users" / USERNAME
    LOCAL_REPO_ROOT = Path.home() / "repos" / "behavioural-rigs"

elif RUNNING_ON_MAC:
    LAB_ROOT = Path("/Volumes/lab-windingm")
    USER_ROOT = LAB_ROOT / "home/users" / USERNAME
    LOCAL_REPO_ROOT = Path.home() / "repos" / "behavioural-rigs"

else:
    raise RuntimeError(
        "Could not detect lab filesystem. "
        "Are you on Nemo or is /Volumes/lab-windingm mounted?"
    )


SHARED_HOME = LAB_ROOT / "home/shared"
SHARED_DATA_ROOT = SHARED_HOME / "behavioural-rigs_data"
INSTRUMENTS_ROOT = LAB_ROOT / "data/instruments/behavioural_rigs/plugcamera"


# ---------------------------------------------------------------------
# Directory registry
# ---------------------------------------------------------------------

dirs = {
    # roots
    "lab-root": LAB_ROOT,
    "shared-home": SHARED_HOME,
    "shared-root": SHARED_DATA_ROOT,
    "user-root": USER_ROOT,
    "local-repo-root": LOCAL_REPO_ROOT,

    # shared data
    "instruments-root": INSTRUMENTS_ROOT,
    "plugcamera-instruments": INSTRUMENTS_ROOT,

    # sheets
    "final-sheets": SHARED_DATA_ROOT / "final-sheets",
    "intermediate-sheets": SHARED_DATA_ROOT / "intermediate-sheets",

    # screen folders
    "mechano-screen": SHARED_DATA_ROOT / "mechano-screen",
    "split-screen": SHARED_DATA_ROOT / "split-screen",
    "top-up-screen": SHARED_DATA_ROOT / "top-up-screen",
    "VRDN-screen": SHARED_DATA_ROOT / "VRDN-screen",

    # backups
    "backup-mechano": SHARED_DATA_ROOT / "mechano-backup",
    "backup-split": SHARED_DATA_ROOT / "split-backup",
    "backup-top-up": SHARED_DATA_ROOT / "top-up-backup",
    "backup-VRDN": SHARED_DATA_ROOT / "VRDN-backup",

    # shared analysis folders
    "plugcamera": SHARED_DATA_ROOT / "plugcamera",
    "notebooks": SHARED_DATA_ROOT / "notebooks",
    "fly-lines": SHARED_DATA_ROOT / "fly-lines",
    "metadata": SHARED_DATA_ROOT / "metadata",
    "logs": SHARED_DATA_ROOT / "logs",

    # user-specific folders
    "personal-behavioural-data": USER_ROOT / "behavioural-data",
    "personal-repos": Path.home() / "repos",
}


SCREEN_KEYS = (
    "mechano-screen",
    "split-screen",
    "top-up-screen",
    "VRDN-screen",
)


# ---------------------------------------------------------------------
# Google Sheet IDs
# ---------------------------------------------------------------------

WEEK_TO_SPREADSHEET_ID = {
    1: "1pLGTVYPtalXG0o81nfcdldW7l_wCYjrAkbaok7Qm1AA",
    2: "1LyZz-w3hfr1HtEhWeX-Mh7jGxFdMruvkwO_f6CJAFXM",
    3: "1Qhw80Em3mNXuQzxJDndURJooYMgjBusFIzSk_V5VY7k",
    4: "1WrWOelZgj5-MBAScA3J1nOvCJ362CMWuvTNuXOvOwnI",
    5: "1-_ieR_zL29S_yWGH8p5NCDg6I8T8uD8iYOywlqnv8RQ",
    6: "1p-rRjZKr78O77VeYuWq3zRA74Vjdli2j5pshYnwmJd0",
    7: "1g8utRFF02OVMsuhlnVtWP37OPk-AR87k7LYKUXkWiY0",
}


SPREADSHEET_TO_EXP_NAME = {
    # spreadsheet_id: {
    #     "week": 1,
    #     "date": "2026-...",
    #     "screen": "VRDN-screen",
    #     "sheet_prefix": "...",
    # }
}


# ---------------------------------------------------------------------
# Experiment path helpers
# ---------------------------------------------------------------------

def experiment_root(exp_name: str) -> Path:
    """
    Shared canonical experiment folder.
    """
    return dirs["plugcamera-instruments"] / exp_name


def experiment_pupae_root(exp_name: str) -> Path:
    return experiment_root(exp_name) / "pupae"


def experiment_raw_data(exp_name: str) -> Path:
    return experiment_pupae_root(exp_name) / "raw_data"


def personal_experiment_root(exp_name: str) -> Path:
    """
    User-specific staging folder.
    Resolves differently for meryv, svc-windingm-pi, or any other user.
    """
    return dirs["personal-behavioural-data"] / exp_name


def personal_experiment_raw_data(exp_name: str) -> Path:
    return personal_experiment_root(exp_name) / "pupae" / "raw_data"


# ---------------------------------------------------------------------
# Validation / debugging
# ---------------------------------------------------------------------

def check_dirs(required_keys=None):
    if required_keys is None:
        required_keys = dirs.keys()

    missing = []

    for key in required_keys:
        path = dirs[key]
        if not path.exists():
            missing.append((key, path))

    if missing:
        msg = ["Missing directories:"]
        for key, path in missing:
            msg.append(f"  {key}: {path}")
        raise FileNotFoundError("\n".join(msg))

    return True


def print_dirs():
    print(f"USERNAME: {USERNAME}")
    print(f"HOSTNAME: {HOSTNAME}")
    print(f"RUNNING_ON_NEMO: {RUNNING_ON_NEMO}")
    print(f"RUNNING_ON_MAC: {RUNNING_ON_MAC}")
    print()

    for key, path in dirs.items():
        status = "exists" if path.exists() else "missing"
        print(f"{key:30s} {status:8s} {path}")