"""Trusted Blender builder for STAR asset specs. Runs INSIDE Blender (bpy), headless:

    blender -b --factory-startup -noaudio --python build_bpy.py -- job.json OUTDIR

job.json: {"mode": "pipeline"|"baseline", "spec": {...validated + mirrors expanded...}, "tex": 1024,
           "render": {"size": 512, "samples": 24, "views": [...]}, "final": false, "threads": 4}
Writes OUTDIR/metrics.json, OUTDIR/views/<view>.png and (final) textures/*.png, asset.glb, asset.fbx, asset.obj.
Only bpy/bmesh/mathutils/numpy and the standard library; no network, no model code.
"""
import json
import math
import os
import sys
import time
import traceback

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

T0 = time.time()
LOG = []


def log(msg):
    LOG.append(f"{time.time() - T0:7.1f}s {msg}")
    print("[asset3d]", msg, flush=True)


STYLE = {
    "pbr": {"bevel": 0.003, "segments": 3, "circle": 32, "shade": "smooth"},
    "stylized": {"bevel": 0.010, "segments": 2, "circle": 16, "shade": "smooth"},
    "lowpoly": {"bevel": 0.0, "segments": 1, "circle": 8, "shade": "flat"},
    "roblox": {"bevel": 0.006, "segments": 2, "circle": 16, "shade": "smooth"},
}

# kind -> (default colour, metallic, roughness)
MAT = {
    "painted_metal": ("#5a6b4a", 0.0, 0.55), "bare_metal": ("#9a9da2", 1.0, 0.38), "gunmetal": ("#2e3034", 1.0, 0.42),
    "anodized": ("#3a5a8c", 1.0, 0.30), "chrome": ("#d8dade", 1.0, 0.08), "gold": ("#d4a63a", 1.0, 0.25),
    "brass": ("#b8913f", 1.0, 0.35), "polymer": ("#1f2023", 0.0, 0.62), "plastic": ("#c8c8c8", 0.0, 0.45),
    "rubber": ("#151515", 0.0, 0.88), "wood": ("#9a6a3c", 0.0, 0.62), "dark_wood": ("#5a3a22", 0.0, 0.58),
    "leather": ("#6b4226", 0.0, 0.70), "fabric": ("#6d6a58", 0.0, 0.90), "glass": ("#1c2a33", 0.0, 0.05),
    "emissive": ("#3fe0ff", 0.0, 0.40), "stone": ("#8a8780", 0.0, 0.85), "ceramic": ("#e8e4dc", 0.0, 0.30),
}
METALS = {"bare_metal", "gunmetal", "anodized", "chrome", "gold", "brass"}


def hex_rgb(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]


AXIS_ROT = {"z": Euler((0, 0, 0)), "x": Euler((0, math.pi / 2, 0)), "y": Euler((math.pi / 2, 0, 0))}


def world_matrix(pos, rot_deg):
    return Matrix.LocRotScale(Vector(pos), Euler([math.radians(a) for a in rot_deg]), None)


# ---------------------------------------------------------------- geometry
def bm_box(size, taper=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
        if taper and v.co.z > 0:
            v.co.x *= taper[0]
            v.co.y *= taper[1]
    return bm


def bm_cone(r1, r2, depth, axis, segs):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r1, radius2=max(r2, 0.0),
                          depth=depth)
    if r2 <= 1e-6:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.transform(AXIS_ROT[axis].to_matrix().to_4x4())
    return bm


