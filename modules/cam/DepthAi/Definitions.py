import numpy as np
from enum import Enum
from typing import Callable
from depthai import Tracklet, ImgDetection, Rect, Point3f


class FrameType(Enum):
    NONE =  0
    VIDEO = 1
    LEFT =  2
    RIGHT = 3
    STEREO= 4

FRAME_TYPE_NAMES: list[str] = [e.name for e in FrameType]

FRAME_TYPE_LABEL_DICT: dict[FrameType, str] = {
    FrameType.NONE:   'N',
    FrameType.VIDEO:  'C',
    FrameType.LEFT:   'L',
    FrameType.RIGHT:  'R',
    FrameType.STEREO: 'S'
}

EXPOSURE_RANGE:     tuple[int, int] = (1000, 33000)
ISO_RANGE:          tuple[int, int] = ( 100, 1600 )
BALANCE_RANGE:      tuple[int, int] = (1000, 12000)
CONTRAST_RANGE:     tuple[int, int] = ( -10, 10   )
BRIGHTNESS_RANGE:   tuple[int, int] = ( -10, 10   )
LUMA_DENOISE_RANGE: tuple[int, int] = (   0, 4    )
SATURATION_RANGE:   tuple[int, int] = ( -10, 10   )
SHARPNESS_RANGE:    tuple[int, int] = (   0, 4    )

STEREO_DEPTH_RANGE: tuple[int, int] = ( 500, 15000)
STEREO_BRIGHTNESS_RANGE: tuple[int, int] = (   0, 255  )

class StereoMedianFilterType(Enum):
    OFF = 0
    KERNEL_3x3 = 1
    KERNEL_5x5 = 2
    KERNEL_7x7 = 3

STEREO_FILTER_NAMES: list[str] = [e.name for e in StereoMedianFilterType]

FrameCallback = Callable[[int, FrameType, np.ndarray], None]
PreviewCallback = Callable[[int, np.ndarray], None]
DetectionCallback = Callable[[int, ImgDetection], None]
TrackerCallback = Callable[[int, Tracklet], None]
FPSCallback = Callable[[int, float], None]
