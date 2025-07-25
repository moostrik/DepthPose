# Standard library imports
import numpy as np

# Third-party imports

# Local application imports
from modules.gl.Mesh import Mesh
from modules.pose.PoseDefinitions import Pose, PosePoints, PoseEdgeIndices
from modules.render.DataManager import DataManager
from modules.render.renders.BaseRender import BaseRender, Rect

class PoseMeshes(BaseRender):
    """Methods for updating meshes based on pose data."""
    def __init__(self, data: DataManager, amount: int) -> None:
        self.data: DataManager = data
        self.amount: int = amount
        self.meshes: dict[int, Mesh] = {}

    def allocate(self) -> None:
        for i in range(self.amount):
            if i not in self.meshes:
                mesh = Mesh()
                mesh.allocate()
                mesh.set_indices(PoseEdgeIndices)
                self.meshes[i] = mesh

    def deallocate(self) -> None:
        for mesh in self.meshes.values():
            mesh.deallocate()
        self.meshes.clear()

    def draw(self, rect: Rect) -> None:
        pass

    def update(self) -> None:
        for id in range(self.amount):
            pose: Pose | None = self.data.get_pose(id, True, self.key())
            pose_mesh: Mesh | None = self.meshes.get(id, None)
            if pose is not None and pose_mesh is not None:
                points: PosePoints | None = pose.points
                if points is not None:
                    pose_mesh.set_vertices(points.getVertices())
                    pose_mesh.set_colors(points.getColors(threshold=0.0))
                    pose_mesh.update()