"""Default sport profiles. Each entry maps to a Profile row in the database."""

from dataclasses import dataclass


@dataclass
class SportDefaults:
    color_grade: str
    music_energy: str
    target_duration_youtube_s: int
    target_duration_short_s: int
    min_clip_s: float
    max_clip_s: float
    overlay_speed: bool
    overlay_altitude: bool
    overlay_gps_map: bool
    speed_threshold_kmh: float
    motion_threshold: float
    scene_detector: str
    scene_threshold: float
    scene_min_scene_len: int


DEFAULT_PROFILES: dict[str, dict] = {
    "mtb": dict(
        color_grade="punchy",
        music_energy="high",
        target_duration_youtube_s=240,
        target_duration_short_s=45,
        min_clip_s=2.0,
        max_clip_s=15.0,
        overlay_speed=True,
        overlay_altitude=True,
        overlay_gps_map=False,
        speed_threshold_kmh=25.0,
        motion_threshold=0.60,
        scene_detector="content",
        scene_threshold=27.0,
        scene_min_scene_len=15,
    ),
    "surf": dict(
        color_grade="warm",
        music_energy="medium",
        target_duration_youtube_s=180,
        target_duration_short_s=40,
        min_clip_s=3.0,
        max_clip_s=20.0,
        overlay_speed=False,
        overlay_altitude=False,
        overlay_gps_map=False,
        speed_threshold_kmh=15.0,
        motion_threshold=0.50,
        scene_detector="adaptive",
        scene_threshold=3.0,
        scene_min_scene_len=20,
    ),
    "ski": dict(
        color_grade="cool",
        music_energy="high",
        target_duration_youtube_s=240,
        target_duration_short_s=45,
        min_clip_s=2.0,
        max_clip_s=15.0,
        overlay_speed=True,
        overlay_altitude=True,
        overlay_gps_map=False,
        speed_threshold_kmh=40.0,
        motion_threshold=0.65,
        scene_detector="content",
        scene_threshold=30.0,
        scene_min_scene_len=15,
    ),
    "skydive": dict(
        color_grade="vibrant",
        music_energy="high",
        target_duration_youtube_s=150,
        target_duration_short_s=60,
        min_clip_s=2.0,
        max_clip_s=30.0,
        overlay_speed=True,
        overlay_altitude=True,
        overlay_gps_map=False,
        speed_threshold_kmh=100.0,
        motion_threshold=0.70,
        scene_detector="adaptive",
        scene_threshold=3.0,
        scene_min_scene_len=10,
    ),
    "moto": dict(
        color_grade="cinematic",
        music_energy="high",
        target_duration_youtube_s=360,
        target_duration_short_s=60,
        min_clip_s=3.0,
        max_clip_s=20.0,
        overlay_speed=True,
        overlay_altitude=False,
        overlay_gps_map=False,
        speed_threshold_kmh=60.0,
        motion_threshold=0.55,
        scene_detector="content",
        scene_threshold=35.0,
        scene_min_scene_len=25,
    ),
    "trail": dict(
        color_grade="natural",
        music_energy="medium",
        target_duration_youtube_s=180,
        target_duration_short_s=40,
        min_clip_s=3.0,
        max_clip_s=20.0,
        overlay_speed=False,
        overlay_altitude=True,
        overlay_gps_map=False,
        speed_threshold_kmh=10.0,
        motion_threshold=0.40,
        scene_detector="content",
        scene_threshold=25.0,
        scene_min_scene_len=20,
    ),
    "cycling": dict(
        color_grade="natural",
        music_energy="medium",
        target_duration_youtube_s=300,
        target_duration_short_s=50,
        min_clip_s=2.0,
        max_clip_s=15.0,
        overlay_speed=True,
        overlay_altitude=True,
        overlay_gps_map=False,
        speed_threshold_kmh=20.0,
        motion_threshold=0.45,
        scene_detector="content",
        scene_threshold=27.0,
        scene_min_scene_len=15,
    ),
}

VALID_SPORTS = list(DEFAULT_PROFILES.keys())
VALID_GRADES = ["punchy", "cinematic", "natural", "warm", "cool", "vibrant"]
VALID_ENERGIES = ["high", "medium", "chill"]
