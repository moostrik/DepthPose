
import depthai as dai
from datetime import timedelta
from pathlib import Path
from modules.cam.depthcam.Definitions import *

def get_frame_types(do_color: bool, do_stereo: bool, show_stereo) -> list[FrameType]:
    frame_types: list[FrameType] = [FrameType.NONE]
    if do_color:
        frame_types.append(FrameType.VIDEO)
    else:
        frame_types.append(FrameType.LEFT)
    if do_stereo:
        if do_color:
            frame_types.append(FrameType.LEFT)
        frame_types.append(FrameType.RIGHT)
        if show_stereo:
            frame_types.append(FrameType.STEREO)
    return frame_types

def get_stereo_config(do_color: bool) -> dai.RawStereoDepthConfig:
    stereoConfig: dai.RawStereoDepthConfig = dai.RawStereoDepthConfig()
    if do_color:
        stereoConfig.algorithmControl.depthAlign = dai.RawStereoDepthConfig.AlgorithmControl.DepthAlign.CENTER
    else:
        stereoConfig.algorithmControl.depthAlign = dai.RawStereoDepthConfig.AlgorithmControl.DepthAlign.RECTIFIED_LEFT
    return stereoConfig

def setup_pipeline(
    pipeline : dai.Pipeline,
    modelPath:str,
    fps: int = 30,
    doColor: bool = True,
    doStereo: bool = True,
    doPerson: bool = True,
    lowres: bool = False,
    showStereo: bool = False
    ) -> None:

    options: list[str] = [
        'Color' if doColor else 'Mono',
        'Stereo' if doStereo else '',
        'Yolo' if doPerson else '',
        'LowRes' if lowres else 'Highres',
        'showStereo' if showStereo else ''
    ]

    pipeline_description = "Depth Pipeline: " + " ".join(filter(None, options))
    print(pipeline_description)

    if doColor:
        if doStereo:
            if doPerson:
                SetupColorStereoPerson(pipeline, fps, lowres, showStereo, modelPath)
            else:
                SetupColorStereo(pipeline, fps, lowres, showStereo)
        else:
            if doPerson:
                SetupColorPerson(pipeline, fps, lowres, modelPath)
            else:
                SetupColor(pipeline, fps, lowres)
    else:
        if doStereo:
            if doPerson:
                SetupMonoStereoPerson(pipeline, fps, lowres, showStereo, modelPath)
            else:
                SetupMonoStereo(pipeline, fps, lowres, showStereo)
        else:
            if doPerson:
                SetupMonoPerson(pipeline, fps, lowres, modelPath)
            else:
                SetupMono(pipeline, fps, lowres)


class Setup():
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool = False) -> None:
        self.pipeline: dai.Pipeline = pipeline
        self.fps: int = fps
        self.lowres: bool = lowres

        self.sync: dai.node.Sync = pipeline.create(dai.node.Sync)
        syncThreshold = int(1250 / fps)
        self.sync.setSyncAttempts(2)
        self.sync.setSyncThreshold(timedelta(milliseconds=syncThreshold))

        # CONTROL INPUTS
        self.colorControl: dai.node.XLinkIn = pipeline.create(dai.node.XLinkIn)
        self.colorControl.setStreamName('color_control')

        self.monoControl: dai.node.XLinkIn = pipeline.create(dai.node.XLinkIn)
        self.monoControl.setStreamName('mono_control')

        self.stereoControl: dai.node.XLinkIn = pipeline.create(dai.node.XLinkIn)
        self.stereoControl.setStreamName('stereo_control')

        # OUTPUTS
        self.outputImages: dai.node.XLinkOut = pipeline.create(dai.node.XLinkOut)
        self.outputImages.setStreamName("output_images")

        self.trackerOut: dai.node.XLinkOut = pipeline.create(dai.node.XLinkOut)
        self.trackerOut.setStreamName("tracklets")

        # LINKING
        self.sync.out.link(self.outputImages.input)


