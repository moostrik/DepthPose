from OpenGL.GL import * # type: ignore
import OpenGL.GLUT as glut
from threading import Lock
import numpy as np
from enum import Enum

from modules.gl.RenderWindow import RenderWindow
from modules.gl.Texture import Texture
from modules.gl.Fbo import Fbo, SwapFbo
from modules.gl.Mesh import Mesh
from modules.gl.Utils import lfo, fit, fill

# from modules.cam.DepthAi.Definitions import Tracklet, Tracklets

from depthai import Tracklet
from modules.pose.PoseDefinitions import Pose, PoseIndicesFlat
from modules.person.Person import Person


class ImageType(Enum):
    CAM1 = 0
    CAM2 = 0
    CAM3 = 0
    CAM4 = 0
    POSE = 1

class MeshType(Enum):
    POSE_0 = 0
    POSE_1 = 1


def draw_tracklet(tracklet: Tracklet, x: float, y: float, w: float, h: float) -> None:
    if tracklet.status == Tracklet.TrackingStatus.REMOVED:
        return

    x = x + tracklet.roi.x * w
    y = y + tracklet.roi.y * h
    w = tracklet.roi.width * w
    h = tracklet.roi.height * h

    r: float = 1.0
    g: float = 1.0
    b: float = 1.0
    a: float = min(tracklet.age / 100.0, 0.33)
    if tracklet.status == Tracklet.TrackingStatus.NEW:
        r, g, b, a = (1.0, 1.0, 1.0, 1.0)
    if tracklet.status == Tracklet.TrackingStatus.TRACKED:
        r, g, b, a = (0.0, 1.0, 0.0, a)
    if tracklet.status == Tracklet.TrackingStatus.LOST:
        r, g, b, a = (1.0, 0.0, 0.0, a)
    if tracklet.status == Tracklet.TrackingStatus.REMOVED:
        r, g, b, a = (1.0, 0.0, 0.0, 1.0)

    string: str = f'ID: {tracklet.id} Age: {tracklet.age} C: {tracklet.srcImgDetection.confidence:.2f}'
    if tracklet.spatialCoordinates.z > 0:
        string += f' Z: {tracklet.spatialCoordinates.z:.0f}'

    glColor4f(r, g, b, a)   # Set color
    glBegin(GL_QUADS)       # Start drawing a quad
    glVertex2f(x, y)        # Bottom left
    glVertex2f(x, y + h)    # Bottom right
    glVertex2f(x + w, y + h)# Top right
    glVertex2f(x + w, y)    # Top left
    glEnd()                 # End drawing
    glColor4f(1.0, 1.0, 1.0, 1.0)  # Reset color
    glFlush()               # Render now

    x += 9
    y += 15
    glRasterPos2f(x, y)     # Set position
    for character in string:
        glut.glutBitmapCharacter(glut.GLUT_BITMAP_9_BY_15, ord(character)) # type: ignore
    glRasterPos2f(0, 0)     # Reset position


