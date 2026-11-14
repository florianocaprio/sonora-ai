"""Contratti pubblici del servizio locale e intervalli a campioni."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sample = Annotated[int, Field(ge=0, le=2**63-1, strict=True)]
FirstEndSample = Annotated[int, Field(gt=0, le=2**63-1, strict=True)]
Stem = Literal["original", "dialogue", "music", "effects", "residual", "master", "difference"]
MixStem = Literal["original", "dialogue", "music", "effects", "residual"]
VersionStatus = Literal["approved", "proposed", "rejected"]
JobStatus = Literal["queued", "running", "cancelling", "cancelled", "succeeded", "failed", "blocked"]
Profile = Literal["basic", "medium", "high"]
Rate = Annotated[int, Field(ge=8000, le=192000)]
Name = Annotated[str, Field(min_length=1, max_length=120)]
Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ProjectName(Contract):
    name: Name


class ProjectPatch(Contract):
    name: Name | None = None
    archived: bool | None = None


class VersionPatch(Contract):
    status: Literal["approved", "rejected"]


class Region(Contract):
    start_sample: Sample = 0
    end_sample: FirstEndSample | None = None

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end_sample is not None and self.end_sample <= self.start_sample:
            raise ValueError("L'intervallo deve avere una durata positiva.")
        return self


class AssetJob(Region):
    asset_id: Identifier


class Separate(AssetJob):
    model_id: Annotated[str, Field(pattern="^[a-z0-9-]{1,64}$")]
    backend: Literal["cpu", "mps"] = "cpu"


class Analyze(AssetJob):
    sensitivity: float = Field(default=0.5, ge=0, le=1)
    depth: Literal["quick", "standard", "deep"] = "standard"


class Operation(Region):
    type: Literal["dc_remove", "dehum", "declick", "peq", "microgap"]
    end_sample: FirstEndSample
    wet: float = Field(default=1, ge=0, le=1)
    bypass: bool = False
    params: dict[str, float] = Field(default_factory=dict)


class Restore(Contract):
    asset_id: Identifier
    operations: list[Operation] = Field(min_length=1, max_length=128)
    profile: Profile = "basic"

    @model_validator(mode="after")
    def validate_profile(self):
        if self.profile != "high" and any(op.type == "microgap" and not op.bypass for op in self.operations):
            raise ValueError("Seleziona High per la ricostruzione dei micro-gap.")
        return self


class EventPatch(Contract):
    status: Literal["unreviewed", "confirmed", "dismissed", "repaired"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    start_sample: Sample | None = None
    end_sample: FirstEndSample | None = None


class Channel(Contract):
    gain_db: float = Field(default=0, ge=-90, le=24)
    trim_db: float = Field(default=0, ge=-80, le=24)
    bypass: bool = False
    eq: list[dict] | dict | None = None
    compressor: dict | None = None


class Track(Channel):
    asset_id: Identifier
    pan: float = Field(default=0, ge=-1, le=1)
    mute: bool = False
    solo: bool = False
    polarity: bool = False
    automation: dict[str, list[dict]] | None = None


class Master(Channel):
    ceiling_dbtp: float | None = Field(default=None, ge=-30, le=0)


class Mix(Contract):
    tracks: dict[MixStem, Track] = Field(min_length=1, max_length=5)
    master: Master = Field(default_factory=Master)


class Export(Contract):
    mix_id: Identifier
    format: Literal["wav_float", "wav_pcm24", "flac"] = "wav_float"
    sample_rate: Rate | None = None
