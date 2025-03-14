# DOCS
# https://oak-web.readthedocs.io/
# https://docs.luxonis.com/software/depthai/examples/depth_post_processing/

import cv2
import numpy as np
import depthai as dai
from datetime import timedelta
from PIL import Image, ImageOps
from enum import Enum

from pathlib import Path
from modules.utils.FPS import FPS

from modules.cam.DepthPipeline import SetupPipeline

class PreviewType(Enum):
    NONE =  0
    VIDEO = 1
    MONO =  2
    STEREO= 3
    MASK =  4
    MASKED= 5

PreviewTypeNames: list[str] = [e.name for e in PreviewType]

exposureRange:          tuple[int, int] = (1000, 33000)
isoRange:               tuple[int, int] = ( 100, 1600 )
balanceRange:           tuple[int, int] = (1000, 12000)
contrastRange:          tuple[int, int] = ( -10, 10   )
brightnessRange:        tuple[int, int] = ( -10, 10   )
lumaDenoiseRange:       tuple[int, int] = (   0, 4    )
saturationRange:        tuple[int, int] = ( -10, 10   )
sharpnessRange:         tuple[int, int] = (   0, 4    )

stereoDepthRange:       tuple[int, int] = ( 500, 15000)
stereoBrightnessRange:  tuple[int, int] = (   0, 255  )

class StereoMedianFilterType(Enum):
    OFF = 0
    KERNEL_3x3 = 1
    KERNEL_5x5 = 2
    KERNEL_7x7 = 3

StereoMedianFilterTypeNames: list[str] = [e.name for e in StereoMedianFilterType]


def clamp(num: int | float, size: tuple[int | float, int | float]) -> int | float:
    return max(size[0], min(num, size[1]))

def fit(image: np.ndarray, width, height) -> np.ndarray:
    h, w = image.shape[:2]
    if w == width and h == height:
        return image
    pil_image: Image.Image = Image.fromarray(image)
    size: tuple[int, int] = (width, height)
    fit_image: Image.Image = ImageOps.fit(pil_image, size)
    return np.asarray(fit_image)

