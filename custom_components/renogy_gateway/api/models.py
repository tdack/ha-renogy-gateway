"""Data models for the Renogy DC Home API."""

from dataclasses import dataclass, field


@dataclass
class TokenSet:
    """Authentication tokens for the Renogy API."""

    access_token: str
    refresh_token: str
    rtm_token: str
    rtm_did: str
    device_uuid: str


@dataclass
class GatewayInfo:
    """Basic info about a Renogy ONE Core gateway."""

    did_str: str
    name: str
    online: bool


@dataclass
class FieldSpec:
    """Schema description of a single RTM field/topic."""

    sp: str
    """Full topic path: '<device_did>/<namespace>.<field_path>'."""
    name: str
    """Stable field key, language-neutral (from gwm.get_model)."""
    field_type: int
    """1=bool, 2=int, 3=float, 4=str, 5=array, 7=obj, 8=func, 9=series."""
    ops: int
    """Bitmask of allowed operations: 1=write, 2=read, 4=subscribe."""
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    options: list[dict] | None = None
    """Enum choices: [{key, value}]."""
    precision: int = 0
    user_label: str | None = None
    """User-assigned friendly name from userdata_str.config (e.g. 'Bedroom Light')."""

    @property
    def writable(self) -> bool:
        """Return True if this field can be written (ops & 1)."""
        return bool(self.ops & 1)

    @property
    def readable(self) -> bool:
        """Return True if this field can be read (ops & 2)."""
        return bool(self.ops & 2)

    @property
    def subscribable(self) -> bool:
        """Return True if this field supports push subscriptions (ops & 4)."""
        return bool(self.ops & 4)

    @property
    def channel_key(self) -> str | None:
        """Extract the channel key from the sp for user-label lookup.

        e.g. '<did>/distribution_box.dc_10a_1.state' → 'dc_10a_1'
        Returns None if the sp does not have at least three path segments.
        """
        # sp = "<did>/<namespace>.<channel>.<field>" or "<did>/<namespace>.<field>"
        after_slash = self.sp.split("/", 1)[-1]  # "<namespace>.<channel>.<field>"
        parts = after_slash.split(".", 2)
        return parts[1] if len(parts) >= 3 else None

    @property
    def display_name(self) -> str:
        """Return the best available human name."""
        return self.user_label or self.name


@dataclass
class SceneInfo:
    """A scene (Manual or Auto) from the gateway's REST scene CRUD (PROTOCOL.md §8).

    `raw` keeps the exact object as returned by `getUserScenes` so it can be
    echoed back intact to `updateScene` when toggling an Auto scene's armed
    state — the API expects the full scene body, not a partial patch.
    """

    id: str
    name: str
    gateway_did: str
    is_manual: bool
    """True for a Manual (Run-button) scene; False for an Auto (condition-triggered) scene."""
    is_open: bool
    """Auto scene armed state. Always True for Manual scenes (no enable toggle)."""
    raw: dict


@dataclass
class RenogyDevice:
    """A device discovered behind a Renogy gateway."""

    did_str: str
    pid: str
    sku: str
    name: str
    online: bool
    fields: list[FieldSpec] = field(default_factory=list)
    ctrl_sp_blacklist: frozenset[str] = frozenset()
    """Relative field paths (e.g. 'charger.max_current') the device firmware
    refuses to accept writes for, from driving_mode.ctrl_sp_blacklist."""

    @property
    def did(self) -> int:
        """Return the device DID as a Python int (lossless int64)."""
        return int(self.did_str)
