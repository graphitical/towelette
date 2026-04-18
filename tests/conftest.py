from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory for testing."""
    return tmp_path


@pytest.fixture
def sample_pyproject(tmp_project: Path) -> Path:
    """Create a sample pyproject.toml with dependencies."""
    content = textwrap.dedent("""\
        [project]
        name = "my-cad-project"
        version = "0.1.0"
        dependencies = [
            "pythonocc-core>=7.9.0",
            "trimesh>=4.0.0",
            "numpy>=1.24.0",
            "pydantic>=2.0.0",
        ]

        [project.optional-dependencies]
        dev = [
            "pytest>=7.0.0",
            "potpourri3d>=1.4.0",
        ]
    """)
    p = tmp_project / "pyproject.toml"
    p.write_text(content)
    return p


@pytest.fixture
def sample_requirements(tmp_project: Path) -> Path:
    """Create a sample requirements.txt."""
    content = textwrap.dedent("""\
        pythonocc-core>=7.9.0
        trimesh>=4.0.0
        numpy>=1.24.0
        pydantic>=2.0.0
        # A comment line
        potpourri3d>=1.4.0
    """)
    p = tmp_project / "requirements.txt"
    p.write_text(content)
    return p


@pytest.fixture
def sample_environment_yml(tmp_project: Path) -> Path:
    """Create a sample environment.yml."""
    content = textwrap.dedent("""\
        name: my-cad-env
        channels:
          - conda-forge
          - defaults
        dependencies:
          - python=3.11
          - pythonocc-core=7.9.0
          - numpy
          - pip:
            - trimesh>=4.0.0
            - potpourri3d
    """)
    p = tmp_project / "environment.yml"
    p.write_text(content)
    return p


@pytest.fixture
def sample_python_files(tmp_project: Path) -> Path:
    """Create sample .py files with imports."""
    src = tmp_project / "src"
    src.mkdir()
    (src / "main.py").write_text(textwrap.dedent("""\
        import numpy as np
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCC.Core.gp import gp_Pnt
        import trimesh
        from potpourri3d import MeshHeatSolver
    """))
    (src / "utils.py").write_text(textwrap.dedent("""\
        import json
        from pathlib import Path
        from trimesh.base import Trimesh
    """))
    return tmp_project


@pytest.fixture
def sample_python_module(tmp_path: Path) -> Path:
    """Create a sample Python module for AST indexing."""
    content = textwrap.dedent('''\
        """A sample module for testing."""


        class MeshProcessor:
            """Processes mesh data."""

            def __init__(self, vertices, faces):
                self.vertices = vertices
                self.faces = faces

            def compute_normals(self):
                """Compute face normals."""
                return [(0, 0, 1)] * len(self.faces)

            def simplify(self, target_faces: int):
                """Reduce face count."""
                return self.faces[:target_faces]


        def load_mesh(path: str) -> MeshProcessor:
            """Load a mesh from file."""
            return MeshProcessor([], [])


        def _private_helper():
            pass
    ''')
    p = tmp_path / "sample_module.py"
    p.write_text(content)
    return p


@pytest.fixture
def sample_cpp_header(tmp_path: Path) -> Path:
    """Create a sample C++ header for tree-sitter indexing."""
    content = textwrap.dedent("""\
        #ifndef _BRepPrimAPI_MakeBox_HeaderFile
        #define _BRepPrimAPI_MakeBox_HeaderFile

        #include <Standard.hxx>
        #include <gp_Pnt.hxx>

        //! Builds a box solid, or a shell, or a half-space solid.
        class BRepPrimAPI_MakeBox : public BRepBuilderAPI_MakeShape
        {
        public:
            //! Make a box with a corner at 0,0,0 and the other dx,dy,dz
            Standard_EXPORT BRepPrimAPI_MakeBox(
                const Standard_Real dx,
                const Standard_Real dy,
                const Standard_Real dz);

            //! Make a box with corners P1 and P2
            Standard_EXPORT BRepPrimAPI_MakeBox(
                const gp_Pnt& P1,
                const gp_Pnt& P2);

            //! Returns the constructed box as a shell.
            Standard_EXPORT const TopoDS_Shell& Shell();

            //! Returns the constructed box as a solid.
            Standard_EXPORT const TopoDS_Solid& Solid();

        protected:
            BRepPrim_Wedge myWedge;

        private:
            Standard_Boolean myDone;
        };

        #endif
    """)
    p = tmp_path / "BRepPrimAPI_MakeBox.hxx"
    p.write_text(content)
    return p


@pytest.fixture
def sample_cmakelists(tmp_project: Path) -> Path:
    """Create a sample CMakeLists.txt with find_package and FetchContent."""
    content = textwrap.dedent("""\
        cmake_minimum_required(VERSION 3.20)
        project(MyGeomApp)

        find_package(Eigen3 REQUIRED)
        find_package(OpenGL REQUIRED)

        include(FetchContent)

        FetchContent_Declare(
            libigl
            GIT_REPOSITORY https://github.com/libigl/libigl.git
            GIT_TAG        v2.5.0
        )
        FetchContent_MakeAvailable(libigl)
    """)
    p = tmp_project / "CMakeLists.txt"
    p.write_text(content)
    return p


@pytest.fixture
def sample_conanfile_txt(tmp_project: Path) -> Path:
    """Create a sample conanfile.txt."""
    content = textwrap.dedent("""\
        [requires]
        eigen/3.4.0
        fmt/10.1.1
        # a comment
        boost/1.83.0@conan/stable

        [generators]
        CMakeDeps
        CMakeToolchain
    """)
    p = tmp_project / "conanfile.txt"
    p.write_text(content)
    return p


@pytest.fixture
def sample_vcpkg_json(tmp_project: Path) -> Path:
    """Create a sample vcpkg.json."""
    import json
    data = {
        "name": "my-geom-app",
        "version": "0.1.0",
        "dependencies": [
            "eigen3",
            {"name": "cgal", "version>=": "5.6"},
        ],
    }
    p = tmp_project / "vcpkg.json"
    p.write_text(json.dumps(data, indent=2))
    return p


@pytest.fixture
def sample_cpp_source_files(tmp_project: Path) -> Path:
    """Create sample C++ source files with #include directives."""
    src = tmp_project / "src"
    src.mkdir(exist_ok=True)
    (src / "main.cpp").write_text(textwrap.dedent("""\
        #include <Eigen/Dense>
        #include <igl/readOBJ.h>
        #include <vector>
        #include <iostream>

        int main() {
            Eigen::MatrixXd V;
            return 0;
        }
    """))
    (src / "mesh.h").write_text(textwrap.dedent("""\
        #pragma once
        #include <Eigen/Sparse>
        #include <nlohmann/json.hpp>
        #include <string>
    """))
    return tmp_project


@pytest.fixture
def towelette_dir(tmp_project: Path) -> Path:
    """Create a .towelette directory structure."""
    d = tmp_project / ".towelette"
    d.mkdir()
    (d / "chroma").mkdir()
    (d / "repos").mkdir()
    return d