class Render(RenderWindow):
    def __init__(self, window_width: int, window_height: int, name: str, fullscreen: bool = False, v_sync = False) -> None:
        super().__init__(window_width, window_height, name, fullscreen, v_sync)

        self.input_mutex: Lock = Lock()

        self.width: int = window_width
        self.height: int = window_height

        self._images: dict[ImageType, np.ndarray | None] = {}
        self.textures: dict[ImageType, Texture] = {}
        self.input_tracklets: dict[ImageType, dict[int, Tracklet]] = {}

        for image_type in ImageType:
            self._images[image_type] = None
            self.textures[image_type] = Texture()
            self.input_tracklets[image_type] = {}


        self._vertices: dict[MeshType, np.ndarray | None] = {}
        self._colors: dict[MeshType, np.ndarray | None] = {}
        self.meshes: dict[MeshType, Mesh] = {}
        for mesh_type in MeshType:
            self._vertices[mesh_type] = None
            self._colors[mesh_type] = None
            self.meshes[mesh_type] = Mesh()
            self.meshes[mesh_type].set_indices(PoseIndicesFlat)

        self.fbos: list[Fbo | SwapFbo] = []


    def allocate(self) -> None:
        for fbo in self.fbos: fbo.allocate(self.width, self.height, GL_RGBA32F)
        for mesh in self.meshes.values(): mesh.allocate()

    def draw(self) -> None: # override
        if not self.is_allocated: self.allocate()

        self.update_textures()
        self.update_meshes()

        self.draw_video(ImageType.CAM1)


    def draw_in_fbo(self, tex: Texture | Fbo | SwapFbo, fbo: Fbo | SwapFbo) -> None:
        self.setView(fbo.width, fbo.height, False, True)
        fbo.begin()
        tex.draw(0, 0, fbo.width, fbo.height)
        fbo.end()

    def draw_video(self, type: ImageType) -> None:
        self.setView(self.window_width, self.window_height)
        tex: Texture = self.textures[type]
        if tex.width == 0 or tex.height == 0:
            return

        x, y, w, h = fit(tex.width, tex.height, self.window_width, self.window_height)
        self.textures[type].draw(x, 0, w, h)

        # self.half_fps_tracker = not self.half_fps_tracker
        tracklets: dict[int, Tracklet] = self.get_tracklets(type)
        for tracklet in tracklets.values():
            draw_tracklet(tracklet, x, 0, w, h)

        if  self.meshes[MeshType.POSE_0].isInitialized():
            self.meshes[MeshType.POSE_0].draw(x, 0, w, h)

        self.textures[ImageType.POSE].draw(0, h, 256, 256)


    def update_textures(self) -> None:
        for image_type in ImageType:
            image: np.ndarray | None = self.get_image(image_type)
            texture: Texture = self.textures[image_type]
            if image is not None:
                texture.set_from_image(image)

    def set_image(self, type: ImageType, image: np.ndarray) -> None :
        with self.input_mutex:
            self._images[type] = image
    def get_image(self, type: ImageType) -> np.ndarray | None :
        with self.input_mutex:
            ret_image: np.ndarray | None = self._images[type]
            self._images[type] = None
            return ret_image

    def update_meshes(self) -> None:
        for mesh_type in MeshType:
            vertices: np.ndarray | None = self.get_vertices(mesh_type)
            mesh: Mesh = self.meshes[mesh_type]
            if vertices is not None:
                mesh.set_vertices(vertices)
            colors: np.ndarray | None = self.get_colors(mesh_type)
            if colors is not None:
                mesh.set_colors(colors)

    def set_vertices(self, type: MeshType, vertices: np.ndarray) -> None:
        with self.input_mutex:
            self._vertices[type] = vertices

    def get_vertices(self, type: MeshType) -> np.ndarray | None:
        with self.input_mutex:
            ret_vertices: np.ndarray | None = self._vertices[type]
            self._vertices[type] = None
            return ret_vertices

    def set_colors(self, type: MeshType, colors: np.ndarray) -> None:
        with self.input_mutex:
            self._colors[type] = colors

    def get_colors(self, type: MeshType) -> np.ndarray | None:
        with self.input_mutex:
            ret_colors: np.ndarray | None = self._colors[type]
            self._colors[type] = None
            return ret_colors


    def set_camera_image(self, ID: int, image: np.ndarray) -> None :
        self.set_image(ImageType(ID), image)

    def get_tracklets(self, id: ImageType, clearTracklets: bool = False) -> dict[int, Tracklet]:
        with self.input_mutex:
            ret_person: dict[int, Tracklet] =  self.input_tracklets[id].copy()
            if clearTracklets:
                self.input_tracklets[id].clear()
            return ret_person

    def add_tracklet(self, ID: int, tracklet: Tracklet) -> None :
        with self.input_mutex:
            if ID < 4:
                type: ImageType = ImageType(ID)
                track_id: int = tracklet.id
                self.input_tracklets[type][track_id] = tracklet

    def set_detection(self, detection: Person) -> None:
        image: np.ndarray | None = detection.image
        if image is not None:
            self.set_image(ImageType.POSE, image)
            poses: list[Pose] | None = detection.pose
            if poses is not None and len(poses) > 0:
                self.set_vertices(MeshType.POSE_0, poses[0].getVertices())
                self.set_colors(MeshType.POSE_0, poses[0].getColors())