"""Cell graph edges represent cell relationships with their instance details."""

import json
import re

from sqlalchemy.engine import Engine
from sqlmodel import Session
from starlette.requests import Request

from maskyard import Cell, kdb
from maskyard.engine import create_db_and_tables
from maskyard.web.app import app, cell_page


def test_cell_graph_groups_instances_by_parent_and_child(test_engine: Engine) -> None:
    create_db_and_tables()
    with Session(test_engine) as session:
        parent = Cell(name="parent")
        child = Cell(name="child")
        leaf = Cell(name="leaf")
        parent.add_instance(child, name="first")
        parent.add_instance(child, name="second", trans=kdb.Trans(200, 0))
        child.add_instance(leaf, name="leaf instance")
        session.add_all([parent, child, leaf])
        session.commit()
        child_id = child.id
        parent_id = parent.id

    request = Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": f"/cells/{child_id}",
            "root_path": "",
            "headers": [],
            "query_string": b"",
        }
    )
    response = cell_page(request, child_id)
    assert response.status_code == 200
    graph_json = re.search(
        r'<script id="graph-data" type="application/json">(.*?)</script>',
        response.body.decode(),
    )
    assert graph_json is not None
    graph = json.loads(graph_json.group(1))
    edges = [element["data"] for element in graph if "source" in element["data"]]

    assert len(edges) == 2
    parent_edge = next(edge for edge in edges if edge["source"] == str(parent_id))
    assert parent_edge["target"] == str(child_id)
    assert parent_edge["countLabel"] == "2 instances"
    assert [instance["label"] for instance in parent_edge["instances"]] == [
        "first",
        "second",
    ]
    assert [instance["x"] for instance in parent_edge["instances"]] == [0, 200]
    assert len({instance["id"] for instance in parent_edge["instances"]}) == 2
    leaf_edge = next(edge for edge in edges if edge["source"] == str(child_id))
    assert leaf_edge["countLabel"] == ""
    assert [instance["label"] for instance in leaf_edge["instances"]] == [
        "leaf instance"
    ]
