from modules.Settings import Settings
from modules.cam.DepthCam import DepthCam, DepthSimulator
from modules.cam.recorder.SyncRecorderGui import SyncRecorderGui as Recorder
from modules.cam.depthplayer.SyncPlayerGui import SyncPlayerGui as Player, HwAccelerationType
from modules.render.Render import Render
from modules.gui.PyReallySimpleGui import Gui
from modules.person.pose.PoseDetection import ModelType
from modules.person.Manager import Manager

from modules.cam.depthcam.Definitions import FrameType
from modules.cam.depthcam.Pipeline import get_frame_types

import os
from enum import Enum
import time


class DepthPose():
    def __init__(self, settings: Settings) -> None:

        frame_types: list[FrameType] = get_frame_types(settings.color, settings.stereo, settings.show_stereo)
        num_cameras: int = len(settings.camera_list)

        self.gui = Gui('DepthPose', settings.file_path, 'default')
        self.render = Render(num_cameras, settings.num_players, 1280, 720 + 256, 'Depth Pose', fullscreen=False, v_sync=True)

        self.recorder = Recorder(self.gui, settings, num_cameras, frame_types)
        self.player: Player = Player(settings.video_path, num_cameras, frame_types, HwAccelerationType.CPU)

        self.cameras: list[DepthCam | DepthSimulator] = []
        if settings.simulation or settings.passthrough:
            for cam_id in settings.camera_list:
                self.cameras.append(DepthSimulator(self.gui, self.player, cam_id, settings))
        else:
            for cam_id in settings.camera_list:
                camera = DepthCam(self.gui, cam_id, settings)
                self.cameras.append(camera)

        if len(self.cameras) == 0:
            print('No cameras available')

        modelType: ModelType = ModelType.LIGHTNING if settings.lightning else ModelType.THUNDER
        if not settings.pose:
            modelType = ModelType.NONE
        self.detector = Manager(settings.num_players, num_cameras, settings.model_path, modelType)

        self.running: bool = False


    def start(self) -> None:
        self.render.exit_callback = self.stop
        self.render.addKeyboardCallback(self.render_keyboard_callback)
        self.render.start()

        for camera in self.cameras:
            camera.start()
            camera.add_preview_callback(self.detector.set_image)
            camera.add_preview_callback(self.render.set_cam_image)
            camera.add_tracker_callback(self.detector.add_tracklet)
            camera.add_tracker_callback(self.render.add_tracklet)
            for T in self.recorder.types:
                camera.add_frame_callback(T, self.recorder.add_frame)
                camera.add_fps_callback(self.recorder.set_fps)

        self.detector.start()
        self.detector.addCallback(self.render.add_person)

        self.player.start()

        self.gui.exit_callback = self.stop

        for camera in self.cameras:
            self.gui.addFrame([camera.gui.get_gui_color_frame(), camera.gui.get_gui_depth_frame()])
        self.gui.addFrame([self.recorder.get_gui_frame(), self.player.get_gui_frame()])
        self.gui.start()
        self.gui.bringToFront()

        for camera in self.cameras:
            camera.gui.gui_check()
        self.recorder.gui_check() # start after gui to prevent record at startup
        self.recorder.start()

        self.running = True

    def stop(self) -> None:
        self.player.clearFrameCallbacks()
        self.player.stop()
        self.player.join()

        for camera in self.cameras:
            camera.stop()

        self.detector.stop()
        self.recorder.stop()

        self.gui.exit_callback = None
        self.gui.stop()

        self.detector.join()
        self.recorder.join()
        for camera in self.cameras:
            camera.join()


        self.render.exit_callback = None
        self.render.stop()
        # self.render.join()

        self.running = False

    def isRunning(self) -> bool :
        return self.running

    def render_keyboard_callback(self, key, x, y) -> None:
        if not  self.isRunning(): return
        if key == b'g' or key == b'G':
            if not self.gui or not self.gui.isRunning(): return
            self.gui.bringToFront()
