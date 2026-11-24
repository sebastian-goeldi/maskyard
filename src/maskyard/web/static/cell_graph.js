const elements = JSON.parse(document.getElementById("graph-data").textContent);
const selectedId = elements.find((element) => element.classes === "selected").data.id;
const parents = new Map();
const children = new Map();

for (const element of elements) {
  const { source, target } = element.data;
  if (source === undefined || target === undefined) continue;
  if (!parents.has(target)) parents.set(target, []);
  if (!children.has(source)) children.set(source, []);
  parents.get(target).push(source);
  children.get(source).push(target);
}

function distances(links) {
  const depth = new Map([[selectedId, 0]]);
  const queue = [selectedId];
  for (let index = 0; index < queue.length; index++) {
    const current = queue[index];
    for (const next of links.get(current) || []) {
      if (depth.has(next)) continue;
      depth.set(next, depth.get(current) + 1);
      queue.push(next);
    }
  }
  return depth;
}

function shade(near, far, depth) {
  const fraction = Math.min((depth - 1) / 4, 1);
  const channel = (hex, offset) => parseInt(hex.slice(offset, offset + 2), 16);
  return "#" + [1, 3, 5].map((offset) =>
    Math.round(channel(near, offset) * (1 - fraction) + channel(far, offset) * fraction)
      .toString(16).padStart(2, "0")
  ).join("");
}

const ancestorDepth = distances(parents);
const descendantDepth = distances(children);
for (const element of elements) {
  if (element.data.source !== undefined) continue;
  const { id } = element.data;
  if (id === selectedId) {
    element.data.fill = "#343a40";
    element.data.border = "#ffc107";
    element.data.relation = "Selected cell";
  } else if (ancestorDepth.has(id)) {
    const depth = ancestorDepth.get(id);
    element.data.fill = shade("#b02a37", "#6a1420", depth);
    element.data.border = element.data.fill;
    element.data.relation = `Ancestor, ${depth} step${depth === 1 ? "" : "s"} away`;
  } else if (descendantDepth.has(id)) {
    const depth = descendantDepth.get(id);
    element.data.fill = shade("#3166c4", "#071f4d", depth);
    element.data.border = element.data.fill;
    element.data.relation = `Descendant, ${depth} step${depth === 1 ? "" : "s"} away`;
  } else {
    element.data.fill = "#6c757d";
    element.data.border = element.data.fill;
    element.data.relation = "Cell";
  }
}

const graph = cytoscape({
  container: document.getElementById("cell-graph"),
  elements,
  style: [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "background-color": "data(fill)",
        "border-color": "data(border)",
        "border-width": 2,
        color: "#fff",
        "font-size": 12,
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "ellipsis",
        "text-max-width": 170,
        shape: "round-rectangle",
        width: 190,
        height: 52,
      },
    },
    { selector: "node.selected", style: { "border-width": 4 } },
    {
      selector: "edge",
      style: {
        label: "data(countLabel)",
        "font-size": 11,
        "text-background-color": "#fff",
        "text-background-opacity": 0.85,
        "text-background-padding": 2,
        width: 2,
        "line-color": "#adb5bd",
        "target-arrow-color": "#adb5bd",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
      },
    },
    {
      selector: "edge.highlighted",
      style: { "line-color": "#0d6efd", "target-arrow-color": "#0d6efd", width: 4 },
    },
  ],
  layout: {
    name: "breadthfirst",
    directed: true,
    avoidOverlap: true,
    nodeDimensionsIncludeLabels: true,
    padding: 40,
    spacingFactor: 1.75,
  },
});

const detail = document.getElementById("graph-detail");
const hint = detail.textContent;
let selectedEdge = null;

function showEdge(edge, showInstances) {
  const instances = edge.data("instances");
  const count = instances.length;
  const summary = `${edge.source().data("label")} → ${edge.target().data("label")}: ${count} instance${count === 1 ? "" : "s"}`;
  detail.textContent = showInstances ? summary : `${summary}; select the arrow to see every instance`;
  if (!showInstances) return;

  const list = document.createElement("ol");
  list.className = "graph-detail-list mb-0 mt-1";
  for (const instance of instances) {
    const item = document.createElement("li");
    const array = instance.na * instance.nb > 1 ? `, array ${instance.na} × ${instance.nb}` : "";
    item.textContent = `${instance.label} (#${instance.id}): (${instance.x}, ${instance.y}), ${instance.angle}°, mirror ${instance.mirror ? "yes" : "no"}${array}`;
    list.appendChild(item);
  }
  detail.appendChild(list);
}

function restoreDetail() {
  if (selectedEdge) showEdge(selectedEdge, true);
  else detail.textContent = hint;
}

function isSelected(edge) {
  return selectedEdge !== null && edge.id() === selectedEdge.id();
}

graph.on("mouseover", "node", (event) => {
  detail.textContent = `${event.target.data("label")} — ${event.target.data("relation")}; click to view this cell`;
});
graph.on("mouseover", "edge", (event) => {
  const edge = event.target;
  edge.addClass("highlighted");
  showEdge(edge, isSelected(edge));
});
graph.on("mouseout", "node, edge", (event) => {
  if (!isSelected(event.target)) event.target.removeClass("highlighted");
  restoreDetail();
});
graph.on("tap", "edge", (event) => {
  if (selectedEdge) selectedEdge.removeClass("highlighted");
  selectedEdge = event.target;
  selectedEdge.addClass("highlighted");
  showEdge(selectedEdge, true);
});
graph.on("tap", "node", (event) => {
  window.location.href = `/cells/${encodeURIComponent(event.target.id())}`;
});
document.getElementById("fit-graph").addEventListener("click", () => graph.fit(undefined, 40));