class DepthAi():
    def __init__(self, modelPath:str, fps: int = 30, doColor: bool = True, doStereo: bool = True, doPerson: bool = True, lowres: bool = False, showLeft: bool = False) -> None:

        # FIXED SETTINGS
        self.modelpath: str =           modelPath
        self.fps: int =                 fps
        self.doColor: bool =            doColor
        self.doStereo: bool =           doStereo
        self.doPerson: bool =           doPerson
        self.lowres: bool =             lowres
        self.showLeft: bool =           False
        if self.doStereo and self.doColor and showLeft:
            self.showLeft: bool =       True

        # GENERAL SETTINGS
        self.previewType =              PreviewType.VIDEO
        self.flipH: bool =              False
        self.flipV: bool =              False

        # COLOR SETTINGS
        self.colorAutoExposure: bool =  True
        self.colorAutoFocus: bool =     True
        self.colorAutoBalance: bool =   True
        self.colorExposure: int =       0
        self.colorIso: int =            0
        self.colorFocus: int =          0
        self.colorBalance: int =        0
        self.colorContrast: int =       0
        self.colorBrightness: int =     0
        self.colorLumaDenoise: int =    0
        self.colorSaturation: int =     0
        self.colorSharpness: int =      0

        # MONO SETTINGS
        self.monoAutoExposure: bool =   True
        self.monoAutoFocus: bool =      True
        self.monoExposure: int =        0
        self.monoIso: int =             0

        # STEREO SETTINGS
        self.stereoConfig: dai.RawStereoDepthConfig = dai.RawStereoDepthConfig()

        # MASK SETTINGS
        self.depthTresholdMin:  int =   0
        self.depthTresholdMax:  int =   255

        # TRACKER SETTINGS
        self.numTracklets: int =           0
        self.numDetections: int =       0

        # DAI
        self.device:                    dai.Device
        self.colorControl:              dai.DataInputQueue
        self.monoControl:               dai.DataInputQueue
        self.stereoControl:             dai.DataInputQueue
        self.dataQueue:                 dai.DataOutputQueue
        self.dataCallbackId:            int

        # OTHER
        self.deviceOpen: bool =         False
        self.capturing:  bool =         False
        self.frameCallbacks: set =      set()
        self.trackerCallbacks: set =    set()
        self.fps_counter =              FPS()

        self.errorFrame: np.ndarray =   np.zeros((720, 1280, 3), dtype=np.uint8)
        if self.lowres:
            self.errorFrame = cv2.resize(self.errorFrame, (640, 360))
        self.errorFrame[:,:,2] =        255

    def __exit__(self) -> None:
        self.close()

    def open(self) -> bool:
        if self.deviceOpen: return True

        pipeline = dai.Pipeline()
        self.stereoConfig = SetupPipeline(pipeline, self.modelpath, self.fps, self.doColor, self.doStereo, self.doPerson, self.lowres, self.showLeft)

        try: self.device = dai.Device(pipeline)
        except Exception as e:
            print('could not open camera, error', e, 'try again')
            try: self.device = dai.Device(pipeline)
            except Exception as e:
                print('still could not open camera, error', e)
                return False

        self.dataQueue =    self.device.getOutputQueue(name='output_images', maxSize=4, blocking=False)
        self.colorControl = self.device.getInputQueue('color_control')
        self.monoControl =  self.device.getInputQueue('mono_control')
        self.stereoControl =self.device.getInputQueue('stereo_control')

        self.deviceOpen = True
        return True

    def close(self) -> None:
        if not self.deviceOpen: return
        if self.capturing: self.stopCapture()
        self.deviceOpen = False

        self.device.close()
        self.stereoControl.close()
        self.monoControl.close()
        self.colorControl.close()
        self.dataQueue.close()

    def startCapture(self) -> None:
        if not self.deviceOpen:
            print('CamDepthAi:start', 'device is not open')
            return
        if self.capturing: return
        self.dataCallbackId = self.dataQueue.addCallback(self.updateData)

    def stopCapture(self) -> None:
        if not self.capturing: return
        self.dataQueue.removeCallback(self.dataCallbackId)

    def updateData(self, daiMessages) -> None:
        self.updateFPS()
        if self.previewType == PreviewType.NONE:
            return
        if len(self.frameCallbacks) == 0:
            return

        video_frame:  np.ndarray | None = None
        stereo_frame: np.ndarray | None = None
        mono_frame:   np.ndarray | None = None
        mask_frame:   np.ndarray | None = None
        masked_frame: np.ndarray | None = None
        detections: list[dai.NNData] | None = None
        tracklets: list[dai.Tracklet] | None = None

        for name, msg in daiMessages:
            if name == 'video':
                video_frame = msg.getCvFrame() #type:ignore
                self.updateColorControl(msg)
            elif name == 'stereo':
                stereo_frame = self.updateStereo(msg.getCvFrame()) #type:ignore
                self.updateMonoControl(msg)
            elif name == 'mono':
                mono_frame = msg.getCvFrame() #type:ignore
            elif name == 'detection':
                detections = msg.detections
                self.numDetections = len(msg.detections)
            elif name == 'tracklets':
                tracklets = msg.tracklets
                self.numTracklets = len(msg.tracklets)
                pass
            else:
                print('unknown message', name)

        if stereo_frame is not None:
            mask_frame = self.updateMask(stereo_frame)
            stereo_frame = cv2.applyColorMap(stereo_frame, cv2.COLORMAP_JET)

        if video_frame is not None and mask_frame is not None:
            masked_frame = self.applyMask(video_frame, mask_frame)

        return_frame: np.ndarray = self.errorFrame
        if self.previewType == PreviewType.VIDEO and video_frame is not None:
            return_frame = video_frame
        if self.previewType == PreviewType.MONO and mono_frame is not None:
            return_frame = cv2.cvtColor(mono_frame, cv2.COLOR_GRAY2RGB)  # type: ignore
        if self.previewType == PreviewType.STEREO and stereo_frame is not None:
            return_frame = stereo_frame
        if self.previewType == PreviewType.MASK and mask_frame is not None:
            return_frame = cv2.cvtColor(mask_frame, cv2.COLOR_GRAY2RGB)  # type: ignore
        if self.previewType == PreviewType.MASKED and masked_frame is not None:
            return_frame = masked_frame

        return_frame = self.flip(return_frame)

        for c in self.frameCallbacks:
            c(return_frame)

        for c in self.trackerCallbacks:
            c(tracklets)

    def updateStereo(self, frame: np.ndarray) -> np.ndarray:
        return (frame * (255 / 95)).astype(np.uint8)

    def updateMask(self, frame: np.ndarray) -> np.ndarray:
        min: int = self.depthTresholdMin
        max: int = self.depthTresholdMax
        _, binary_mask = cv2.threshold(frame, min, max, cv2.THRESH_BINARY)
        return binary_mask

    def applyMask(self, color: np.ndarray, mask: np.ndarray) -> np.ndarray:
        # resize color to mask size
        color = fit(color, mask.shape[1], mask.shape[0])

        return cv2.bitwise_and(color, color, mask=mask)

    def flip(self, frame: np.ndarray) -> np.ndarray:
        if self.flipH and self.flipV:
            return cv2.flip(frame, -1)
        if self.flipH:
            return cv2.flip(frame, 1)
        if self.flipV:
            return cv2.flip(frame, 0)
        return frame

    def iscapturing(self) ->bool:
        return self.capturing

    def isOpen(self) -> bool:
        return self.deviceOpen

    # GENERAL SETTINGS
    def setPreview(self, value: PreviewType | int | str) -> None:
        if isinstance(value, str) and value in PreviewTypeNames:
            self.previewType = PreviewType(PreviewTypeNames.index(value))
        else:
            self.previewType = PreviewType(value)

    def setFlipH(self, flipH: bool) -> None:
        self.flipH = flipH

    def setFlipV(self, flipV: bool) -> None:
        self.flipV = flipV

    # COLOR SETTINGS
    def updateColorControl(self, frame) -> None:
        if (self.colorAutoExposure):
            self.colorExposure = frame.getExposureTime().total_seconds() * 1000000
            self.colorIso = frame.getSensitivity()
        if (self.colorAutoFocus):
            self.colorFocus = frame.getLensPosition()
        if (self.colorAutoBalance):
            self.colorBalance = frame.getColorTemperature()

    def setColorAutoExposure(self, value) -> None:
        if not self.deviceOpen: return
        self.colorAutoExposure = value
        if value == False:
            self.setExposureIso(self.colorExposure, self.colorIso)
            return
        ctrl = dai.CameraControl()
        ctrl.setAutoExposureEnable()
        self.colorControl.send(ctrl)

    def setColorAutoBalance(self, value) -> None:
        if not self.deviceOpen: return
        self.colorAutoBalance = value
        if value == False:
            self.setColorBalance(self.colorBalance)
            return
        ctrl = dai.CameraControl()
        ctrl.setAutoWhiteBalanceMode(dai.CameraControl.AutoWhiteBalanceMode.AUTO)
        self.colorControl.send(ctrl)

    def setExposureIso(self, exposure: int, iso: int) -> None:
        if not self.deviceOpen: return
        self.colorAutoExposure = False
        self.colorExposure = int(clamp(exposure, exposureRange))
        self.colorIso = int(clamp(iso, isoRange))
        ctrl = dai.CameraControl()
        ctrl.setManualExposure(self.colorExposure, self.colorIso)
        self.colorControl.send(ctrl)

    def setColorExposure(self, value : int) -> None:
        self.setExposureIso(value, self.colorIso)

    def setColorIso(self, value: int) -> None:
        self.setExposureIso(self.colorExposure, value)

    def setColorBalance(self, value: int) -> None:
        if not self.deviceOpen: return
        self.colorAutoBalance = False
        ctrl = dai.CameraControl()
        self.colorBalance = int(clamp(value, balanceRange))
        ctrl.setManualWhiteBalance(self.colorBalance)
        self.colorControl.send(ctrl)

    def setColorContrast(self, value: int) -> None:
        if not self.deviceOpen: return
        ctrl = dai.CameraControl()
        self.colorContrast = int(clamp(value, contrastRange))
        ctrl.setContrast(self.colorContrast)
        self.colorControl.send(ctrl)

    def setColorBrightness(self, value: int) -> None:
        if not self.deviceOpen: return
        ctrl = dai.CameraControl()
        self.colorBrightness = int(clamp(value, brightnessRange))
        ctrl.setBrightness(self.colorBrightness)
        self.colorControl.send(ctrl)

    def setColorDenoise(self, value: int) -> None:
        if not self.deviceOpen: return
        ctrl = dai.CameraControl()
        self.colorLumaDenoise = int(clamp(value, lumaDenoiseRange))
        ctrl.setLumaDenoise(self.colorLumaDenoise)
        self.colorControl.send(ctrl)

    def setColorSaturation(self, value: int) -> None:
        if not self.deviceOpen: return
        ctrl = dai.CameraControl()
        self.colorSaturation = int(clamp(value, saturationRange))
        ctrl.setSaturation(self.colorSaturation)
        self.colorControl.send(ctrl)

    def setColorSharpness(self, value: int) -> None:
        if not self.deviceOpen: return
        ctrl = dai.CameraControl()
        self.colorSharpness = int(clamp(value, sharpnessRange))
        ctrl.setSharpness(self.colorSharpness)
        self.colorControl.send(ctrl)

    # MONO SETTINGS
    def updateMonoControl(self, frame) -> None:
        if (self.monoAutoExposure):
            self.monoExposure = frame.getExposureTime().total_seconds() * 1000000
            self.monoIso = frame.getSensitivity()

    def setMonoAutoExposure(self, value) -> None:
        if not self.deviceOpen: return
        self.monoAutoExposure = value
        if value == False:
            self.setMonoExposureIso(self.monoExposure, self.monoIso)
            return
        ctrl = dai.CameraControl()
        ctrl.setAutoExposureEnable()
        self.monoControl.send(ctrl)

    def setMonoExposureIso(self, exposure: int, iso: int) -> None:
        if not self.deviceOpen: return
        self.monoAutoExposure = False
        self.monoExposure = int(clamp(exposure, exposureRange))
        self.monoIso = int(clamp(iso, isoRange))
        ctrl = dai.CameraControl()
        ctrl.setManualExposure(self.monoExposure, self.monoIso)
        self.monoControl.send(ctrl)

    def setMonoExposure(self, value : int) -> None:
        self.setMonoExposureIso(value, self.monoIso)

    def setMonoIso(self, value: int) -> None:
        self.setMonoExposureIso(self.monoExposure, value)

    # STEREO SETTINGS
    def setDepthTresholdMin(self, value: int) -> None:
        if not self.deviceOpen: return
        v: int = int(clamp(value, stereoDepthRange))
        self.stereoConfig.postProcessing.thresholdFilter.minRange = int(v)
        self.stereoControl.send(self.stereoConfig)

    def setDepthTresholdMax(self, value: int) -> None:
        if not self.deviceOpen: return
        v: int = int(clamp(value, stereoDepthRange))
        self.stereoConfig.postProcessing.thresholdFilter.maxRange = int(v)
        self.stereoControl.send(self.stereoConfig)

    def setStereoMinBrightness(self, value: int) -> None:
        if not self.deviceOpen: return
        v: int = int(clamp(value, stereoBrightnessRange))
        self.stereoConfig.postProcessing.brightnessFilter.minBrightness = int(v)
        self.stereoControl.send(self.stereoConfig)

    def setStereoMaxBrightness(self, value: int) -> None:
        if not self.deviceOpen: return
        v: int = int(clamp(value, stereoBrightnessRange))
        self.stereoConfig.postProcessing.brightnessFilter.maxBrightness = int(v)
        self.stereoControl.send(self.stereoConfig)

    def setStereoMedianFilter(self, value: StereoMedianFilterType | int | str) -> None:
        if not self.deviceOpen: return
        if isinstance(value, str):
            if value in StereoMedianFilterTypeNames:
                self.setStereoMedianFilter(StereoMedianFilterType(StereoMedianFilterTypeNames.index(value)))
            else:
                print('setStereoMedianFilter wrong type', value)
            return

        if value == StereoMedianFilterType.OFF:
            self.stereoConfig.postProcessing.median = dai.MedianFilter.MEDIAN_OFF
        elif value == StereoMedianFilterType.KERNEL_3x3:
            self.stereoConfig.postProcessing.median = dai.MedianFilter.KERNEL_3x3
        elif value == StereoMedianFilterType.KERNEL_5x5:
            self.stereoConfig.postProcessing.median = dai.MedianFilter.KERNEL_5x5
        elif value == StereoMedianFilterType.KERNEL_7x7:
            self.stereoConfig.postProcessing.median = dai.MedianFilter.KERNEL_7x7
        self.stereoControl.send(self.stereoConfig)

    # IR SETTINGS
    def setIrFloodLight(self, value: float) -> None:
        if not self.deviceOpen: return
        v: float = clamp(value, (0.0, 1.0))
        self.device.setIrFloodLightIntensity(v)

    def setIrGridLight(self, value: float) -> None:
        if not self.deviceOpen: return
        v: float = clamp(value, (0.0, 1.0))
        self.device.setIrLaserDotProjectorIntensity(v)

    # CALLBACKS
    def addFrameCallback(self, callback) -> None:
        self.frameCallbacks.add(callback)
    def discardFrameCallback(self, callback) -> None:
        self.frameCallbacks.discard(callback)
    def clearFrameCallbacks(self) -> None:
        self.frameCallbacks.clear()

    def addTrackerCallback(self, callback) -> None:
        self.trackerCallbacks.add(callback)
    def discardTrackerCallback(self, callback) -> None:
        self.trackerCallbacks.discard(callback)
    def clearTrackerCallbacks(self) -> None:
        self.trackerCallbacks.clear()

    # FPS
    def updateFPS(self) -> None:
        self.fps_counter.processed()
    def getFPS(self) -> float:
        return self.fps_counter.get_rate_average()













