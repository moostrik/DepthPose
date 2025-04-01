class Settings():
    def __init__(self) -> None:
        self.root_path: str
        self.model_path: str
        self.video_path: str
        self.temp_path: str
        self.file_path: str
        self.camera_list: list[str]
        self.fps: int
        self.num_players: int
        self.color: bool
        self.stereo: bool
        self.person: bool
        self.lowres: bool
        self.show_stereo: bool
        self.lightning: bool
        self.pose: bool
        self.simulation: bool
        self.passthrough: bool