def bm_sphere(r, scale, segs):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(6, segs // 2), radius=r)
    bm.transform(Matrix.Diagonal(Vector((scale[0], scale[1], scale[2], 1.0))))
    return bm


def bm_torus(R, r, axis, segs):
    bm = bmesh.new()
    minor = max(6, segs // 2)
    rings = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        ring = []
        for j in range(minor):
            b = 2 * math.pi * j / minor
            d = R + r * math.cos(b)
            ring.append(bm.verts.new((d * math.cos(a), d * math.sin(a), r * math.sin(b))))
        rings.append(ring)
    for i in range(segs):
        for j in range(minor):
            a, b = rings[i], rings[(i + 1) % segs]
            bm.faces.new((a[j], b[j], b[(j + 1) % minor], a[(j + 1) % minor]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # torus is built in the XY plane (axis z); the spec's axis is the wheel axle
    bm.transform(AXIS_ROT[axis].to_matrix().to_4x4())
    return bm


def bm_profile(points, thickness):
    bm = bmesh.new()
    vs = [bm.verts.new((x, -thickness / 2, z)) for x, z in points]
    face = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    moved = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=moved, vec=(0, thickness, 0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def bm_lathe(points, axis, segs):
    bm = bmesh.new()
    pts = [(max(r, 0.0), h) for h, r in points]  # spec: [position_along_axis, radius]
    vs = [bm.verts.new((r, 0, h)) for r, h in pts]
    edges = [bm.edges.new((vs[i], vs[i + 1])) for i in range(len(vs) - 1)]
    bmesh.ops.spin(bm, geom=vs + edges, cent=(0, 0, 0), axis=(0, 0, 1), angle=2 * math.pi, steps=segs,
                   use_merge=True, use_duplicate=False)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    # cap open ends (rings whose radius is > 0 at the first/last point)
    for idx in (0, len(pts) - 1):
        r, h = pts[idx]
        if r > 1e-5:
            ring = [e for e in bm.edges if e.is_boundary and all(abs(v.co.z - h) < 1e-5 for v in e.verts)]
            if ring:
                try:
                    bmesh.ops.edgeloop_fill(bm, edges=ring)
                except Exception:
                    bmesh.ops.contextual_create(bm, geom=ring)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.transform(AXIS_ROT[axis].to_matrix().to_4x4())
    return bm


def mesh_from_bm(bm, name):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def tube_object(name, points, radius, segs):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for p, q in zip(sp.points, points):
        p.co = (q[0], q[1], q[2], 1.0)
    cu.bevel_depth = radius
    cu.bevel_resolution = max(1, segs // 8)
    cu.use_fill_caps = True
    ob = bpy.data.objects.new(name + "_curve", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    me.name = name
    return me


def link(name, me):
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def part_mesh(p, st):
    segs = st["circle"]
    t = p["type"]
    if t == "tube":
        return tube_object(p["id"], [[q[0] + p["pos"][0], q[1] + p["pos"][1], q[2] + p["pos"][2]]
                                     for q in p["points"]], p["radius"], segs)
    if t == "box":
        bm = bm_box(p["size"], p.get("taper"))
    elif t == "cylinder":
        bm = bm_cone(p["radius"], p["radius"], p["depth"], p["axis"], segs)
    elif t == "cone":
        bm = bm_cone(p["radius"], p["radius2"], p["depth"], p["axis"], segs)
    elif t == "sphere":
        bm = bm_sphere(p["radius"], p["scale"], segs)
    elif t == "torus":
        bm = bm_torus(p["radius"], p["tube"], p["axis"], segs)
    elif t == "profile":
        bm = bm_profile(p["points"], p["thickness"])
    elif t == "lathe":
        bm = bm_lathe(p["points"], p["axis"], segs)
    else:
        raise ValueError(t)
    bm.transform(world_matrix(p["pos"], p["rot"]))
    return mesh_from_bm(bm, p["id"])


def min_dim(me):
    if not me.vertices:
        return 0.0
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    ext = co.max(0) - co.min(0)
    return float(max(ext.min(), 1e-4))


def cutter_object(name, c, segs):
    bm_all = bmesh.new()
    for k in range(c["count"]):
        pos = [c["pos"][i] + c["step"][i] * k for i in range(3)]
        if c["shape"] == "box":
            bm = bm_box(c["size"])
        else:
            bm = bm_cone(c["radius"], c["radius"], c["depth"], c["axis"], max(8, segs // 2))
        bm.transform(world_matrix(pos, c["rot"]))
        tmp = bpy.data.meshes.new("tmp")
        bm.to_mesh(tmp)
        bm.free()
        bm_all.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    ob = link(name, mesh_from_bm(bm_all, name))
    ob.hide_render = True
    return ob


def seam_cutter(name, base_me, axis, at, width, depth):
    """A thin ring that hugs the part's outside: slab minus the part shrunk by `depth` along vertex normals."""
    co = np.empty(len(base_me.vertices) * 3, dtype=np.float32)
    base_me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lo, hi = co.min(0) - 0.01, co.max(0) + 0.01
    ai = "xyz".index(axis)
    size = list(hi - lo)
    centre = list((hi + lo) / 2)
    size[ai] = width
    centre[ai] = at
    slab = link(name + "_slab", mesh_from_bm(bm_box(size), name + "_slab"))
    slab.location = centre
    bm = bmesh.new()
    bm.from_mesh(base_me)
    bm.normal_update()
    for v in bm.verts:
        v.co -= v.normal * depth
    inner = link(name + "_inner", mesh_from_bm(bm, name + "_inner"))
    mod = slab.modifiers.new("in", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = inner
    mod.solver = "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(slab.evaluated_get(dg))
    for o in (slab, inner):
        bpy.data.objects.remove(o)
    ob = link(name, me)
    ob.hide_render = True
    return ob


def build_part(p, style, st):
    me = part_mesh(p, st)
    ob = link(p["id"], me)
    temps = []
    segs = st["circle"]
    for k, c in enumerate(p["cuts"]):
        cu = cutter_object(f"{p['id']}_cut{k}", c, segs)
        temps.append(cu)
        mod = ob.modifiers.new(f"cut{k}", "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.object = cu
        mod.solver = "EXACT"
    md = min_dim(me)
    if style != "lowpoly":
        width = max(0.0008, md * 0.012)
        for k, s in enumerate(p["seams"]):
            for j, at in enumerate(s["at"]):
                sc = seam_cutter(f"{p['id']}_seam{k}_{j}", me, s["axis"], at, width, max(0.0006, md * 0.02))
                temps.append(sc)
                mod = ob.modifiers.new(f"seam{k}_{j}", "BOOLEAN")
                mod.operation = "DIFFERENCE"
                mod.object = sc
                mod.solver = "EXACT"
    bevel = p.get("bevel", st["bevel"])
    if st["shade"] == "smooth" and p["type"] not in ("tube",):
        me.shade_smooth()
    if bevel > 0 and p["type"] not in ("sphere", "tube"):
        width = min(bevel, md * 0.22)
        if width > 0.0002:
            mod = ob.modifiers.new("bevel", "BEVEL")
            mod.width = width
            mod.segments = st["segments"]
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(35)
            mod.use_clamp_overlap = True
            mod.harden_normals = st["shade"] == "smooth"
    elif style == "lowpoly" and p["type"] in ("box", "profile"):
        mod = ob.modifiers.new("chamfer", "BEVEL")
        mod.width = min(0.004, md * 0.08)
        mod.segments = 1
        mod.limit_method = "ANGLE"
        mod.use_clamp_overlap = True
    dg = bpy.context.evaluated_depsgraph_get()
    final = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    for o in temps:
        bpy.data.objects.remove(o)
    old = ob.data
    ob.modifiers.clear()
    ob.data = final
    bpy.data.meshes.remove(old)
    final.name = p["id"]
    if st["shade"] == "smooth":
        if not final.has_custom_normals:
            final.shade_smooth()
            final.set_sharp_from_angle(angle=math.radians(35))
    else:
        final.shade_flat()
    # deterministic fix: outward normals per part (closed parts)
    bm = bmesh.new()
    bm.from_mesh(final)
    flipped = 0
    try:
        vol = bm.calc_volume(signed=True)
        if all(e.is_manifold for e in bm.edges) and vol < 0:
            bmesh.ops.reverse_faces(bm, faces=bm.faces)
            flipped = 1
            bm.to_mesh(final)
    finally:
        bm.free()
    return ob, flipped


# ---------------------------------------------------------------- materials
def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    return m, nt


def node(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def mix_rgb(nt, fac, a, b, blend="MIX"):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    for src, idx in ((fac, 0), (a, 6), (b, 7)):
        if isinstance(src, (int, float)):
            n.inputs[idx].default_value = src
        elif isinstance(src, (list, tuple)):
            n.inputs[idx].default_value = (*src[:3], 1.0)
        else:
            nt.links.new(src, n.inputs[idx])
    return n.outputs[2]


def mix_f(nt, fac, a, b):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "FLOAT"
    for src, idx in ((fac, 0), (a, 2), (b, 3)):
        if isinstance(src, (int, float)):
            n.inputs[idx].default_value = src
        else:
            nt.links.new(src, n.inputs[idx])
    return n.outputs[0]


def maprange(nt, src, a, b, c=0.0, d=1.0):
    n = nt.nodes.new("ShaderNodeMapRange")
    n.clamp = True
    nt.links.new(src, n.inputs[0])
    n.inputs[1].default_value, n.inputs[2].default_value = a, b
    n.inputs[3].default_value, n.inputs[4].default_value = c, d
    return n.outputs[0]


def edge_mask(nt, radius, lo=0.02, hi=0.25):
    """1 on convex/concave edges, 0 on flats (Cycles Bevel node vs true normal)."""
    bev = node(nt, "ShaderNodeBevel")
    bev.samples = 8
    bev.inputs["Radius"].default_value = radius
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    nt.links.new(bev.outputs[0], dot.inputs[0])
    nt.links.new(geo.outputs["Normal"], dot.inputs[1])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(dot.outputs["Value"], inv.inputs[1])
    return maprange(nt, inv.outputs[0], lo, hi), bev


def noise(nt, scale, detail=6.0, rough=0.55, coord="Object"):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    nt.links.new(tc.outputs[coord], n.inputs["Vector"])
    return n.outputs["Fac"]


def build_material(name, kind, color_hex, style, size, zrange):
    """Returns (material, sockets) where sockets = color/rough/metal/emit outputs and the normal source."""
    base_hex, metal, rough = MAT[kind]
    col = hex_rgb(color_hex or base_hex)
    m, nt = new_mat(name)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    edge_r = 0.0015 if style == "pbr" else 0.004
    s = {"emit": None, "normal": None}
    if style == "lowpoly":
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(geo.outputs["Normal"], sep.inputs[0])
        up = maprange(nt, sep.outputs[2], -1.0, 1.0, 0.0, 1.0)
        c = mix_rgb(nt, up, [x * 0.82 for x in col], [min(1, x * 1.08) for x in col])
        s["color"], s["rough"], s["metal"] = c, None, None
        s["rough_v"], s["metal_v"] = 0.85, 0.0
    elif style in ("stylized", "roblox"):
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(geo.outputs["Position"], sep.inputs[0])
        grad = maprange(nt, sep.outputs[2], zrange[0], zrange[1], 0.0, 1.0)
        c = mix_rgb(nt, grad, [x * 0.68 for x in col], [min(1, x * 1.12) for x in col])
        mott = noise(nt, 2.5 / max(size, 0.05), detail=2.0, rough=0.4)
        c = mix_rgb(nt, maprange(nt, mott, 0.35, 0.65, 0.0, 0.10), c, [x * 0.8 for x in col])
        e, bev = edge_mask(nt, edge_r * max(1.0, size), 0.02, 0.18)
        hl = [min(1, x * 1.5 + 0.08) for x in col]
        c = mix_rgb(nt, maprange(nt, e, 0.0, 1.0, 0.0, 0.85), c, hl)
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
        ao.inputs["Distance"].default_value = 0.06 * max(size, 0.2)
        ao.samples = 8
        c = mix_rgb(nt, maprange(nt, ao.outputs["AO"], 0.0, 1.0, 0.55, 0.0), c, [x * 0.35 for x in col])
        s["color"] = c
        s["rough"], s["metal"] = None, None
        s["rough_v"] = 0.35 if kind in METALS else 0.72
        s["metal_v"] = 0.0
        s["normal"] = bev.outputs[0]
    else:  # pbr
        e, bev = edge_mask(nt, edge_r, 0.03, 0.22)
        g = noise(nt, 6.0 / max(size * 0.5, 0.05), detail=8.0, rough=0.6)
        g2 = noise(nt, 40.0, detail=4.0, rough=0.5)
        wear = maprange(nt, mix_f(nt, 0.5, e, g), 0.45, 0.75)
        dirt = maprange(nt, g, 0.55, 0.8, 0.0, 0.25)
        if kind == "painted_metal":
            c = mix_rgb(nt, wear, col, hex_rgb("#8e9196"))
            mt = mix_f(nt, wear, 0.0, 1.0)
            rg = mix_f(nt, wear, rough, 0.32)
        elif kind == "anodized":
            c = mix_rgb(nt, maprange(nt, e, 0.3, 1.0), col, hex_rgb("#b9bcc2"))
            mt, rg = 1.0, rough
        elif kind in METALS:
            c = mix_rgb(nt, maprange(nt, e, 0.2, 1.0, 0.0, 0.5), col, [min(1, x * 1.6) for x in col])
            mt = 1.0
            rg = mix_f(nt, maprange(nt, e, 0.2, 1.0), rough, max(0.08, rough - 0.15))
        elif kind in ("wood", "dark_wood"):
            tc = nt.nodes.new("ShaderNodeTexCoord")
            mp = nt.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (0.6, 14.0, 14.0)
            nt.links.new(tc.outputs["Object"], mp.inputs[0])
            wv = nt.nodes.new("ShaderNodeTexWave")
            wv.wave_type = "BANDS"
            wv.inputs["Scale"].default_value = 3.0
            wv.inputs["Distortion"].default_value = 6.0
            wv.inputs["Detail"].default_value = 3.0
            nt.links.new(mp.outputs[0], wv.inputs["Vector"])
            c = mix_rgb(nt, maprange(nt, wv.outputs["Fac"], 0.2, 0.9), [x * 0.62 for x in col], col)
            mt = 0.0
            rg = mix_f(nt, maprange(nt, e, 0.0, 1.0), rough, rough - 0.12)
        elif kind == "emissive":
            c, mt, rg = col, 0.0, rough
            s["emit"] = True
        else:  # polymer, plastic, rubber, leather, fabric, glass, stone, ceramic
            c = mix_rgb(nt, maprange(nt, e, 0.2, 1.0, 0.0, 0.35), col, [min(1, x * 1.7 + 0.04) for x in col])
            mt = 0.0
            rg = mix_f(nt, maprange(nt, g2, 0.3, 0.7), rough - 0.06, rough + 0.06)
        c = mix_rgb(nt, dirt, c, [x * 0.55 for x in col]) if kind not in ("emissive", "glass", "chrome") else c
        if not isinstance(rg, float) and kind not in ("glass", "chrome"):
            rg = mix_f(nt, dirt, rg, min(1.0, rough + 0.2))
        s["color"] = c
        s["rough"] = rg if not isinstance(rg, float) else None
        s["metal"] = mt if not isinstance(mt, float) else None
        s["rough_v"] = rg if isinstance(rg, float) else rough
        s["metal_v"] = mt if isinstance(mt, float) else metal
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.08
        bump.inputs["Distance"].default_value = 0.0006
        nt.links.new(g2, bump.inputs["Height"])
        nt.links.new(bev.outputs[0], bump.inputs["Normal"])
        s["normal"] = bump.outputs[0]
    if isinstance(s["color"], (list, tuple)):
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = (*s["color"][:3], 1.0)
        s["color"] = rgb.outputs[0]
    # wire the preview BSDF
    nt.links.new(s["color"], bsdf.inputs["Base Color"])
    if s["rough"] is not None:
        nt.links.new(s["rough"], bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Roughness"].default_value = s["rough_v"]
    if s["metal"] is not None:
        nt.links.new(s["metal"], bsdf.inputs["Metallic"])
    else:
        bsdf.inputs["Metallic"].default_value = s["metal_v"]
    if s["normal"] is not None:
        nt.links.new(s["normal"], bsdf.inputs["Normal"])
    if kind == "emissive":
        s["emit"] = True
        nt.links.new(s["color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 4.0
    s["bsdf"], s["out"] = bsdf, out
    return m, s


# ---------------------------------------------------------------- bake + final material
def set_bake_route(m, s, what):
    nt = m.node_tree
    em = nt.nodes.get("BAKE_EMIT") or nt.nodes.new("ShaderNodeEmission")
    em.name = "BAKE_EMIT"
    for l in list(em.inputs[0].links):
        nt.links.remove(l)
    if what == "bsdf":
        nt.links.new(s["bsdf"].outputs[0], s["out"].inputs[0])
        return
    src = {"color": s["color"], "rough": s["rough"], "metal": s["metal"]}.get(what)
    if what == "emitmask":
        em.inputs[0].default_value = (1, 1, 1, 1) if s.get("emit") else (0, 0, 0, 1)
    elif src is None:
        v = s["rough_v"] if what == "rough" else s["metal_v"]
        em.inputs[0].default_value = (v, v, v, 1)
    else:
        nt.links.new(src, em.inputs[0])
    nt.links.new(em.outputs[0], s["out"].inputs[0])


def bake_all(ob, mats, tex, outdir, style, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.render.bake.margin = max(4, tex // 128)
    maps = ["color", "normal"] + (["rough", "metal", "ao"] if style in ("pbr", "roblox") else [])
    if any(s.get("emit") for _, s in mats):
        maps.append("emitmask")
    imgs = {}
    for mp in maps:
        img = bpy.data.images.new(f"T_{mp}", tex, tex, alpha=False, float_buffer=False)
        if mp != "color":
            img.colorspace_settings.name = "Non-Color"
        imgs[mp] = img
        for m, s in mats:
            nt = m.node_tree
            tn = nt.nodes.get("BAKE_IMG") or nt.nodes.new("ShaderNodeTexImage")
            tn.name = "BAKE_IMG"
            tn.image = img
            nt.nodes.active = tn
        bpy.ops.object.select_all(action="DESELECT")
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        t = time.time()
        if mp == "normal":
            for m, s in mats:
                set_bake_route(m, s, "bsdf")
            bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", margin=sc.render.bake.margin)
        elif mp == "ao":
            bpy.ops.object.bake(type="AO", margin=sc.render.bake.margin)
        else:
            for m, s in mats:
                set_bake_route(m, s, mp)
            sc.cycles.samples = samples if mp == "color" else 4
            bpy.ops.object.bake(type="EMIT", margin=sc.render.bake.margin)
            sc.cycles.samples = samples
        log(f"bake {mp} {tex}px {time.time() - t:.1f}s")
    # AO into colour (also used where the engine has no AO slot, e.g. Roblox SurfaceAppearance)
    if "ao" in imgs:
        c = np.empty(tex * tex * 4, dtype=np.float32)
        a = np.empty(tex * tex * 4, dtype=np.float32)
        imgs["color"].pixels.foreach_get(c)
        imgs["ao"].pixels.foreach_get(a)
        c = c.reshape(-1, 4)
        a = a.reshape(-1, 4)[:, :1]
        c[:, :3] *= (1.0 - 0.45 * (1.0 - a))
        imgs["color"].pixels.foreach_set(c.ravel())
    os.makedirs(os.path.join(outdir, "textures"), exist_ok=True)
    paths = {}
    for mp, img in imgs.items():
        p = os.path.join(outdir, "textures", f"{mp}.png")
        img.filepath_raw = p
        img.file_format = "PNG"
        img.save()
        paths[mp] = p
    return imgs, paths


def final_material(imgs, style):
    m, nt = new_mat("M_Asset")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])

    def tex(mp):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = imgs[mp]
        return n

    nt.links.new(tex("color").outputs[0], bsdf.inputs["Base Color"])
    if "rough" in imgs:
        nt.links.new(tex("rough").outputs[0], bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Roughness"].default_value = 0.75 if style != "lowpoly" else 0.85
    if "metal" in imgs:
        nt.links.new(tex("metal").outputs[0], bsdf.inputs["Metallic"])
    else:
        bsdf.inputs["Metallic"].default_value = 0.0
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(tex("normal").outputs[0], nm.inputs["Color"])
    nt.links.new(nm.outputs[0], bsdf.inputs["Normal"])
    if "emitmask" in imgs:
        mul = mix_rgb(nt, 1.0, tex("color").outputs[0], tex("emitmask").outputs[0], blend="MULTIPLY")
        nt.links.new(mul, bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 4.0
    return m


# ---------------------------------------------------------------- QA
def bbox(obs_or_me):
    co = []
    for me in obs_or_me:
        a = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", a)
        co.append(a.reshape(-1, 3))
    co = np.concatenate(co) if co else np.zeros((1, 3))
    return co.min(0), co.max(0)


def contact_report(objs):
    """Parts that touch nothing: BVH overlap or AABB gap below a tolerance links two parts."""
    n = len(objs)
    trees, boxes = [], []
    for ob in objs:
        me = ob.data
        bm = bmesh.new()
        bm.from_mesh(me)
        trees.append(BVHTree.FromBMesh(bm))
        bm.free()
        boxes.append(bbox([me]))
    adj = [set() for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            (a0, a1), (b0, b1) = boxes[i], boxes[j]
            gap = np.maximum(0, np.maximum(a0 - b1, b0 - a1))
            g = float(np.linalg.norm(gap))
            size = float(min((a1 - a0).max(), (b1 - b0).max()))
            tol = 0.0015 + 0.01 * size
            if g > tol:
                continue
            if g > 0 or trees[i].overlap(trees[j]):
                adj[i].add(j)
                adj[j].add(i)
            else:
                # AABBs overlap but no triangle crosses: one may sit inside the other, or near-touch
                ci = sum(b0 <= c <= b1 for c, b0, b1 in zip(((a0 + a1) / 2), b0, b1)) == 3
                cj = sum(a0 <= c <= a1 for c, a0, a1 in zip(((b0 + b1) / 2), a0, a1)) == 3
                hit, _, _, d = trees[j].find_nearest(Vector(((a0 + a1) / 2).tolist()))
                if ci or cj or (d is not None and d < tol + size):
                    adj[i].add(j)
                    adj[j].add(i)
    seen, comps = set(), []
    for i in range(n):
        if i in seen:
            continue
        stack, comp = [i], []
        seen.add(i)
        while stack:
            k = stack.pop()
            comp.append(k)
            for j in adj[k]:
                if j not in seen:
                    seen.add(j)
                    stack.append(j)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    floating = [objs[k].name for comp in comps[1:] for k in comp]
    return {"components": len(comps), "floating_parts": floating[:20]}


def mesh_qa(ob, tex):
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    tris = len(bm.faces)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    zero = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
    loose = sum(1 for v in bm.verts if not v.link_faces)
    bm.free()
    q = {"tris": tris, "non_manifold_edges": non_manifold, "boundary_edges": boundary, "zero_area_faces": zero,
         "loose_verts": loose}
    uvl = me.uv_layers.active
    if uvl is None:
        q["uv"] = None
        return q
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    loops = np.empty(nt * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("loops", loops)
    uv = np.empty(len(me.loops) * 2, dtype=np.float32)
    uvl.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)[loops].reshape(-1, 3, 2)
    vidx = np.empty(nt * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", vidx)
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    p3 = co.reshape(-1, 3)[vidx].reshape(-1, 3, 3)
    a3 = 0.5 * np.linalg.norm(np.cross(p3[:, 1] - p3[:, 0], p3[:, 2] - p3[:, 0]), axis=1)
    e1, e2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    auv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    ok = a3 > 1e-9
    dens = np.sqrt(auv[ok] * tex * tex / a3[ok])  # px per metre
    w = a3[ok] / a3[ok].sum()
    mean = float((dens * w).sum())
    std = float(np.sqrt(((dens - mean) ** 2 * w).sum()))
    srt = np.argsort(dens)
    cw = np.cumsum(w[srt])
    p10 = float(dens[srt][np.searchsorted(cw, 0.10)])
    p90 = float(dens[srt][min(len(srt) - 1, np.searchsorted(cw, 0.90))])
    out_of_bounds = float(((uv < -0.001) | (uv > 1.001)).any(axis=(1, 2)).mean())
    # overlap: rasterize at 256 px, count pixels covered by more than one triangle
    R = 256
    grid = np.zeros((R, R), dtype=np.uint16)
    px = uv * R
    for t in range(nt):
        tri = px[t]
        x0, y0 = np.floor(tri.min(0)).astype(int)
        x1, y1 = np.ceil(tri.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, R), min(y1, R)
        if x1 <= x0 or y1 <= y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = tri
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
        inside = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        grid[y0:y1, x0:x1] += inside.astype(np.uint16)
    covered = int((grid >= 1).sum())
    q["uv"] = {"texel_px_per_m": round(mean, 1), "texel_cv": round(std / max(mean, 1e-6), 3),
               "texel_p90_over_p10": round(p90 / max(p10, 1e-6), 2),
               "overlap_ratio": round(int((grid >= 2).sum()) / max(covered, 1), 4),
               "coverage": round(covered / (R * R), 3), "out_of_bounds_tris": round(out_of_bounds, 4)}
    return q


# ---------------------------------------------------------------- render rig
def setup_world():
    sc = bpy.context.scene
    w = bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.05, 0.055, 0.06, 1)
    bg.inputs[1].default_value = 1.0


def backdrop(radius):
    """Seamless cyclorama behind and under the object (faces the camera, which looks along +Y)."""
    bm = bmesh.new()
    R = radius
    pts = [(-R * 4, 0.0)]
    for i in range(1, 12):
        a = math.pi / 2 * i / 12
        pts.append((R * 2.0 + R * 1.2 * math.sin(a), R * 1.2 * (1 - math.cos(a))))
    pts.append((R * 3.2, R * 6))
    rows = []
    for x in (-R * 6, R * 6):
        rows.append([bm.verts.new((x, y, z)) for y, z in pts])
    for i in range(len(pts) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = mesh_from_bm(bm, "Backdrop")
    me.shade_smooth()
    ob = link("Backdrop", me)
    m, nt = new_mat("M_Backdrop")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.075, 0.078, 0.085, 1)
    b.inputs["Roughness"].default_value = 0.9
    nt.links.new(b.outputs[0], out.inputs[0])
    ob.data.materials.append(m)
    return ob


def area_light(name, loc, target, power, size, color):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = power
    ld.size = size
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


VIEWS = {"front34": (-35, 18), "side": (0, 8), "back34": (145, 22), "top34": (-35, 52), "front": (-90, 6)}


def render_views(asset, outdir, size, samples, views, threads, hero=False):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    sc.render.threads_mode = "FIXED"
    sc.render.threads = threads
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    lo, hi = bbox([asset.data])
    centre = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo) / 2)
    pivot = bpy.data.objects.new("Pivot", None)
    sc.collection.objects.link(pivot)
    pivot.location = (centre[0], centre[1], lo[2])
    asset.parent = pivot
    asset.matrix_parent_inverse = pivot.matrix_world.inverted()
    pivot.location = (0, 0, 0)
    target = Vector((0, 0, (hi[2] - lo[2]) / 2))
    backdrop(radius)
    cam_d = bpy.data.cameras.new("Cam")
    cam_d.lens = 60
    cam = bpy.data.objects.new("Cam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    fov = 2 * math.atan(36 / 2 / cam_d.lens)
    dist = radius / math.sin(fov / 2) * 1.08
    R = radius
    # light power scales with the square of the size only: same exposure for a pistol and a truck
    area_light("Key", (-R * 2.2, -R * 2.6, R * 2.8), target, 260 * R * R, R * 1.6, (1.0, 0.95, 0.88))
    area_light("Fill", (R * 2.8, -R * 1.8, R * 1.0), target, 90 * R * R, R * 2.2, (0.85, 0.92, 1.0))
    area_light("Rim", (R * 0.8, R * 3.0, R * 2.4), target, 340 * R * R, R * 1.2, (1.0, 1.0, 1.0))
    paths = {}
    for v in views:
        yaw, el = VIEWS[v]
        pivot.rotation_euler = (0, 0, math.radians(yaw))
        e = math.radians(el)
        # fit the rotated bounding box into 88% of the frame
        dirv = Vector((0, -math.cos(e), math.sin(e)))
        fwd = -dirv
        right = fwd.cross(Vector((0, 0, 1))).normalized()
        up = right.cross(fwd).normalized()
        tfov = math.tan(fov / 2) * 0.88
        rz = Matrix.Rotation(math.radians(yaw), 3, "Z")
        need = 0.0
        for cx in (lo[0] - centre[0], hi[0] - centre[0]):
            for cy in (lo[1] - centre[1], hi[1] - centre[1]):
                for cz in (0.0, hi[2] - lo[2]):
                    c = rz @ Vector((cx, cy, cz)) - target
                    need = max(need, c.dot(dirv) + abs(c.dot(right)) / tfov, c.dot(dirv) + abs(c.dot(up)) / tfov)
        dist = max(need, radius * 0.5)
        cam.location = target + dirv * dist
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        if hero and v == views[0]:
            sc.render.resolution_x, sc.render.resolution_y = size, size
        else:
            sc.render.resolution_x = sc.render.resolution_y = size
        p = os.path.join(outdir, "views", f"{v}.png")
        sc.render.filepath = p
        t = time.time()
        bpy.ops.render.render(write_still=True)
        log(f"render {v} {size}px {time.time() - t:.1f}s")
        paths[v] = p
    pivot.rotation_euler = (0, 0, 0)
    return paths


# ---------------------------------------------------------------- export
def select_only(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def make_lods(asset, ratios):
    lods = []
    dg = bpy.context.evaluated_depsgraph_get()
    for k, r in enumerate(ratios, start=1):
        ob = asset.copy()
        ob.data = asset.data.copy()
        ob.name = f"{asset.name.split('_LOD')[0]}_LOD{k}"
        bpy.context.scene.collection.objects.link(ob)
        mod = ob.modifiers.new("dec", "DECIMATE")
        mod.ratio = r
        mod.use_collapse_triangulate = True
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        ob.modifiers.clear()
        ob.data = me
        lods.append(ob)
    return lods


def export_all(objs, outdir):
    paths = {}
    select_only(objs)
    p = os.path.join(outdir, "asset.glb")
    bpy.ops.export_scene.gltf(filepath=p, export_format="GLB", use_selection=True)
    paths["glb"] = p
    p = os.path.join(outdir, "asset.fbx")
    bpy.ops.export_scene.fbx(filepath=p, use_selection=True, path_mode="COPY", embed_textures=True,
                             mesh_smooth_type="FACE")
    paths["fbx"] = p
    select_only(objs[:1])
    p = os.path.join(outdir, "asset.obj")
    bpy.ops.wm.obj_export(filepath=p, export_selected_objects=True, export_materials=True)
    paths["obj"] = p
    return {k: (v, os.path.getsize(v)) for k, v in paths.items()}


# ---------------------------------------------------------------- main
def build_pipeline(job, outdir):
    spec = job["spec"]
    style = spec["style"]
    st = STYLE[style]
    objs, flipped, errors = [], 0, []
    for p in spec["parts"]:
        try:
            ob, f = build_part(p, style, st)
            objs.append((p, ob))
            flipped += f
        except Exception as e:  # one bad part must not kill the asset
            errors.append(f"{p['id']}: {type(e).__name__}: {e}")
    if not objs:
        raise RuntimeError("no part could be built: " + "; ".join(errors))
    log(f"built {len(objs)} parts ({len(errors)} failed)")
    contact = contact_report([ob for _, ob in objs])
    lo, hi = bbox([ob.data for _, ob in objs])
    size = float((hi - lo).max())
    zr = (float(lo[2]), float(hi[2]))
    mats, cache = [], {}
    for p, ob in objs:
        key = (p["mat"], p.get("color"))
        if key not in cache:
            m, s = build_material(f"M_{len(cache)}_{p['mat']}", p["mat"], p.get("color"), style, size, zr)
            cache[key] = m
            mats.append((m, s))
        ob.data.materials.append(cache[key])
    # join into one game mesh at identity
    target = link("Asset", bpy.data.meshes.new("Asset"))
    select_only([target] + [ob for _, ob in objs])
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.join()
    asset = bpy.context.view_layer.objects.active
    asset.name = "Asset_LOD0"
    # UVs
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(margin=0.006, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    log("uv done")
    tex = job.get("tex", 1024)
    imgs, tex_paths = bake_all(asset, mats, tex, outdir, style, job.get("bake_samples", 16))
    fm = final_material(imgs, style)
    asset.data.materials.clear()
    asset.data.materials.append(fm)
    for poly in asset.data.polygons:
        poly.material_index = 0
    qa = mesh_qa(asset, tex)
    lo, hi = bbox([asset.data])
    res = {"parts_built": len(objs), "part_errors": errors, "flipped_fixed": flipped, "contact": contact,
           "dims": [round(float(x), 4) for x in (hi - lo)], "qa": qa, "tex": tex, "textures": tex_paths}
    return asset, res


def build_baseline(job, outdir):
    spec = job["spec"]
    objs = []
    for i, p in enumerate(spec["parts"]):
        t = p["type"]
        s = p["size"]
        if t == "cube":
            bm = bm_box(s)
        elif t == "cylinder":
            bm = bm_cone(s[0] / 2, s[0] / 2, s[2], "z", 24)
            bm.transform(Matrix.Diagonal(Vector((1, s[1] / max(s[0], 1e-6), 1, 1))))
        elif t == "cone":
            bm = bm_cone(s[0] / 2, 0.0, s[2], "z", 24)
            bm.transform(Matrix.Diagonal(Vector((1, s[1] / max(s[0], 1e-6), 1, 1))))
        else:
            bm = bm_sphere(0.5, s, 24)
        bm.transform(world_matrix(p["pos"], p["rot"]))
        ob = link(f"p{i}", mesh_from_bm(bm, f"p{i}"))
        m, nt = new_mat(f"M{i}")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        b.inputs["Base Color"].default_value = (*hex_rgb(p["color"]), 1)
        b.inputs["Metallic"].default_value = p["metallic"]
        b.inputs["Roughness"].default_value = p["roughness"]
        nt.links.new(b.outputs[0], out.inputs[0])
        ob.data.materials.append(m)
        objs.append(ob)
    contact = contact_report(objs)
    target = link("Asset", bpy.data.meshes.new("Asset"))
    select_only([target] + objs)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.join()
    asset = bpy.context.view_layer.objects.active
    asset.name = "Asset_LOD0"
    qa = mesh_qa(asset, 1024)
    lo, hi = bbox([asset.data])
    return asset, {"parts_built": len(objs), "contact": contact, "dims": [round(float(x), 4) for x in (hi - lo)],
                   "qa": qa}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    job = json.load(open(argv[0], encoding="utf-8"))
    outdir = os.path.abspath(argv[1])
    os.makedirs(os.path.join(outdir, "views"), exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    threads = int(job.get("threads", 4))
    bpy.context.scene.render.threads_mode = "FIXED"
    bpy.context.scene.render.threads = threads
    res = {"ok": False}
    try:
        setup_world()
        if job.get("mode") == "baseline":
            asset, res = build_baseline(job, outdir)
        else:
            asset, res = build_pipeline(job, outdir)
        r = job.get("render", {})
        res["views"] = render_views(asset, outdir, r.get("size", 512), r.get("samples", 24),
                                    r.get("views", ["front34", "side", "back34", "top34"]), threads)
        if job.get("final") and job.get("mode") != "baseline":
            lods = make_lods(asset, [0.5, 0.25])
            res["lod_tris"] = [res["qa"]["tris"]] + [mesh_qa(o, res["tex"])["tris"] for o in lods]
            asset.parent = None
            res["exports"] = export_all([asset] + lods, outdir)
        res["ok"] = True
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
        res["trace"] = traceback.format_exc()[-2000:]
    res["seconds"] = round(time.time() - T0, 1)
    res["log"] = LOG
    with open(os.path.join(outdir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)


main()