class SetupColor(Setup):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool) -> None:
        super().__init__(pipeline, fps, lowres)
        self.color: dai.node.Camera = pipeline.create(dai.node.Camera)
        self.color.setCamera("color")
        self.color.setSize(1280, 720)
        self.color.setFps(self.fps)
        self.color.setMeshSource(dai.CameraProperties.WarpMeshSource.NONE)
        self.color.video.link(self.sync.inputs["video"])

        self.colorControl.out.link(self.color.inputControl)

class SetupColorPerson(SetupColor):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool, model_path) -> None:
        super().__init__(pipeline, fps, lowres)

        self.manip: dai.node.ImageManip = pipeline.create(dai.node.ImageManip)
        self.manip.initialConfig.setResize(300, 300)
        self.manip.initialConfig.setKeepAspectRatio(False)
        self.manip.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
        self.color.video.link(self.manip.inputImage)

        self.detectionNetwork: dai.node.MobileNetDetectionNetwork = pipeline.create(dai.node.MobileNetDetectionNetwork)
        nnPathDefault: Path = (Path(model_path) / DETECTION_MODEL6S).resolve().absolute()
        self.detectionNetwork.setBlobPath(nnPathDefault)
        self.detectionNetwork.setConfidenceThreshold(DETECTION_THRESHOLD)
        self.detectionNetwork.setNumInferenceThreads(2)
        self.detectionNetwork.input.setBlocking(False)
        self.manip.out.link(self.detectionNetwork.input)

        self.objectTracker: dai.node.ObjectTracker = pipeline.create(dai.node.ObjectTracker)
        self.objectTracker.setDetectionLabelsToTrack([15])  # track only person
        self.objectTracker.setTrackerType(TRACKER_TYPE)
        self.objectTracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)

        if self.lowres:
            self.detectionNetwork.passthrough.link(self.objectTracker.inputTrackerFrame)
        else:
            self.color.video.link(self.objectTracker.inputTrackerFrame)
        self.detectionNetwork.passthrough.link(self.objectTracker.inputDetectionFrame)
        self.detectionNetwork.out.link(self.objectTracker.inputDetections)

        self.objectTracker.out.link(self.trackerOut.input)

class SetupColorStereo(SetupColor):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool, showStereo:bool) -> None:
        super().__init__(pipeline, fps, lowres)
        self.showStereo: bool = showStereo

        self.color.setMeshSource(dai.CameraProperties.WarpMeshSource.CALIBRATION)

        resolution: dai.MonoCameraProperties.SensorResolution = dai.MonoCameraProperties.SensorResolution.THE_720_P
        if lowres:
            resolution = dai.MonoCameraProperties.SensorResolution.THE_400_P

        self.left: dai.node.MonoCamera = pipeline.create(dai.node.MonoCamera)
        self.left.setCamera("left")
        self.left.setResolution(resolution)
        self.left.setFps(fps)

        self.right: dai.node.MonoCamera = pipeline.create(dai.node.MonoCamera)
        self.right.setCamera("right")
        self.right.setResolution(resolution)
        self.right.setFps(fps)

        self.stereo: dai.node.StereoDepth = pipeline.create(dai.node.StereoDepth)
        self.stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
        self.stereo.initialConfig.setMedianFilter(dai.MedianFilter.KERNEL_7x7)
        self.stereo.setLeftRightCheck(True)
        self.stereo.setExtendedDisparity(False)
        self.stereo.setSubpixel(False)
        self.stereo.setDepthAlign(dai.CameraBoardSocket.CENTER)

        self.left.out.link(self.stereo.left)
        self.right.out.link(self.stereo.right)

        if self.showStereo:
            self.stereo.disparity.link(self.sync.inputs["stereo"])
        self.stereo.rectifiedLeft.link(self.sync.inputs["left"])
        self.stereo.rectifiedRight.link(self.sync.inputs["right"])

        self.monoControl.out.link(self.left.inputControl)
        self.monoControl.out.link(self.right.inputControl)
        self.stereoControl.out.link(self.stereo.inputConfig)

