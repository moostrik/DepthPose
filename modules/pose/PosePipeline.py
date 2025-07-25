# Standard library imports
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Optional

# Third-party imports
import numpy as np

# Local application imports
from modules.cam.depthcam.Definitions import FrameType
from modules.tracker.Tracklet import Tracklet, TrackletCallback, Rect, TrackingStatus
from modules.pose.PoseDefinitions import ModelTypeNames, Pose, PoseCallback
from modules.pose.PoseDetection import Detection
from modules.pose.PoseImageProcessor import PoseImageProcessor
from modules.pose.PoseAngleCalculator import PoseAngleCalculator
from modules.Settings import Settings

from modules.utils.HotReloadMethods import HotReloadMethods


class PosePipeline(Thread):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._stop_event = Event()
        self.tracklet_input_queue: Queue[Tracklet] = Queue()

        self.input_mutex: Lock = Lock()
        self.input_frames: dict[int, np.ndarray] = {}

        self.pose_active: bool = settings.pose_active
        self.pose_detector_frame_size: int = 256
        self.pose_crop_expansion: float = settings.pose_crop_expansion
        self.max_detectors: int = settings.max_players
        self.pose_detectors: dict[int, Detection] = {}

        self.image_processor: PoseImageProcessor = PoseImageProcessor(
            crop_expansion=self.pose_crop_expansion,
            output_size=self.pose_detector_frame_size
        )

        if self.pose_active:
            for i in range(self.max_detectors):
                self.pose_detectors[i] = Detection(settings.path_model, settings.pose_model_type, True)
            print('Pose Detection:', self.max_detectors, 'instances of model', ModelTypeNames[settings.pose_model_type.value])
        else:
            print('Pose Detection: Disabled')

        # Pose angles calculator
        self.joint_angles: PoseAngleCalculator = PoseAngleCalculator(settings.pose_conf_threshold)

        # Callbacks
        self.callback_lock = Lock()
        self.pose_output_callbacks: set[PoseCallback] = set()

        hot_reloader = HotReloadMethods(self.__class__)

    def start(self) -> None:
        if super().is_alive():
            print("PosePipeline is already running.")
            return

        self.joint_angles.add_pose_callback(self._notify_pose_callback)
        self.joint_angles.start()

        # Start detectors
        for detector in self.pose_detectors.values():
            detector.addMessageCallback(self.joint_angles.pose_input)
            detector.start()
            self.pose_detector_frame_size = detector.get_frame_size()

        super().start()

    def stop(self) -> None:
        self._stop_event.set()
        self.join()
        with self.callback_lock:
            self.pose_output_callbacks.clear()

        for detector in self.pose_detectors.values():
            detector.stop()

        self.joint_angles.stop()

    def run(self) -> None:
        """
        Update the pose pipeline with a new tracklet.
        This method is called when a new tracklet is detected or updated.
        """
        while not self._stop_event.is_set():
            try:
                tracklet: Optional[Tracklet] = self.tracklet_input_queue.get(block=True, timeout=0.01)
                if tracklet is not None:
                    self._process(tracklet)
            except Empty:
                continue

    def _process(self, tracklet: Tracklet) -> None:
        pose_final: bool = tracklet.is_removed

        pose_image: Optional[np.ndarray] = None
        pose_crop_rect: Optional[Rect] = None
        cam_image: Optional[np.ndarray] = self._get_image(tracklet.cam_id)

        if cam_image is not None and tracklet.is_active:
            pose_image, pose_crop_rect = self.image_processor.process_pose_image(tracklet, cam_image)

        pose = Pose(
            id=tracklet.id,
            cam_id=tracklet.cam_id,
            time_stamp=tracklet.time_stamp,
            tracklet=tracklet,
            crop_rect = pose_crop_rect,
            image = pose_image,
            is_final = pose_final
        )

        # print(f"PosePipeline: Processing pose for tracklet {tracklet.id} at time {pose.time_stamp}")
        detector: Optional[Detection] = self.pose_detectors.get(tracklet.id)
        if detector:
            detector.add_pose(pose)
        else:
            self._notify_pose_callback(pose)

     # INPUTS
    def add_tracklet(self, tracklet: Tracklet) -> None:
        self.tracklet_input_queue.put(tracklet)

    def set_image(self, id: int, frame_type: FrameType, image: np.ndarray) -> None :
        if frame_type != FrameType.VIDEO:
            return
        with self.input_mutex:
            self.input_frames[id] = image
    def _get_image(self, id: int) -> Optional[np.ndarray]:
        with self.input_mutex:
            if not self.input_frames.get(id) is None:
                return self.input_frames[id]
            return None

    # External Output Callbacks
    def add_pose_callback(self, callback: PoseCallback) -> None:
        with self.callback_lock:
            self.pose_output_callbacks.add(callback)

    def _notify_pose_callback(self, pose: Pose) -> None:
        with self.callback_lock:
            for callback in self.pose_output_callbacks:
                callback(pose)