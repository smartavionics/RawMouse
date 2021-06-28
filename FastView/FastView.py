# Copyright (c) 2015 Ultimaker B.V.
# Uranium is released under the terms of the LGPLv3 or higher.

from UM.Resources import Resources

from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator

from UM.View.GL.OpenGL import OpenGL

from cura.CuraView import CuraView
from cura.Scene.ConvexHullNode import ConvexHullNode

## Standard view for mesh models.

class FastView(CuraView):
    def __init__(self):
        super().__init__(parent = None, use_empty_menu_placeholder = True)

        self._shader = None

    def beginRendering(self):
        scene = self.getController().getScene()
        renderer = self.getRenderer()

        if not self._shader:
            self._shader = OpenGL.getInstance().createShaderProgram(Resources.getPath(Resources.Shaders, "object.shader"))

        for node in DepthFirstIterator(scene.getRoot()):
            if type(node) is ConvexHullNode:
                continue
            if not node.render(renderer):
                if node.getMeshData() and node.isVisible() and not node.callDecoration("isNonPrintingMesh"):
                    renderer.queueNode(node, shader = self._shader)

    def endRendering(self):
        pass