class SetupColorStereoPerson(SetupColorStereo):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool, showStereo: bool, model_path) -> None:
        super().__init__(pipeline, fps, lowres, showStereo)

        self.manip: dai.node.ImageManip = pipeline.create(dai.node.ImageManip)
        self.manip.initialConfig.setResize(300, 300)
        self.manip.initialConfig.setKeepAspectRatio(False)
        self.manip.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
        self.color.video.link(self.manip.inputImage)

        self.detectionNetwork: dai.node.MobileNetSpatialDetectionNetwork = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
        nnPathDefault: Path = (Path(model_path) / DETECTION_MODEL5S).resolve().absolute()
        self.detectionNetwork.setBlobPath(nnPathDefault)
        self.detectionNetwork.setConfidenceThreshold(DETECTION_THRESHOLD)
        self.detectionNetwork.setNumInferenceThreads(2)
        self.detectionNetwork.setBoundingBoxScaleFactor(DEPTH_TRACKER_BOX_SCALE)
        self.detectionNetwork.setDepthLowerThreshold(DEPTH_TRACKER_MIN_DEPTH)
        self.detectionNetwork.setDepthUpperThreshold(DEPTH_TRACKER_MAX_DEPTH)
        self.detectionNetwork.input.setBlocking(False)
        self.manip.out.link(self.detectionNetwork.input)
        self.stereo.depth.link(self.detectionNetwork.inputDepth)

        self.objectTracker: dai.node.ObjectTracker = pipeline.create(dai.node.ObjectTracker)
        self.objectTracker.setDetectionLabelsToTrack([15])  # track only person
        self.objectTracker.setTrackerType(TRACKER_TYPE)
        self.objectTracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)

        self.detectionNetwork.passthrough.link(self.objectTracker.inputTrackerFrame)
        self.detectionNetwork.passthrough.link(self.objectTracker.inputDetectionFrame)
        self.detectionNetwork.out.link(self.objectTracker.inputDetections)

        self.objectTracker.out.link(self.trackerOut.input)


class SetupMono(Setup):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool) -> None:
        super().__init__(pipeline, fps, lowres)

        self.left: dai.node.MonoCamera = pipeline.create(dai.node.MonoCamera)
        self.resolution: dai.MonoCameraProperties.SensorResolution = dai.MonoCameraProperties.SensorResolution.THE_720_P
        if self.lowres:
            self.resolution = dai.MonoCameraProperties.SensorResolution.THE_400_P
        self.left.setCamera("left")
        self.left.setResolution(self.resolution)
        self.left.setFps(self.fps)

        self.left.out.link(self.sync.inputs["left"])

        self.monoControl.out.link(self.left.inputControl)

class SetupMonoPerson(SetupMono):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool, model_path:str) -> None:
        super().__init__(pipeline, fps, lowres)

        self.manip: dai.node.ImageManip = pipeline.create(dai.node.ImageManip)
        self.manip.initialConfig.setResize(300, 300)
        self.manip.initialConfig.setKeepAspectRatio(False)
        self.manip.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
        self.left.out.link(self.manip.inputImage)

        self.detectionNetwork: dai.node.MobileNetDetectionNetwork = pipeline.create(dai.node.MobileNetDetectionNetwork)
        nnPathDefault: Path = (Path(model_path) / DETECTION_MODEL6S).resolve().absolute()
        self.detectionNetwork.setBlobPath(nnPathDefault)
        self.detectionNetwork.setConfidenceThreshold(DETECTION_THRESHOLD)
        self.detectionNetwork.setNumInferenceThreads(2)
        self.detectionNetwork.input.setBlocking(False)
        self.manip.out.link(self.detectionNetwork.input)

        self.objectTracker: dai.node.ObjectTracker = pipeline.create(dai.node.ObjectTracker)
        self.objectTracker.setDetectionLabelsToTrack([15])  # track only person
        self.objectTracker.setTrackerType(TRACKER_TYPE)
        self.objectTracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)

        if self.lowres:
            self.manip.out.link(self.objectTracker.inputTrackerFrame)
        else:
            maxFrameSize = 1280 * 720 * 3
            self.manip2: dai.node.ImageManip = pipeline.create(dai.node.ImageManip)
            self.manip2.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
            self.manip2.initialConfig.setResize(1280, 720)
            self.manip2.initialConfig.setKeepAspectRatio(False)
            self.manip2.setMaxOutputFrameSize(maxFrameSize)
            self.left.out.link(self.manip2.inputImage)
            self.manip2.out.link(self.objectTracker.inputTrackerFrame)

        self.detectionNetwork.passthrough.link(self.objectTracker.inputDetectionFrame)
        self.detectionNetwork.out.link(self.objectTracker.inputDetections)

        self.objectTracker.out.link(self.trackerOut.input)

