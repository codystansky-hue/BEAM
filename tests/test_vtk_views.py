"""Tests for trame_app/vtk_views.py — PyVista plotter functions."""

import os
import sys
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock pyvista before importing vtk_views
mock_pv_module = MagicMock()
sys.modules.setdefault("pyvista", mock_pv_module)
sys.modules.setdefault("vtk", MagicMock())

from trame_app.vtk_views import create_plotter, show_mesh_preview, show_deformed_beam, show_buckling_mode


class TestCreatePlotter:
    @patch("trame_app.vtk_views.pv")
    def test_creates_offscreen_plotter(self, mock_pv):
        mock_plotter = MagicMock()
        mock_pv.Plotter.return_value = mock_plotter

        result = create_plotter()

        mock_pv.Plotter.assert_called_once_with(off_screen=True)
        mock_plotter.set_background.assert_called_once_with("white")
        assert result is mock_plotter


class TestShowMeshPreview:
    @patch("trame_app.vtk_views.pv")
    def test_reads_and_adds_mesh(self, mock_pv):
        mock_plotter = MagicMock()
        mock_mesh = MagicMock()
        mock_pv.read.return_value = mock_mesh

        show_mesh_preview(mock_plotter, "/path/to/mesh.vtk")

        mock_plotter.clear.assert_called_once()
        mock_pv.read.assert_called_once_with("/path/to/mesh.vtk")
        mock_plotter.add_mesh.assert_called_once()
        call_kwargs = mock_plotter.add_mesh.call_args
        assert call_kwargs[1]["show_edges"] is True
        mock_plotter.view_xy.assert_called_once()
        mock_plotter.reset_camera.assert_called_once()


class TestShowDeformedBeam:
    @patch("trame_app.vtk_views.pv")
    def test_warps_by_displacement(self, mock_pv):
        mock_plotter = MagicMock()
        mock_mesh = MagicMock()
        mock_mesh.point_data = {"displacement": True}
        mock_warped = MagicMock()
        mock_mesh.warp_by_vector.return_value = mock_warped
        mock_pv.read.return_value = mock_mesh

        show_deformed_beam(mock_plotter, "/path/to/beam.vtk", warp_factor=5.0)

        mock_mesh.warp_by_vector.assert_called_once_with("displacement", factor=5.0)
        mock_plotter.add_mesh.assert_called_once()
        call_kwargs = mock_plotter.add_mesh.call_args
        assert call_kwargs[1]["scalars"] == "displacement_magnitude"
        assert call_kwargs[1]["cmap"] == "plasma"

    @patch("trame_app.vtk_views.pv")
    def test_fallback_without_displacement(self, mock_pv):
        mock_plotter = MagicMock()
        mock_mesh = MagicMock()
        mock_mesh.point_data = {}
        mock_pv.read.return_value = mock_mesh

        show_deformed_beam(mock_plotter, "/path/to/beam.vtk")

        mock_plotter.add_mesh.assert_called_once()
        call_kwargs = mock_plotter.add_mesh.call_args
        assert call_kwargs[1].get("color") == "lightblue"


class TestShowBucklingMode:
    @patch("trame_app.vtk_views.pv")
    def test_warps_by_mode_displacement(self, mock_pv):
        mock_plotter = MagicMock()
        mock_mesh = MagicMock()
        mock_mesh.point_data = {"displacement": True}
        mock_warped = MagicMock()
        mock_mesh.warp_by_vector.return_value = mock_warped
        mock_pv.read.return_value = mock_mesh

        show_buckling_mode(mock_plotter, "/path/to/mode.vtk", warp_factor=10.0)

        mock_mesh.warp_by_vector.assert_called_once_with("displacement", factor=10.0)

        mock_plotter.add_mesh.assert_called_once()
        call_kwargs = mock_plotter.add_mesh.call_args
        assert call_kwargs[1]["cmap"] == "coolwarm"
