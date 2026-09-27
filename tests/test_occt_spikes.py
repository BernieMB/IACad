"""Contrato experimental: OCCT expone historia de caras para el naming de Fase 2."""

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer


def test_occt_boolean_face_history_available():
    source = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    cutter = BRepPrimAPI_MakeCylinder(2, 10).Shape()
    operation = BRepAlgoAPI_Cut(source, cutter)
    operation.Build()
    assert operation.IsDone()

    history = operation.History()
    faces = TopExp_Explorer(source, TopAbs_FACE)
    found = 0
    modified = 0
    while faces.More():
        found += 1
        if history.Modified(faces.Current()).Size():
            modified += 1
        faces.Next()
    assert found == 6 and modified > 0
