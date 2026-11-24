async function renderCellLayout() {
  const host = document.getElementById("cell-layout");
  const status = document.getElementById("layout-status");
  status.textContent = "Loading layout manifest…";
  const response = await fetch(document.getElementById("layout-source").dataset.url);
  if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
  const data = await response.json();
  const colors = ["#4fc3f7", "#ff8a80", "#81c784", "#ffd54f", "#ba68c8", "#4dd0e1"];
  const patterns = ["solid", ["*...", "....", "....", "...."],
    ["*.*.", ".*.*", "*.*.", ".*.*"],
    ["*.......", ".*......", "..*.....", "...*....",
      "....*...", ".....*..", "......*.", ".......*"]];
  function layerStyle(id) {
    const [number, datatype] = id.split("/").map(Number);
    const index = Math.abs(number * 17 + datatype * 31) % colors.length;
    const supplied = (data.layerStyles || {})[id] || {};
    return {
      frameColor: supplied.frameColor || colors[index],
      fillColor: supplied.fillColor || colors[index],
      frameWidth: supplied.frameWidth ?? 1,
      pattern: supplied.pattern || patterns[index % patterns.length],
      visible: supplied.visible ?? true,
    };
  }
  function patternCanvas(rows, color) {
    const canvas = document.createElement("canvas");
    canvas.width = rows[0].length;
    canvas.height = rows.length;
    const context = canvas.getContext("2d");
    const image = context.createImageData(canvas.width, canvas.height);
    const rgb = [1, 3, 5].map((offset) => parseInt(color.slice(offset, offset + 2), 16));
    for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
      const offset = (y * canvas.width + x) * 4;
      image.data.set([...rgb, rows[y][x] === "*" ? 255 : 0], offset);
    }
    context.putImageData(image, 0, 0);
    return canvas;
  }
  const stippleVertexGl = `
    precision highp float;
    in vec2 aPosition;
    out vec2 vTextureCoord;
    uniform vec4 uInputSize;
    uniform vec4 uOutputFrame;
    uniform vec4 uOutputTexture;
    void main() {
      vec2 position = aPosition * uOutputFrame.zw + uOutputFrame.xy;
      position.x = position.x * (2.0 / uOutputTexture.x) - 1.0;
      position.y = position.y * (2.0 * uOutputTexture.z / uOutputTexture.y) - uOutputTexture.z;
      gl_Position = vec4(position, 0.0, 1.0);
      vTextureCoord = aPosition * (uOutputFrame.zw * uInputSize.zw);
    }`;
  const stippleFragmentGl = `
    precision highp float;
    in vec2 vTextureCoord;
    out vec4 finalColor;
    uniform sampler2D uTexture;
    uniform sampler2D uPatternTexture;
    uniform vec2 uPatternSize;
    uniform vec4 uOutputTexture;
    void main() {
      vec2 pixel = floor(vec2(gl_FragCoord.x, uOutputTexture.y - gl_FragCoord.y));
      vec2 uv = (mod(pixel, uPatternSize) + 0.5) / uPatternSize;
      finalColor = texture(uTexture, vTextureCoord) * texture(uPatternTexture, uv).a;
    }`;
  const stippleWgsl = `
    struct GlobalFilterUniforms {
      uInputSize: vec4<f32>, uInputPixel: vec4<f32>, uInputClamp: vec4<f32>,
      uOutputFrame: vec4<f32>, uGlobalFrame: vec4<f32>, uOutputTexture: vec4<f32>,
    };
    struct PatternUniforms { uPatternSize: vec2<f32>, };
    @group(0) @binding(0) var<uniform> gfu: GlobalFilterUniforms;
    @group(0) @binding(1) var uTexture: texture_2d<f32>;
    @group(0) @binding(2) var uSampler: sampler;
    @group(1) @binding(0) var<uniform> patternUniforms: PatternUniforms;
    @group(1) @binding(1) var uPatternTexture: texture_2d<f32>;
    @group(1) @binding(2) var uPatternSampler: sampler;
    struct VSOutput {
      @builtin(position) position: vec4<f32>,
      @location(0) uv: vec2<f32>,
    };
    @vertex fn mainVertex(@location(0) aPosition: vec2<f32>) -> VSOutput {
      var position = aPosition * gfu.uOutputFrame.zw + gfu.uOutputFrame.xy;
      position.x = position.x * (2.0 / gfu.uOutputTexture.x) - 1.0;
      position.y = position.y * (2.0 * gfu.uOutputTexture.z / gfu.uOutputTexture.y) - gfu.uOutputTexture.z;
      return VSOutput(vec4<f32>(position, 0.0, 1.0),
        aPosition * (gfu.uOutputFrame.zw * gfu.uInputSize.zw));
    }
    @fragment fn mainFragment(@location(0) uv: vec2<f32>,
      @builtin(position) position: vec4<f32>) -> @location(0) vec4<f32> {
      let pixel = floor(position.xy);
      let wrapped = pixel - floor(pixel / patternUniforms.uPatternSize)
        * patternUniforms.uPatternSize;
      let patternUv = (wrapped + vec2<f32>(0.5)) / patternUniforms.uPatternSize;
      let mask = textureSampleLevel(uPatternTexture, uPatternSampler, patternUv, 0.0).a;
      return textureSample(uTexture, uSampler, uv) * mask;
    }`;
  const stippleGlProgram = PIXI.GlProgram.from({
    vertex: stippleVertexGl, fragment: stippleFragmentGl,
  });
  const stippleGpuProgram = PIXI.GpuProgram.from({
    vertex: { source: stippleWgsl, entryPoint: "mainVertex" },
    fragment: { source: stippleWgsl, entryPoint: "mainFragment" },
  });
  function patternFilter(canvas) {
    const texture = PIXI.Texture.from(canvas);
    texture.source.style.scaleMode = "nearest";
    const filter = new PIXI.Filter({
      glProgram: stippleGlProgram,
      gpuProgram: stippleGpuProgram,
      resources: {
        patternUniforms: new PIXI.UniformGroup({
          uPatternSize: { value: new Float32Array([canvas.width, canvas.height]), type: "vec2<f32>" },
        }),
        uPatternTexture: texture.source,
        uPatternSampler: texture.source.style,
      },
      resolution: "inherit",
    });
    return { filter, texture };
  }
  const app = new PIXI.Application();
  await app.init({ resizeTo: host, background: 0x15191f, antialias: true });
  host.appendChild(app.canvas);
  app.canvas.style.cursor = "crosshair";
  app.canvas.style.touchAction = "none";
  const grid = new PIXI.Graphics();
  const world = new PIXI.Container();
  const crosshair = new PIXI.Graphics();
  crosshair.eventMode = "none";
  crosshair.visible = false;
  app.stage.addChild(grid, world, crosshair);
  const layers = new Map();
  const groups = new Map();
  const layerStyles = new Map();
  function registerLayers(cellLayers) {
    for (const layer of cellLayers) {
      let entry = layers.get(layer.id);
      if (!entry) {
        const style = layerStyle(layer.id);
        layerStyles.set(layer.id, style);
        const group = new PIXI.Container();
        group.visible = style.visible;
        group.fillGroup = new PIXI.Container();
        group.frameGroup = new PIXI.Container();
        group.addChild(group.fillGroup, group.frameGroup);
        if (Array.isArray(style.pattern)) {
          const canvas = patternCanvas(style.pattern, style.fillColor);
          const { filter, texture } = patternFilter(canvas);
          group.fillGroup.filters = [filter];
          style.patternTexture = texture;
          style.patternImage = canvas.toDataURL();
        }
        world.addChild(group);
        groups.set(layer.id, group);
        const label = document.createElement("label");
        label.className = "form-check d-inline-flex align-items-center gap-2 mb-0";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "form-check-input mt-0";
        checkbox.checked = style.visible;
        checkbox.addEventListener("change", () => { group.visible = checkbox.checked; refreshSoon(); });
        const swatch = document.createElement("span");
        swatch.style.cssText = `width:.8rem;height:.8rem;display:inline-block;background-color:${style.pattern === "hollow" ? "#15191f" : style.fillColor};border:${Math.min(style.frameWidth, 3)}px solid ${style.frameColor};border-radius:.15rem`;
        if (style.patternImage) {
          swatch.style.backgroundColor = "#15191f";
          swatch.style.backgroundImage = `url(${style.patternImage})`;
        }
        const name = document.createElement("span");
        label.append(checkbox, swatch, name);
        document.getElementById("layout-layers").appendChild(label);
        entry = { label: layer.label, shapes: 0, name };
        layers.set(layer.id, entry);
      }
      entry.shapes += layer.shapes;
      entry.name.textContent = `${entry.label} (${entry.shapes})`;
    }
  }
  const metadataReady = new Set();
  for (const [id, cell] of Object.entries(data.cells)) {
    if (cell.layers.length) {
      metadataReady.add(id);
      registerLayers(cell.layers);
    }
  }
  const coarseCells = new PIXI.Graphics();
  world.addChild(coarseCells);

  const identity = [1, 0, 0, 1, 0, 0];
  function multiply(a, b) {
    return [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
      a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
      a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]];
  }
  function instanceMatrix(p) {
    const angle = p.angle * Math.PI / 180;
    const co = Math.cos(angle), si = Math.sin(angle);
    const sy = p.mirror ? -p.mag : p.mag;
    return [co * p.mag, si * p.mag, -si * sy, co * sy, p.x, p.y];
  }
  function transformed(box, m) {
    const out = [Infinity, Infinity, -Infinity, -Infinity];
    for (const x of [box[0], box[2]]) for (const y of [box[1], box[3]]) {
      const px = m[0] * x + m[2] * y + m[4];
      const py = m[1] * x + m[3] * y + m[5];
      out[0] = Math.min(out[0], px); out[1] = Math.min(out[1], py);
      out[2] = Math.max(out[2], px); out[3] = Math.max(out[3], py);
    }
    return out;
  }
  function visible(box, viewport) {
    return box[0] <= viewport[2] && box[2] >= viewport[0]
      && box[1] <= viewport[3] && box[3] >= viewport[1];
  }
  function viewport() {
    const s = world.scale.x;
    return [-world.x / s, (world.y - app.screen.height) / s,
      (app.screen.width - world.x) / s, world.y / s];
  }
  function matrixObject(m) { return new PIXI.Matrix(...m); }

  // The file stores boxes, polygon rings, and labels. Shapes are moved to a
  // chunk-local origin so GPU floats retain precision across a large reticle.
  function decode(buffer, origin, style) {
    const view = new DataView(buffer);
    if (view.getUint32(0, true) !== 0x3142594d) throw new Error("Unknown layout chunk format");
    const fillContext = new PIXI.GraphicsContext();
    const frameContext = new PIXI.GraphicsContext();
    const fillStyle = { color: style.fillColor, alpha: 0.8 };
    const strokeStyle = { color: style.frameColor, width: style.frameWidth, pixelLine: true };
    const texts = [];
    let pos = 4;
    while (pos < view.byteLength) {
      const tag = view.getUint8(pos++);
      if (tag === 1) {
        const x0 = view.getInt32(pos, true) - origin[0]; pos += 4;
        const y0 = view.getInt32(pos, true) - origin[1]; pos += 4;
        const x1 = view.getInt32(pos, true) - origin[0]; pos += 4;
        const y1 = view.getInt32(pos, true) - origin[1]; pos += 4;
        if (style.pattern !== "hollow") fillContext.rect(x0, y0, x1 - x0, y1 - y0).fill(fillStyle);
        if (style.frameWidth) frameContext.rect(x0, y0, x1 - x0, y1 - y0).stroke(strokeStyle);
      } else if (tag === 2) {
        const rings = view.getUint32(pos, true); pos += 4;
        for (let ring = 0; ring < rings; ring++) {
          const count = view.getUint32(pos, true); pos += 4;
          const points = [];
          for (let i = 0; i < count; i++) {
            points.push(view.getInt32(pos, true) - origin[0]); pos += 4;
            points.push(view.getInt32(pos, true) - origin[1]); pos += 4;
          }
          if (points.length >= 6) {
            if (ring === 0 && style.pattern !== "hollow") fillContext.poly(points, true).fill(fillStyle);
            else if (ring > 0 && style.pattern !== "hollow") fillContext.poly(points, true).cut();
            if (style.frameWidth) frameContext.poly(points, true).stroke(strokeStyle);
          }
        }
      } else if (tag === 3) {
        const x = view.getInt32(pos, true) - origin[0]; pos += 4;
        const y = view.getInt32(pos, true) - origin[1]; pos += 4;
        const angle = view.getUint8(pos++);
        const mirror = Boolean(view.getUint8(pos++));
        const size = view.getInt32(pos, true); pos += 4;
        const length = view.getUint32(pos, true); pos += 4;
        const text = new TextDecoder().decode(new Uint8Array(buffer, pos, length));
        pos += length;
        texts.push({ x, y, angle, mirror, size, text });
      } else throw new Error(`Unknown layout record ${tag}`);
    }
    return { fillContext, frameContext, texts };
  }

  const loaded = new Map(), pending = new Set(), failed = new Set();
  let wanted = new Set(), queue = [], active = 0, timer = null;
  const metadataPending = new Set(), metadataFailed = new Set();
  let metadataWanted = new Set(), metadataQueue = [], metadataActive = 0;
  let failureMessage = null;
  function refreshSoon() {
    if (timer !== null) return;
    timer = setTimeout(() => { timer = null; refresh(); }, 70);
  }
  function pumpMetadata() {
    while (metadataActive < 4 && metadataQueue.length) {
      const id = metadataQueue.shift();
      if (!metadataWanted.has(id)) { metadataPending.delete(id); continue; }
      metadataActive++;
      fetch(`/cells/${id}/layout/geometry`)
        .then((reply) => {
          if (!reply.ok) throw new Error(`Cell geometry HTTP ${reply.status}`);
          return reply.json();
        })
        .then((result) => {
          data.cells[id].layers = result.layers;
          metadataReady.add(id);
          registerLayers(result.layers);
        })
        .catch((error) => {
          metadataFailed.add(id);
          failureMessage = `Could not load cell geometry: ${error.message}`;
        })
        .finally(() => {
          metadataActive--;
          metadataPending.delete(id);
          refreshSoon();
          pumpMetadata();
        });
    }
  }
  function requestMetadata(id) {
    metadataWanted.add(id);
    if (!metadataReady.has(id) && !metadataPending.has(id) && !metadataFailed.has(id)) {
      metadataPending.add(id);
      metadataQueue.push(id);
    }
  }
  function pump() {
    while (active < 6 && queue.length) {
      const item = queue.shift();
      if (!wanted.has(item.key)) { pending.delete(item.key); continue; }
      active++;
      fetch(`/cells/${item.cellId}/layout/chunks/${item.layerIndex}/${item.chunkIndex}`)
        .then((reply) => {
          if (!reply.ok) throw new Error(`Chunk HTTP ${reply.status}`);
          return reply.arrayBuffer();
        })
        .then((bytes) => loaded.set(item.key, decode(bytes, item.origin, item.style)))
        .catch((error) => {
          failed.add(item.key);
          failureMessage = `Could not load layout chunk: ${error.message}`;
        })
        .finally(() => { active--; pending.delete(item.key); refreshSoon(); pump(); });
    }
  }
  function addShape(group, m, content, style) {
    if (style.pattern !== "hollow") {
      const fillHolder = new PIXI.Container();
      fillHolder.setFromMatrix(matrixObject(m));
      fillHolder.addChild(new PIXI.Graphics(content.fillContext));
      group.fillGroup.addChild(fillHolder);
    }
    const holder = new PIXI.Container();
    holder.setFromMatrix(matrixObject(m));
    if (style.frameWidth) {
      const Graphics = style.frameWidth > 1 ? PIXI.SmoothGraphics : PIXI.Graphics;
      holder.addChild(new Graphics(content.frameContext));
    }
    for (const shape of content.texts) {
      const label = new PIXI.Text({ text: shape.text,
        style: { fontSize: 14, fill: style.frameColor } });
      const height = shape.size > 0 ? shape.size : 10 / data.dbu;
      label.anchor.set(0, 1);
      label.position.set(shape.x, shape.y);
      label.scale.set((shape.mirror ? -1 : 1) * height / 14, -height / 14);
      label.angle = -shape.angle * 90;
      holder.addChild(label);
    }
    group.frameGroup.addChild(holder);
  }
  function refresh() {
    for (const group of groups.values()) {
      for (const childGroup of [group.fillGroup, group.frameGroup]) {
        for (const child of childGroup.removeChildren()) child.destroy({ children: true });
      }
    }
    coarseCells.clear();
    wanted = new Set();
    for (const item of queue) pending.delete(item.key);
    queue = [];
    metadataWanted = new Set();
    for (const id of metadataQueue) metadataPending.delete(id);
    metadataQueue = [];
    const view = viewport(), ancestors = new Set();
    let visibleChunks = 0;
    function drawCoarse(box) {
      coarseCells.rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
        .stroke({ color: 0x687587, alpha: 0.6, pixelLine: true });
    }
    function arrayBounds(instance, parent, childBox) {
      const out = [Infinity, Infinity, -Infinity, -Infinity];
      for (const ia of [0, instance.na - 1]) for (const ib of [0, instance.nb - 1]) {
        const base = instance.transform;
        const p = { ...base,
          x: base.x + ia * instance.a[0] + ib * instance.b[0],
          y: base.y + ia * instance.a[1] + ib * instance.b[1] };
        const box = transformed(childBox, multiply(parent, instanceMatrix(p)));
        out[0] = Math.min(out[0], box[0]); out[1] = Math.min(out[1], box[1]);
        out[2] = Math.max(out[2], box[2]); out[3] = Math.max(out[3], box[3]);
      }
      return out;
    }
    function visit(id, matrix) {
      const cell = data.cells[id];
      if (!cell || ancestors.has(id)) return;
      const bounds = cell.bbox && transformed(cell.bbox, matrix);
      if (bounds && !visible(bounds, view)) return;
      if (id !== data.root && bounds
          && Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * world.scale.x < 2) {
        return;
      }
      ancestors.add(id);
      if (!metadataReady.has(id)) {
        if (id === data.root || !bounds || Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1])
            * world.scale.x >= 2) requestMetadata(id);
        if (bounds) drawCoarse(bounds);
      }
      for (const [layerIndex, layer] of cell.layers.entries()) {
        const group = groups.get(layer.id);
        if (!group || !group.visible) continue;
        const style = layerStyles.get(layer.id);
        for (const [chunkIndex, chunk] of layer.chunks.entries()) {
          if (!chunk.bbox) continue;
          const box = transformed(chunk.bbox, matrix);
          if (!visible(box, view)) continue;
          const origin = [chunk.bbox[0], chunk.bbox[1]];
          const shifted = multiply(matrix, [1, 0, 0, 1, ...origin]);
          const size = Math.max(box[2] - box[0], box[3] - box[1]) * world.scale.x;
          if (size < 2) continue;
          visibleChunks++;
          const key = `${id}:${layerIndex}:${chunkIndex}`;
          wanted.add(key);
          if (loaded.has(key)) addShape(group, shifted, loaded.get(key), style);
          else if (!pending.has(key) && !failed.has(key)) {
            pending.add(key);
            queue.push({ key, cellId: id, layerIndex, chunkIndex, origin, style });
          }
        }
      }
      for (const instance of cell.instances) {
        const child = data.cells[instance.cell];
        if (!child?.bbox) continue;
        const first = multiply(matrix, instanceMatrix(instance.transform));
        const childExtent = transformed(child.bbox, first);
        const childSize = Math.max(childExtent[2] - childExtent[0],
          childExtent[3] - childExtent[1]) * world.scale.x;
        if (childSize < (instance.na > 1 || instance.nb > 1 ? 8 : 2)) continue;
        const extent = arrayBounds(instance, matrix, child.bbox);
        if (!visible(extent, view)) continue;
        for (let ib = 0; ib < instance.nb; ib++) for (let ia = 0; ia < instance.na; ia++) {
          const base = instance.transform;
          const placement = { ...base,
            x: base.x + ia * instance.a[0] + ib * instance.b[0],
            y: base.y + ia * instance.a[1] + ib * instance.b[1] };
          visit(instance.cell, multiply(matrix, instanceMatrix(placement)));
        }
      }
      ancestors.delete(id);
    }
    visit(data.root, identity);
    pumpMetadata();
    for (const [key, value] of loaded) {
      if (loaded.size <= 256) break;
      if (!wanted.has(key)) {
        value.fillContext.destroy();
        value.frameContext.destroy();
        loaded.delete(key);
      }
    }
    pump();
    const count = [...layers.values()].reduce((sum, layer) => sum + layer.shapes, 0);
    status.textContent = failureMessage || `${count} indexed unique shapes in ${Object.keys(data.cells).length} cells · ${visibleChunks} visible chunks · ${loaded.size} chunks loaded · ${metadataActive + metadataQueue.length} cell requests · 1 DBU = ${data.dbu} µm`;
  }

  const bounds = data.bounds || [0, 0, 0, 0];
  const scaleLabel = document.getElementById("layout-scale-label");
  const scaleBar = document.getElementById("layout-scale-bar");
  const positionLabel = document.getElementById("layout-position");
  const gridToggle = document.getElementById("layout-grid-toggle");
  const gridSpacing = document.getElementById("layout-grid-spacing");
  let pointerPosition = null;
  function updateCrosshair() {
    const position = pointerPosition;
    crosshair.visible = position !== null
      && position[0] >= 0 && position[0] <= app.screen.width
      && position[1] >= 0 && position[1] <= app.screen.height;
    if (!crosshair.visible) return;
    const [x, y] = position;
    crosshair.clear()
      .moveTo(x, 0).lineTo(x, app.screen.height)
      .moveTo(0, y).lineTo(app.screen.width, y)
      .stroke({ color: 0xdce6ef, alpha: 0.55, width: 1, pixelLine: true });
  }
  function formatLength(micrometers) {
    const value = micrometers >= 1000 ? micrometers / 1000
      : micrometers < 1 ? micrometers * 1000 : micrometers;
    const unit = micrometers >= 1000 ? "mm" : micrometers < 1 ? "nm" : "µm";
    return `${new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 }).format(value)} ${unit}`;
  }
  function updateGrid() {
    grid.visible = gridToggle.checked;
    if (!grid.visible) {
      gridSpacing.textContent = "";
      return;
    }
    const scale = world.scale.x;
    const target = 80 / scale;
    const decade = 10 ** Math.floor(Math.log10(target));
    const majorStep = Math.max(1, Math.round(
      [1, 2, 5, 10].map((value) => value * decade).find((value) => value >= target),
    ));
    gridSpacing.textContent = `(${formatLength(majorStep * data.dbu)})`;
    grid.clear();
    const [left, bottom, right, top] = viewport();
    function drawLines(step, color, alpha, skipFifths = false) {
      for (let index = Math.ceil(left / step); index <= Math.floor(right / step); index++) {
        if (skipFifths && index % 5 === 0) continue;
        const x = world.x + index * step * scale;
        grid.moveTo(x, 0).lineTo(x, app.screen.height);
      }
      for (let index = Math.ceil(bottom / step); index <= Math.floor(top / step); index++) {
        if (skipFifths && index % 5 === 0) continue;
        const y = world.y - index * step * scale;
        grid.moveTo(0, y).lineTo(app.screen.width, y);
      }
      grid.stroke({ color, alpha, width: 1, pixelLine: true });
    }
    const minorStep = majorStep / 5;
    if (Number.isInteger(minorStep) && minorStep * scale >= 12) {
      drawLines(minorStep, 0x91a0ae, 0.1, true);
    }
    drawLines(majorStep, 0x91a0ae, 0.22);
    if (left <= 0 && right >= 0) grid.moveTo(world.x, 0).lineTo(world.x, app.screen.height);
    if (bottom <= 0 && top >= 0) grid.moveTo(0, world.y).lineTo(app.screen.width, world.y);
    grid.stroke({ color: 0xb8c6d2, alpha: 0.38, width: 1, pixelLine: true });
  }
  gridToggle.addEventListener("change", updateGrid);
  function canvasPosition(event) {
    const rect = app.canvas.getBoundingClientRect();
    return [(event.clientX - rect.left) * app.screen.width / rect.width,
      (event.clientY - rect.top) * app.screen.height / rect.height];
  }
  function updateOverlay() {
    updateCrosshair();
    const target = Math.max(1, Math.min(120, app.screen.width / 4)) * data.dbu / world.scale.x;
    const decade = 10 ** Math.floor(Math.log10(target));
    const lengths = [1, 2, 5, 10].map((step) => step * decade);
    const length = lengths.reduce((best, candidate) =>
      Math.abs(Math.log(candidate / target)) < Math.abs(Math.log(best / target)) ? candidate : best);
    const pixels = length * world.scale.x / data.dbu;
    scaleBar.style.width = `${pixels}px`;
    scaleLabel.textContent = formatLength(length);

    const [x, y] = pointerPosition || [app.screen.width / 2, app.screen.height / 2];
    const physicalPerPixel = data.dbu / world.scale.x;
    const digits = Math.max(0, Math.min(6, Math.ceil(-Math.log10(physicalPerPixel))));
    const format = new Intl.NumberFormat(undefined, { maximumFractionDigits: digits });
    const worldX = (x - world.x) / world.scale.x * data.dbu;
    const worldY = (world.y - y) / world.scale.x * data.dbu;
    positionLabel.textContent = `${pointerPosition ? "Cursor" : "Center"}: x ${format.format(worldX)} µm · y ${format.format(worldY)} µm`;
  }
  const minimumViewHeightDbu = 10;
  function maximumScale() { return app.screen.height / minimumViewHeightDbu; }
  let fittedScale = 1;
  function fit() {
    const [left, bottom, right, top] = bounds;
    const width = Math.max(right - left, 1 / data.dbu);
    const height = Math.max(top - bottom, 1 / data.dbu);
    fittedScale = Math.min(Math.max(1, app.screen.width - 48) / width,
      Math.max(1, app.screen.height - 48) / height, maximumScale());
    world.scale.set(fittedScale, -fittedScale);
    world.position.set(app.screen.width / 2 - ((left + right) / 2) * fittedScale,
      app.screen.height / 2 + ((bottom + top) / 2) * fittedScale);
    updateGrid();
    updateOverlay();
    refreshSoon();
  }
  fit();
  document.getElementById("fit-layout").addEventListener("click", fit);
  window.addEventListener("resize", fit);
  let lastPointer = null;
  let draggingPointerId = null;
  app.canvas.addEventListener("pointerdown", (event) => {
    if (draggingPointerId !== null || event.button !== 0) return;
    app.canvas.setPointerCapture(event.pointerId);
    draggingPointerId = event.pointerId;
    lastPointer = canvasPosition(event);
    pointerPosition = lastPointer;
    updateOverlay();
  });
  app.canvas.addEventListener("pointermove", (event) => {
    if (draggingPointerId !== null && event.pointerId !== draggingPointerId) return;
    const position = canvasPosition(event);
    pointerPosition = position;
    if (lastPointer === null) { updateOverlay(); return; }
    world.x += position[0] - lastPointer[0];
    world.y += position[1] - lastPointer[1];
    lastPointer = position;
    updateGrid();
    updateOverlay();
    refreshSoon();
  });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    app.canvas.addEventListener(type, (event) => {
      if (event.pointerId !== draggingPointerId) return;
      draggingPointerId = null;
      lastPointer = null;
      const [x, y] = canvasPosition(event);
      pointerPosition = x < 0 || x > app.screen.width || y < 0 || y > app.screen.height
        ? null : [x, y];
      updateOverlay();
    });
  }
  app.canvas.addEventListener("pointerleave", () => {
    pointerPosition = null;
    updateOverlay();
  });
  app.canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const [x, y] = canvasPosition(event);
    pointerPosition = [x, y];
    const oldScale = world.scale.x;
    const nextScale = Math.max(fittedScale * 0.05,
      Math.min(maximumScale(), oldScale * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
    const worldX = (x - world.x) / oldScale;
    const worldY = (world.y - y) / oldScale;
    world.scale.set(nextScale, -nextScale);
    world.position.set(x - worldX * nextScale, y + worldY * nextScale);
    updateGrid();
    updateOverlay();
    refreshSoon();
  }, { passive: false });
}
renderCellLayout().catch((error) => {
  document.getElementById("layout-status").textContent = `Could not render layout: ${error.message}`;
});
