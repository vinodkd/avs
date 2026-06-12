import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionStatus(str, enum.Enum):
    """Lifecycle states for a Session. Stored as strings in the DB."""
    IMPORTING = "importing"   # ingest running
    INGESTED  = "ingested"    # ingest complete, analysis not yet started
    ANALYZING = "analyzing"   # analysis pipeline running
    READY     = "ready"       # analysis complete, marks available for review
    ASSEMBLED = "assembled"   # preview video built
    EXPORTED  = "exported"    # final output written


class MarkStatus(str, enum.Enum):
    """Review state for a candidate Mark."""
    CANDIDATE = "candidate"
    ACCEPTED  = "accepted"
    REJECTED  = "rejected"


def _uuid() -> str:
    return str(uuid.uuid4())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str]      = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_path: Mapped[str]     = mapped_column(Text)
    sport: Mapped[str | None]    = mapped_column(String, nullable=True)
    camera: Mapped[str | None]   = mapped_column(String, nullable=True)
    total_clips: Mapped[int | None]      = mapped_column(Integer, nullable=True)
    total_duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default=SessionStatus.IMPORTING)

    clips: Mapped[list["Clip"]]     = relationship(back_populates="session", cascade="all, delete-orphan")
    exports: Mapped[list["Export"]] = relationship(back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Session {self.id[:8]} sport={self.sport} status={self.status}>"


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str]         = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), nullable=False)
    filename: Mapped[str]   = mapped_column(Text, nullable=False)
    filepath: Mapped[str]   = mapped_column(Text, nullable=False)
    proxy_path: Mapped[str | None]  = mapped_column(Text, nullable=True)
    duration_s: Mapped[float]       = mapped_column(Float, nullable=False)
    width: Mapped[int | None]       = mapped_column(Integer, nullable=True)
    height: Mapped[int | None]      = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None]       = mapped_column(Float, nullable=True)
    codec: Mapped[str | None]       = mapped_column(String, nullable=True)
    has_telemetry: Mapped[bool]     = mapped_column(Boolean, default=False)
    peak_speed_kmh: Mapped[float | None]   = mapped_column(Float, nullable=True)
    peak_altitude_m: Mapped[float | None]  = mapped_column(Float, nullable=True)
    peak_motion: Mapped[float | None]      = mapped_column(Float, nullable=True)
    scene_count: Mapped[int | None]        = mapped_column(Integer, nullable=True)
    clip_order: Mapped[int]                = mapped_column(Integer, nullable=False)
    # JSON-encoded list of additional chapter file paths (GoPro only)
    chapter_paths: Mapped[str | None]      = mapped_column(Text, nullable=True)

    session: Mapped["Session"]       = relationship(back_populates="clips")
    telemetry: Mapped[list["TelemetryPoint"]] = relationship(back_populates="clip", cascade="all, delete-orphan")
    marks: Mapped[list["Mark"]]      = relationship(back_populates="clip", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Clip {self.filename} {self.duration_s:.1f}s>"


class TelemetryPoint(Base):
    __tablename__ = "telemetry"

    id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[str]     = mapped_column(String, ForeignKey("clips.id"), nullable=False)
    timestamp_s: Mapped[float]           = mapped_column(Float, nullable=False)
    speed_kmh: Mapped[float | None]      = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None]     = mapped_column(Float, nullable=True)
    lat: Mapped[float | None]            = mapped_column(Float, nullable=True)
    lon: Mapped[float | None]            = mapped_column(Float, nullable=True)
    accel_magnitude: Mapped[float | None]    = mapped_column(Float, nullable=True)
    motion_intensity: Mapped[float | None]       = mapped_column(Float, nullable=True)
    motion_intensity_quick: Mapped[float | None] = mapped_column(Float, nullable=True)

    clip: Mapped["Clip"] = relationship(back_populates="telemetry")


class Mark(Base):
    __tablename__ = "marks"

    id: Mapped[str]      = mapped_column(String, primary_key=True, default=_uuid)
    clip_id: Mapped[str] = mapped_column(String, ForeignKey("clips.id"), nullable=False)
    in_s: Mapped[float]  = mapped_column(Float, nullable=False)
    out_s: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float | None]  = mapped_column(Float, nullable=True)
    # telemetry_peak | motion_peak | audio_peak | user | llm
    source: Mapped[str]  = mapped_column(String, nullable=False)
    status: Mapped[str]  = mapped_column(String, nullable=False, default=MarkStatus.CANDIDATE)
    order_in_edit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    clip: Mapped["Clip"] = relationship(back_populates="marks")

    def __repr__(self) -> str:
        return f"<Mark {self.in_s:.1f}–{self.out_s:.1f}s score={self.score} status={self.status}>"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str]    = mapped_column(String, primary_key=True, default=_uuid)
    sport: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # punchy | cinematic | natural | warm | cool | vibrant
    color_grade: Mapped[str]  = mapped_column(String, nullable=False)
    # high | medium | chill
    music_energy: Mapped[str] = mapped_column(String, nullable=False)
    target_duration_youtube_s: Mapped[int | None]  = mapped_column(Integer, nullable=True)
    target_duration_short_s: Mapped[int | None]    = mapped_column(Integer, nullable=True)
    min_clip_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_clip_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    overlay_speed: Mapped[bool]    = mapped_column(Boolean, default=True)
    overlay_altitude: Mapped[bool] = mapped_column(Boolean, default=True)
    overlay_gps_map: Mapped[bool]  = mapped_column(Boolean, default=False)
    speed_threshold_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    motion_threshold: Mapped[float | None]    = mapped_column(Float, nullable=True)
    # scene detection — content | adaptive | threshold
    scene_detector: Mapped[str] = mapped_column(String, nullable=False, default="content")
    scene_threshold: Mapped[float | None]       = mapped_column(Float, nullable=True)
    scene_min_scene_len: Mapped[int | None]     = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Profile sport={self.sport} grade={self.color_grade}>"


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str]         = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), nullable=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    filepath: Mapped[str]   = mapped_column(Text, nullable=False)
    aspect: Mapped[str]     = mapped_column(String, nullable=False)  # 16:9 | 9:16
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    session: Mapped["Session"] = relationship(back_populates="exports")


class AppSetting(Base):
    """App-level key/value settings (UI preferences). Values are JSON-encoded."""
    __tablename__ = "app_settings"

    key: Mapped[str]   = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}={self.value}>"