class SetupMonoStereo(SetupMono):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool, showStereo: bool) -> None:
        super().__init__(pipeline, fps, lowres)
        self.showStereo: bool = showStereo

        self.right: dai.node.MonoCamera = pipeline.create(dai.node.MonoCamera)
        self.right.setCamera("right")
        self.right.setResolution(self.resolution)
        self.right.setFps(fps)

        self.stereo: dai.node.StereoDepth = pipeline.create(dai.node.StereoDepth)
        self.stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
        self.stereo.initialConfig.setMedianFilter(dai.MedianFilter.KERNEL_7x7)
        self.stereo.setLeftRightCheck(True)
        self.stereo.setExtendedDisparity(False)
        self.stereo.setSubpixel(False)
        self.stereo.setDepthAlign(dai.CameraBoardSocket.LEFT)

        self.left.out.link(self.stereo.left)
        self.right.out.link(self.stereo.right)

        if self.showStereo:
            self.stereo.disparity.link(self.sync.inputs["stereo"])

        self.left.out.unlink(self.sync.inputs["left"])
        self.stereo.rectifiedLeft.link(self.sync.inputs["left"])
        self.stereo.rectifiedRight.link(self.sync.inputs["right"])

        self.monoControl.out.link(self.right.inputControl)
        self.stereoControl.out.link(self.stereo.inputConfig)

class SetupMonoStereoPerson(SetupMonoStereo):
    def __init__(self, pipeline : dai.Pipeline, fps: int, lowres: bool, showMono: bool, model_path:str) -> None:
        super().__init__(pipeline, fps, lowres, showMono)

        self.manip: dai.node.ImageManip = pipeline.create(dai.node.ImageManip)
        self.manip.initialConfig.setResize(300, 300)
        self.manip.initialConfig.setKeepAspectRatio(False)
        self.manip.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
        self.stereo.rectifiedLeft.link(self.manip.inputImage)

        self.detectionNetwork: dai.node.MobileNetSpatialDetectionNetwork = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
        nnPathDefault: Path = (Path(model_path) / DETECTION_MODEL5S).resolve().absolute()
        self.detectionNetwork.setBlobPath(nnPathDefault)
        self.detectionNetwork.setConfidenceThreshold(DETECTION_THRESHOLD)
        self.detectionNetwork.setNumInferenceThreads(2)
        self.detectionNetwork.setBoundingBoxScaleFactor(DEPTH_TRACKER_BOX_SCALE)
        self.detectionNetwork.setDepthLowerThreshold(DEPTH_TRACKER_MIN_DEPTH)
        self.detectionNetwork.setDepthUpperThreshold(DEPTH_TRACKER_MAX_DEPTH)
        self.detectionNetwork.input.setBlocking(False)
        self.manip.out.link(self.detectionNetwork.input)
        self.stereo.depth.link(self.detectionNetwork.inputDepth)

        self.objectTracker: dai.node.ObjectTracker = pipeline.create(dai.node.ObjectTracker)
        self.objectTracker.setDetectionLabelsToTrack([15])  # track only person
        self.objectTracker.setTrackerType(TRACKER_TYPE)
        self.objectTracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)

        self.detectionNetwork.passthrough.link(self.objectTracker.inputTrackerFrame)
        self.detectionNetwork.passthrough.link(self.objectTracker.inputDetectionFrame)
        self.detectionNetwork.out.link(self.objectTracker.inputDetections)

        self.objectTracker.out.link(self.trackerOut.input)