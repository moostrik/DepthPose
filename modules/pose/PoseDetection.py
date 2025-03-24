# based on
# https://www.tensorflow.org/hub/tutorials/movenet
# https://github.com/Kazuhito00/MoveNet-Python-Example/tree/main
# Lightning for low latency, Thunder for high accuracy


import cv2
import numpy as np
import time
import onnxruntime as ort
from enum import Enum
from threading import Thread, Lock
import copy
import os

from modules.pose.PoseDefinitions import *
from modules.person.Person import Person

class PoseDetection(Thread):
    onnx_session: ort.InferenceSession | None = None
    onnx_size: int = 256
    model_multi: bool = False

    def __init__(self, path: str, model_type:ModelType) -> None:
        super().__init__()
        self.path: str = path
        self.modelType: ModelType = model_type
        # if model_type is not ModelType.THUNDER and model_type is not ModelType.LIGHTNING:
        #     print('PoseDetection ModelType must be THUNDER or LIGHTNING, defaulting to THUNDER', model_type)
        self.modelType = ModelType.THUNDER

        self._input_mutex: Lock = Lock()
        self._image: np.ndarray | None = None
        self._image_consumed: bool = True

        self._detection: Person | None = None

        self._running: bool = False
        self._callbacks: set = set()
        self._occupied: bool = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        if PoseDetection.onnx_session is None:
            PoseDetection.onnx_session, PoseDetection.onnx_size, PoseDetection.model_multi = self.LoadSession(self.modelType, self.path)

        self._running = True
        while self._running:
            detection: Person | None = self.get_detection()
            if detection is not None:
                image: np.ndarray | None = detection.pose_image
                if image is not None:
                    Poses: PoseList = self.RunSession(PoseDetection.onnx_session, PoseDetection.onnx_size, PoseDetection.model_multi, image)
                    detection.pose = Poses
                    self.callback(detection)
            time.sleep(0.01)

    def get_detection(self) -> Person | None:
        with self._input_mutex:
            return_detection: Person | None = self._detection
            self._detection = None
            return return_detection

    def set_detection(self, detection: Person) -> None:
        with self._input_mutex:
            self._detection = detection

    def get_frame_size(self) -> int:
        return PoseDetection.onnx_size

    # CALLBACKS
    def callback(self, value: Person) -> None:
        for c in self._callbacks:
            c(value)

    def addMessageCallback(self, callback) -> None:
        self._callbacks.add(callback)

    def clearMessageCallbacks(self) -> None:
        self._callbacks = set()

    # STATIC METHODS
    @staticmethod
    def LoadSession(model_type: ModelType, model_path: str) -> tuple[ort.InferenceSession, int, bool]:
        print('Loading PoseDetection Model:', ModelTypeNames[model_type.value])
        path: str = os.path.join(model_path, ModelFileNames[model_type.value])
        onnx_session = ort.InferenceSession(
            path,
            providers=[
                'CUDAExecutionProvider',
                'CPUExecutionProvider'
            ],
        )
        input_size: int = ModelInputSize[model_type.value]
        model_multi: bool = model_type is ModelType.MULTI
        return onnx_session, input_size, model_multi

    @staticmethod
    def RunSession(onnx_session: ort.InferenceSession, input_size: int, model_multi: bool, image: np.ndarray) -> PoseList:
        height, width = image.shape[:2]
        if height != input_size or width != input_size:
            image = PoseDetection.resize_with_pad(image, input_size, input_size)
        input_image: np.ndarray = image.reshape(-1, input_size, input_size, 3)
        input_image = input_image.astype('int32')

        input_name  = onnx_session.get_inputs()[0].name
        output_name = onnx_session.get_outputs()[0].name
        outputs     = onnx_session.run([output_name], {input_name: input_image})

        keypoints_with_scores: np.ndarray = outputs[0]
        keypoints_with_scores = np.squeeze(keypoints_with_scores)

        if not model_multi:
            keypoints: np.ndarray = keypoints_with_scores[:, :2]
            keypoints = np.flip(keypoints, axis=1)
            scores: np.ndarray = keypoints_with_scores[:, 2]
            pose = Pose(keypoints, scores)
            return [pose]
        else:
            poses: PoseList = []
            for kps in keypoints_with_scores:

                mean_score = kps[55]
                if mean_score < 0.1:
                    continue

                # make a nd.array of 17 by 3 for the keypoints
                keypoints: np.ndarray = np.zeros((17, 2), dtype=np.float32)
                scores: np.ndarray = np.zeros((17), dtype=np.float32)
                for index in range(17):
                    x: float = kps[(index * 3) + 1]
                    y: float = kps[(index * 3) + 0]
                    s: float = kps[(index * 3) + 2]

                    keypoints[index] = [x, y]
                    scores[index] = s

                ymin: float = kps[51]
                xmin: float = kps[52]
                ymax: float = kps[53]
                xmax: float = kps[54]

                pose = Pose(keypoints, scores)
                poses.append(pose)
            return poses

    @staticmethod
    def resize_with_pad(image, target_width, target_height, padding_color=(0, 0, 0)) -> np.ndarray:
        # Get the original dimensions
        original_height, original_width = image.shape[:2]

        # Calculate the aspect ratio
        aspect_ratio: float = original_width / original_height

        # Determine the new dimensions while maintaining the aspect ratio
        if target_width / target_height > aspect_ratio:
            new_height: int = target_height
            new_width = int(target_height * aspect_ratio)
        else:
            new_width: int = target_width
            new_height = int(target_width / aspect_ratio)

        # Resize the image
        resized_image: np.ndarray = cv2.resize(image, (new_width, new_height))

        # Create a new image with the target dimensions and the padding color
        padded_image: np.ndarray = np.full((target_height, target_width, 3), padding_color, dtype=np.uint8)

        # Calculate the position to place the resized image
        x_offset: int = (target_width - new_width) // 2
        y_offset: int = (target_height - new_height) // 2

        # Place the resized image on the padded image
        padded_image[y_offset:y_offset+new_height, x_offset:x_offset+new_width] = resized_image

        return padded_image