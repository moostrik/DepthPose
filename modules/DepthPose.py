
from modules.cam.DepthCam import DepthCam
from modules.render.Render import Render
from modules.gui.PyReallySimpleGui import Gui
from modules.pose.PoseDetection import ModelType
from modules.person.Manager import Person, PersonCallback, Manager

import os
from enum import Enum

class CamType(Enum):
    DEPTH   = 1
    VIMBA   = 2
    WEB     = 3
    IMAGE   = 4

class DepthPose():
    def __init__(self, path: str, fps: int, numPlayers: int, color: bool, stereo: bool, person: bool, lowres: bool, showLeft: bool, lightning: bool, noPose:bool) -> None:
        self.path: str =    path
        modelPath: str =    os.path.join(path, 'models')
        self.noPose: bool = noPose

        self.gui = Gui('DepthPose', os.path.join(path, 'files'), 'default')
        self.render = Render(1, numPlayers, 1280, 720 + 256, 'Depth Pose', fullscreen=False, v_sync=True)
        self.camera = DepthCam(self.gui, modelPath, fps, color, stereo, person, lowres, showLeft)

        modelType: ModelType = ModelType.LIGHTNING if lightning else ModelType.THUNDER
        if self.noPose:
            modelType = ModelType.NONE
        # self.detector = PoseDetection(modelPath, ModelType.LIGHTNING if lightning else ModelType.THUNDER)

        self.detector = Manager(max_persons=numPlayers, num_cams=1, model_path=modelPath, model_type=modelType)

        self.running: bool = False

    def start(self) -> None:
        self.render.exit_callback = self.stop
        self.render.addKeyboardCallback(self.render_keyboard_callback)
        self.render.start()

        self.camera.open()
        self.camera.startCapture()
        self.camera.addFrameCallback(self.detector.set_image)
        self.camera.addFrameCallback(self.render.set_cam_image)
        self.camera.addTrackerCallback(self.detector.add_tracklet)
        self.camera.addTrackerCallback(self.render.add_tracklet)

        self.detector.start()
        self.detector.addCallback(self.render.add_person)

        self.gui.exit_callback = self.stop
        self.gui.addFrame([self.camera.get_gui_color_frame(), self.camera.get_gui_depth_frame()])
        self.gui.start()
        self.gui.bringToFront()

        self.running = True

    def stop(self) -> None:
        self.detector.stop()
        self.detector.clearCallbacks()

        self.camera.stopCapture()
        self.camera.clearFrameCallbacks()
        self.camera.close()

        self.render.exit_callback = None
        self.render.stop()

        self.gui.exit_callback = None
        self.gui.stop()

        self.running = False

    def isRunning(self) -> bool :
        return self.running

    def render_keyboard_callback(self, key, x, y) -> None:
        if not  self.isRunning(): return
        if key == b'g' or key == b'G':
            if not self.gui or not self.gui.isRunning(): return
            self.gui.bringToFront()
