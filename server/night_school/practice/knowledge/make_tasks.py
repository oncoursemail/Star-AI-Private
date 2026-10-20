"""Build the knowledge-school practice pools (non-code tasks with checkable answers), 2026-10-18.

    python server/night_school/practice/knowledge/make_tasks.py

Writes server/night_school/practice/knowledge-<domain>-20261018.json (one list of tasks per domain, the night-school
pool shape) and knowledge-references-20261018.jsonl (id -> a reference answer; kept out of the pool like the
conductor's references). tests/test_knowledge_checks.py checks every reference passes, trivial answers fail, keys are
valid and no two prompts are near-duplicates.

Facts come from the sources the knowledge service indexes (Wikipedia pages of topics/wikipedia-topics.json, OpenStax
textbooks, the Godot and Blender manuals, CNP3); every task links the page it rests on. Numeric tasks are computed
here from the stated formula, so the key is exact by construction.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import random

OUT = Path(__file__).resolve().parents[1]
DATE = "20261018"
WIKI = "https://en.wikipedia.org/wiki/"
GODOT = "https://docs.godotengine.org/en/latest/"
BLENDER = "https://docs.blender.org/manual/en/latest/"
OPENSTAX = "https://openstax.org/details/books/"
CNP3 = "https://www.computer-networking.info/"

TAIL = " End your reply with one line of the form `Answer: ...`."
TAIL_LETTER = " Reply with the letter of the correct option on a final line `Answer: X`."
TAIL_ORDER = " End with one line `Answer: ...` listing them in order, separated by commas."


def exact(q, accept, urls, topic=""):
    return ("exact", q + TAIL, {"type": "exact", "accept": accept if isinstance(accept, list) else [accept]}, urls, topic,
            "Answer: " + (accept[0] if isinstance(accept, list) else accept))


def choice(q, options, correct, urls, topic=""):
    letters = "ABCD"
    text = q + "\n" + "\n".join(f"{letters[i]}) {opt}" for i, opt in enumerate(options)) + TAIL_LETTER
    key = {"type": "choice", "options": {letters[i]: opt for i, opt in enumerate(options)}, "correct": letters[correct]}
    return ("choice", text, key, urls, topic, f"Answer: {letters[correct]}")


def order(q, items, urls, topic=""):
    return ("order", q + TAIL_ORDER, {"type": "order", "items": [i[1] for i in items]}, urls, topic,
            "Answer: " + ", ".join(i[0] for i in items))


def match(q, pairs, urls, topic=""):
    key = {"type": "match", "pairs": [[p[1], p[3]] for p in pairs]}
    reference = "\n".join(f"{p[0]}: {p[2]}." for p in pairs)
    return ("match", q + " Write one line per pair as `term: meaning`.", key, urls, topic, reference)


def short(q, required, reference, urls, topic="", min_required=None, forbidden=None):
    key = {"type": "short", "required": required}
    if min_required is not None:
        key["min_required"] = min_required
    if forbidden:
        key["forbidden"] = forbidden
    return ("short", q, key, urls, topic, reference)


def rubric(q, required, reference, urls, topic="", min_required=None, min_words=40):
    key = {"type": "rubric", "required": required, "min_words": min_words}
    if min_required is not None:
        key["min_required"] = min_required
    return ("rubric", q, key, urls, topic, reference)


def numeric(q, value, urls, topic="", tol=None, rel=0.01, unit=None, shown=None):
    key = {"type": "numeric", "value": value}
    if tol is not None:
        key["tol"] = tol
    else:
        key["rel"] = rel
    if unit:
        key["unit"] = unit
    shown = shown if shown is not None else (f"{value:.4g}" if isinstance(value, float) else str(value))
    return ("numeric", q + TAIL, key, urls, topic, f"Answer: {shown}" + (f" {unit}" if unit else ""))


def w(*titles):
    return [WIKI + t.replace(" ", "_") for t in titles]


# =====================================================================================================================
# Domain fact tables. Each entry is produced by one of the helpers above.
# =====================================================================================================================

def game_design():
    T = []
    T += [exact("In the MDA framework for game design, what do the letters M, D and A stand for? Give the three words.", ["Mechanics, Dynamics, Aesthetics", "Mechanics Dynamics Aesthetics"], w("MDA framework"), "frameworks")]
    T += [exact("Which psychologist described the mental state of 'flow', the basis of the flow channel between boredom and anxiety used in difficulty design?", ["Csikszentmihalyi", "Mihaly Csikszentmihalyi"], w("Flow (psychology)"), "flow")]
    T += [choice("A positive feedback loop in a game economy tends to:", ["bring players who fall behind back towards the leader", "widen the gap between a leading player and the rest", "keep every player at the same resource level", "remove randomness from outcomes"], 1, w("Positive feedback", "Game balance"), "balance")]
    T += [choice("Which reward schedule produces the most persistent behaviour and is the model for loot drops and slot machines?", ["fixed interval", "fixed ratio", "variable ratio", "continuous reinforcement"], 2, w("Variable ratio schedule", "Reinforcement"), "psychology")]
    T += [exact("What is the name of the game-design pattern where a loop of anticipation, activity and reward is repeated to keep players engaged, often criticised when used to manipulate?", ["compulsion loop", "core loop"], w("Compulsion loop"), "loops")]
    T += [exact("What term describes a conflict between what a game's story says about a character and what its mechanics reward the player for doing?", ["ludonarrative dissonance"], w("Ludonarrative dissonance"), "narrative")]
    T += [choice("Permadeath in a game means:", ["the player loses progress to the last checkpoint", "a dead character is gone for good and cannot be reloaded", "enemies respawn permanently", "the game ends after one death with a cutscene"], 1, w("Permadeath"), "systems")]
    T += [exact("In the Elo rating system, if two players have equal ratings, what is each player's expected score for a game (as a decimal)?", ["0.5", ".5", "50%"], w("Elo rating system"), "matchmaking")]
    T += [choice("Rubber banding in racing games refers to:", ["cars snapping back to the track after a crash", "AI opponents speeding up or slowing down to stay close to the player", "the elastic physics of tyres", "the player's controller cable"], 1, w("Rubber banding (video games)"), "balance")]
    T += [exact("Which 1993 id Software shooter popularised the first-person shooter genre and shareware distribution of its first episode?", ["Doom"], w("Doom (1993 video game)"), "history")]
    T += [exact("What falling-block puzzle game, created by Alexey Pajitnov in 1984, has pieces called tetrominoes?", ["Tetris"], w("Tetris"), "history")]
    T += [choice("A 'vertical slice' in game development is:", ["a prototype of one feature with placeholder art", "a fully polished slice of the game showing every system at final quality", "the first level only, unfinished", "the technical design document"], 1, w("Vertical slice"), "production")]
    T += [exact("What is the term for the hidden mechanic where a game's difficulty adjusts itself to the player's measured performance?", ["dynamic difficulty adjustment", "dynamic game difficulty balancing", "dynamic difficulty"], w("Dynamic game difficulty balancing"), "difficulty")]
    T += [choice("Fog of war in strategy games hides:", ["the player's own units from themselves", "parts of the map the player has no units observing", "the user interface during cutscenes", "the enemy's score"], 1, w("Fog of war"), "systems")]
    T += [exact("Which 2007 Valve puzzle game is built on a gun that creates two linked portals?", ["Portal"], w("Portal (video game)"), "history")]
    T += [exact("In Nintendo's platformer design, what is the name of the structure where a mechanic is introduced safely, developed, twisted and then concluded, often described with four Japanese narrative beats?", ["kishotenketsu", "kishōtenketsu", "ki-sho-ten-ketsu"], w("Kishōtenketsu"), "level-flow")]
    T += [choice("A loot box is best described as:", ["a chest placed in the level with fixed contents", "a purchasable item with a randomised set of rewards", "the inventory screen", "a daily login bonus"], 1, w("Loot box"), "monetisation")]
    T += [exact("A battle pass monetisation model typically rewards players for:", ["completing challenges and levelling the pass during a season", "progressing through tiers during a season"], w("Battle pass"), "monetisation")]
    T += [exact("What is the name for the smallest version of a product with just enough features to learn from real players?", ["minimum viable product", "MVP"], w("Minimum viable product"), "production")]
    T += [exact("In a roguelike, what structural feature means every run presents a different dungeon?", ["procedural generation", "procedurally generated levels", "random generation"], w("Roguelike", "Procedural generation"), "systems")]
    T += [choice("Emergent gameplay means:", ["gameplay scripted by designers for a cutscene", "complex situations arising from simple rules interacting, not authored directly", "the tutorial level", "the final boss encounter"], 1, w("Emergent gameplay"), "systems")]
    T += [exact("Which Chilean-born designer's book 'The Art of Game Design' is organised as a deck of 'lenses'? Give the surname.", ["Schell", "Jesse Schell"], w("Game design"), "literature")]
    T += [choice("The 'cooldown' mechanic exists mainly to:", ["make a strong ability unavailable for a time so it cannot be spammed", "slow the game's frame rate", "cool the player's hardware", "hide the ability from the UI"], 0, w("Cooldown (video games)"), "systems")]
    T += [exact("Which 2018 platformer by Maddy Thorson about climbing a mountain is praised for an 'Assist Mode' that lets players tune difficulty?", ["Celeste"], w("Celeste (video game)"), "difficulty")]
    T += [exact("What do you call a mode where many players compete until one player or team remains, with a shrinking play area?", ["battle royale"], w("Battle royale game"), "genres")]
    T += [choice("Gamification is:", ["making a game harder", "applying game-like elements such as points and badges to non-game activities", "the testing phase of a game", "porting a game to a new console"], 1, w("Gamification"), "concepts")]
    T += [exact("In game theory, what is the name for a situation where no player can improve their outcome by changing only their own strategy?", ["Nash equilibrium"], w("Game theory"), "theory")]
    T += [choice("A game design document (GDD) is:", ["the legal contract with the publisher", "a living description of the game's vision, mechanics and content for the team", "the source code repository", "the marketing trailer script"], 1, w("Game design document"), "production")]
    T += [exact("What is the term for a short, intense development event where teams make a game in about 48 hours?", ["game jam"], w("Game jam"), "production")]
    T += [order("Put these difficulty-curve stages in the order a well-designed level introduces a new mechanic (Nintendo-style).", [("introduce it safely", "introduce|safe"), ("develop it with variation", "develop|variation"), ("twist it with a surprise", "twist|surprise"), ("conclude with a final test", "conclude|final test")], w("Kishōtenketsu", "Level design"), "level-flow")]
    T += [match("Match each term from game economics to its meaning.", [("faucet", "faucet", "a source that creates currency, like quest rewards", "creat|source|reward"), ("sink", "sink", "something that removes currency, like repair costs", "remove|cost|destroy"), ("inflation", "inflation", "prices rising because too much currency chases too few goods", "price|rising|too much")], w("Virtual economy", "Game economy"), "economy")]
    T += [short("Name two reasons designers add a 'sink' to a virtual economy.", [["inflation|too much (currency|gold|money)|value of (currency|gold|money)"], ["sink|remove|drain|take .* out"]], "A sink removes currency from the economy; without sinks, rewards pile up and the currency inflates until items lose value.", w("Virtual economy"), "economy")]
    T += [short("Explain what 'juice' or 'game feel' adds to a jump without changing its logic. Name at least two techniques.", [["screen ?shake|particles?|squash|stretch|sound|animation|hit ?stop|freeze"], ["feedback|responsive|feel|satisfying"]], "Game feel comes from feedback: squash and stretch on landing, a dust particle burst, a short sound and a tiny screen shake make the same jump feel responsive and satisfying.", w("Game feel"), "feel")]
    T += [choice("The 'core gameplay loop' is:", ["the main menu flow", "the short cycle of actions a player repeats most of the time, such as explore, fight, loot", "the game's save system", "the credits sequence"], 1, w("Core gameplay loop", "Gameplay"), "loops")]
    T += [exact("What rating system, newer than Elo, also tracks a rating deviation (uncertainty) for each player?", ["Glicko", "Glicko rating system", "Glicko-2"], w("Glicko rating system"), "matchmaking")]
    T += [choice("Which of these is a diegetic UI element?", ["a health bar at the top of the screen", "an ammo count displayed on the in-world gun", "the pause menu", "a tooltip"], 1, w("Diegesis", "Game user interface"), "ui")]
    T += [exact("What 2016 Roblox-era term describes a game that keeps players returning with scheduled events and updates after launch, treated as an ongoing service?", ["live service", "games as a service", "live-service game", "GaaS"], w("Games as a service"), "production")]
    T += [exact("Which free-to-play social deduction game of 2018 has crewmates and impostors on a spaceship?", ["Among Us"], w("Among Us"), "history")]
    T += [choice("'Scope creep' describes:", ["the camera zooming in slowly", "features being added beyond the agreed plan so the project grows uncontrolled", "the player's view narrowing when aiming", "a bug that spreads between levels"], 1, w("Scope creep"), "production")]
    T += [exact("In a Skinner box, the animal learns to press a lever for a reward; what field of psychology does this experiment belong to?", ["operant conditioning", "behaviourism", "behaviorism"], w("Skinner box", "Reinforcement"), "psychology")]
    return T


def level_design():
    T = []
    T += [exact("What is the level-design term for a rough blockout of a level made from untextured grey geometry to test layout and flow?", ["greybox", "greyboxing", "graybox", "blockout", "whitebox"], w("Level design"), "process")]
    T += [exact("Walt Disney's Imagineers used the word 'weenie' for what level-design idea?", ["a visual magnet that draws visitors toward a landmark", "landmark", "a landmark that draws people onward", "visual magnet"], w("Weenie (architecture)"), "wayfinding")]
    T += [choice("A 'choke point' in a multiplayer map is:", ["a wide open arena", "a narrow passage all traffic must pass through, concentrating fights", "the spawn room", "an invisible wall"], 1, w("Choke point"), "layout")]
    T += [choice("Environmental storytelling tells the story through:", ["voiced cutscenes", "the arrangement of objects and traces in the world that players read themselves", "the pause menu lore tab", "loading-screen tips"], 1, w("Environmental storytelling"), "narrative")]
    T += [exact("Which pathfinding algorithm extends Dijkstra's algorithm with a heuristic estimate of the remaining distance?", ["A*", "A star", "A-star"], w("A* search algorithm"), "navigation")]
    T += [exact("What data structure made of connected convex polygons do game engines use to describe where characters can walk?", ["navigation mesh", "navmesh", "nav mesh"], w("Navigation mesh"), "navigation")]
    T += [choice("Occlusion culling improves performance by:", ["lowering texture resolution far away", "not rendering objects hidden behind other objects", "deleting objects the player has passed", "freezing physics off-screen"], 1, w("Occlusion culling"), "performance")]
    T += [exact("What is the name of the gradient-noise function invented by Ken Perlin in 1983 and widely used for terrain?", ["Perlin noise"], w("Perlin noise"), "procedural")]
    T += [choice("A metroidvania level structure is characterised by:", ["strictly linear stages", "an interconnected map where new abilities unlock earlier blocked paths", "randomly generated rooms every run", "one giant open field with no gating"], 1, w("Metroidvania"), "structure")]
    T += [exact("What is the term for the design practice of guiding players with light, colour and shape so they find the path without a map?", ["wayfinding", "signposting"], w("Wayfinding"), "wayfinding")]
    T += [choice("A 'hub' level is:", ["the first tutorial room", "a central area the player returns to in order to reach other areas", "the final boss arena", "a hidden bonus stage"], 1, w("Hub (video games)"), "structure")]
    T += [exact("What photographic composition rule places points of interest on the lines that divide the frame into three equal parts each way?", ["rule of thirds"], w("Rule of thirds"), "composition")]
    T += [exact("Which cellular automaton by John Conway is often used as a first example of procedural cave or pattern generation?", ["Game of Life", "Conway's Game of Life", "Life"], w("Conway's Game of Life"), "procedural")]
    T += [choice("Line of sight blockers in a shooter map are placed mainly to:", ["make the map load faster", "break long sight lines so players can move without being shot from across the map", "hide secrets", "mark team bases"], 1, w("Line of sight (video games)", "Cover system"), "layout")]
    T += [exact("What invisible 2D tree structure divides space recursively into four quadrants, used for culling and collision in 2D?", ["quadtree"], w("Quadtree"), "data")]
    T += [exact("What is the 3D equivalent of a quadtree, dividing space into eight children?", ["octree"], w("Octree"), "data")]
    T += [choice("A Voronoi diagram partitions a plane into regions based on:", ["distance to the nearest of a set of seed points", "colour", "elevation above sea level", "player spawn order"], 0, w("Voronoi diagram"), "procedural")]
    T += [choice("The wave function collapse algorithm for level generation works by:", ["simulating quantum physics", "placing tiles so that each neighbour pair is allowed by the sample, collapsing the least-constrained cell first", "random walks only", "hand-placed rooms connected by corridors"], 1, w("Wave function collapse"), "procedural")]
    T += [exact("In a game camera, what name is given to the angle that defines how much of the scene is visible, often set around 60 to 90 degrees?", ["field of view", "FOV"], w("Field of view"), "camera")]
    T += [exact("What is the term for the stage-by-stage division of a platformer where a sequence of obstacles is designed as a unit with a save point at the end?", ["checkpoint", "checkpoints"], w("Checkpoint (video games)"), "flow")]
    T += [choice("'Spawn camping' is:", ["waiting at a spawn point to attack players as they appear", "building a tent in the game", "respawning quickly", "a spawn point for campfires"], 0, w("Spawn camping"), "multiplayer")]
    T += [exact("What is the name of the painting technique, also used in level art, where distant objects are paler, bluer and lower in contrast?", ["atmospheric perspective", "aerial perspective"], w("Atmospheric perspective"), "art")]
    T += [exact("Which Nintendo franchise's 2017 open-world entry used a 'triangle rule' of placing landmarks so that terrain hides and reveals destinations?", ["The Legend of Zelda: Breath of the Wild", "Breath of the Wild", "Zelda"], w("The Legend of Zelda: Breath of the Wild"), "open-world")]
    T += [choice("Fast travel exists primarily to:", ["make the world smaller to render", "reduce repeated traversal time once an area has been explored", "add a loading screen", "stop players from exploring"], 1, w("Fast travel"), "flow")]
    T += [order("Order these steps of a typical level production pipeline from first to last.", [("paper layout", "paper|sketch"), ("greybox blockout", "grey|gray|blockout"), ("playtest and iterate", "playtest|iterate"), ("art pass", "art pass|art")], w("Level design", "Playtest"), "process")]
    T += [match("Match each level-design term to its definition.", [("critical path", "critical path", "the route a player must take to finish", "must|finish|required|main route"), ("golden path", "golden path", "the intended ideal route designers expect most players to follow", "intended|ideal|expect"), ("breadcrumbing", "breadcrumb", "a trail of small rewards or lights leading the player onward", "trail|lead|onward|rewards?")], w("Breadcrumb (navigation)", "Level design"), "wayfinding")]
    T += [short("Explain why a kill zone or 'arena' in a shooter level usually has at least two entrances for the defenders' opponents.", [["flank|second (entrance|route)|alternative|another (way|entrance|route)"], ["camp|stalemate|hold|defend|choke"]], "With a single entrance defenders can camp the choke point and the fight stalls; a second entrance lets attackers flank, which keeps the arena moving.", w("Choke point", "Kill zone"), "layout")]
    T += [exact("What term describes a locked door or gap that can only be passed once the player gains a specific ability (a 'gate')?", ["ability gate", "gating", "gate", "ability gating", "lock and key"], w("Metroidvania"), "structure")]
    T += [choice("Level of detail (LOD) means:", ["more detailed textures for important enemies", "swapping to simpler meshes as objects get farther from the camera", "the depth of the story", "how many secrets a level has"], 1, w("Level of detail (computer graphics)"), "performance")]
    T += [exact("What is the common term for a loop in a 3D maze or dungeon that lets players return without retracing the same corridor, improving flow?", ["loop", "loops", "circular route", "circuit"], w("Level design", "Maze"), "layout")]
    T += [choice("In urban design, 'desire lines' are:", ["the paths people actually take, visible as worn tracks, often cutting corners", "painted lane markings", "the architect's sketch lines", "lines of sight to a monument"], 0, w("Urban design"), "wayfinding")]
    T += [exact("Which Dijkstra-era shortest-path algorithm guarantees the optimal path on a graph with non-negative edge weights and no heuristic?", ["Dijkstra's algorithm", "Dijkstra"], w("Dijkstra's algorithm"), "navigation")]
    T += [exact("What simple algorithm fills a connected region of cells of the same value, used to find rooms or islands in a tile map?", ["flood fill"], w("Flood fill"), "procedural")]
    T += [choice("An obby (obstacle course) in Roblox terms is closest to which classic genre?", ["puzzle", "platformer", "racing", "strategy"], 1, w("Obstacle course", "Platform game"), "genres")]
    T += [exact("Which triangulation of a point set maximises the minimum angle of its triangles and is the dual of the Voronoi diagram?", ["Delaunay triangulation", "Delaunay"], w("Delaunay triangulation"), "procedural")]
    T += [short("Give two ways to make a jump in a platformer feel fair when the player misses it.", [["coyote time|grace|late jump|jump buffer|forgiv|generous hitbox|smaller hitbox"], ["checkpoint|respawn (nearby|quickly|close)|short (retry|restart)|instant"]], "Give coyote time and a jump buffer so near-misses still count, and respawn quickly at a nearby checkpoint so a miss costs seconds, not minutes.", w("Platform game", "Checkpoint (video games)"), "flow")]
    T += [choice("Binary space partitioning (BSP) was famously used in Doom to:", ["compress textures", "sort and render wall segments quickly by splitting the map with lines", "generate enemies", "store save games"], 1, w("Binary space partitioning"), "data")]
    T += [exact("What name is given to a large, mostly empty area at the start of a map where players can learn controls without danger?", ["safe zone", "safe area", "tutorial area", "sandbox", "hub"], w("Tutorial (video games)"), "flow")]
    T += [choice("A heightmap stores terrain as:", ["a list of triangles", "a grayscale image where brightness is elevation", "a text description", "a navigation mesh"], 1, w("Heightmap"), "terrain")]
    T += [exact("In pacing terms, what does a 'breather' section after a hard fight provide?", ["rest", "relief", "a rest", "release of tension", "recovery"], w("Pacing"), "flow")]
    return T


def animation_3d():
    T = []
    T += [exact("How many basic principles of animation did Disney animators Ollie Johnston and Frank Thomas describe in 'The Illusion of Life'?", ["12", "twelve"], w("Twelve basic principles of animation"), "principles")]
    T += [exact("Which animation principle prepares the audience for an action, like a crouch before a jump?", ["anticipation"], w("Anticipation (animation)"), "principles")]
    T += [exact("Which animation principle makes a bouncing ball flatten on impact and lengthen in the air while keeping its volume?", ["squash and stretch"], w("Squash and stretch"), "principles")]
    T += [choice("'Follow through and overlapping action' means:", ["everything stops at the same frame", "parts of a body keep moving after the main body stops, and move at different rates", "the camera follows the character", "two animations play at once"], 1, w("Twelve basic principles of animation"), "principles")]
    T += [exact("What is the term for the drawings between keyframes that fill in the motion?", ["inbetweens", "in-betweens", "inbetweening", "tweening", "tweens"], w("Inbetweening"), "process")]
    T += [exact("In skeletal animation, what is the process of binding mesh vertices to bones with weights called?", ["skinning", "weight painting", "rigging"], w("Skinning (animation)"), "rigging")]
    T += [choice("Inverse kinematics (IK) computes:", ["joint rotations from a desired end-effector position", "the end position from given joint rotations", "the colour of a bone", "the frame rate"], 0, w("Inverse kinematics"), "rigging")]
    T += [choice("Forward kinematics (FK) computes:", ["joint rotations from a desired hand position", "the position of the hand from the chain of joint rotations", "the mesh topology", "the texture coordinates"], 1, w("Forward kinematics"), "rigging")]
    T += [exact("What rotation representation with four components avoids gimbal lock and interpolates smoothly with slerp?", ["quaternion", "quaternions"], w("Quaternion", "Quaternions and spatial rotation"), "math")]
    T += [exact("What is the name of the problem where two rotation axes of an Euler-angle rig align and a degree of freedom is lost?", ["gimbal lock"], w("Gimbal lock"), "math")]
    T += [choice("A blend shape (morph target) stores:", ["a second skeleton", "per-vertex offsets from a base mesh for a target pose, such as a smile", "a texture layer", "a physics constraint"], 1, w("Blend shape", "Morph target animation"), "facial")]
    T += [exact("In Blender, what is the shortcut key for Grab/move in the 3D Viewport?", ["G"], [BLENDER + "scene_layout/object/editing/transform/move.html"], "blender")]
    T += [exact("In Blender, which key toggles between Object Mode and Edit Mode?", ["Tab"], [BLENDER + "editors/3dview/modes.html"], "blender")]
    T += [exact("In Blender, what is the shortcut for Extrude in Edit Mode?", ["E"], [BLENDER + "modeling/meshes/editing/edge/extrude_edges.html"], "blender")]
    T += [choice("A subdivision surface modifier:", ["removes faces to lower the polygon count", "smooths a mesh by subdividing its faces (Catmull-Clark by default)", "adds a skeleton", "bakes lighting"], 1, [BLENDER + "modeling/modifiers/generate/subdivision_surface.html"] + w("Subdivision surface"), "modeling")]
    T += [exact("What do modellers call a continuous ring of edges that follows the muscle flow of a face, important for clean deformation?", ["edge loop", "edge loops"], w("Edge loop"), "topology")]
    T += [choice("Retopology is:", ["recolouring a texture", "rebuilding a high-poly sculpt as a clean, lower-poly mesh with good edge flow", "deleting the UV map", "converting a mesh to a point cloud"], 1, w("Retopology"), "topology")]
    T += [exact("UV mapping flattens a 3D surface into which 2D space so a texture can be painted on it? Name the two coordinate letters.", ["U and V", "UV", "u v"], w("UV mapping"), "texturing")]
    T += [choice("A normal map:", ["changes the silhouette of the mesh", "fakes small surface detail by perturbing lighting normals without adding geometry", "stores the mesh's weights", "is only used for shadows"], 1, w("Normal mapping"), "texturing")]
    T += [choice("Which map actually moves vertices to add real geometric detail?", ["normal map", "bump map", "displacement map", "ambient occlusion map"], 2, w("Displacement mapping"), "texturing")]
    T += [exact("In physically based rendering, which two main workflows describe surfaces: metallic/roughness and ...?", ["specular/glossiness", "specular glossiness", "spec/gloss"], w("Physically based rendering"), "shading")]
    T += [exact("Ragdoll physics animates a character's fall by treating the body as what?", ["connected rigid bodies", "rigid bodies joined by constraints", "articulated rigid bodies", "rigid bodies"], w("Ragdoll physics"), "physics")]
    T += [choice("Motion capture (mocap) records:", ["the artist's keyframes", "the movement of real actors or objects to drive digital characters", "camera shutter speed", "mesh topology"], 1, w("Motion capture"), "process")]
    T += [exact("What is the term for the path a value takes between keyframes, edited as a curve with handles in a graph editor?", ["f-curve", "animation curve", "interpolation curve", "spline", "bezier curve", "fcurve"], w("Bézier curve", "Keyframe"), "process")]
    T += [exact("A walk cycle usually loops after how many steps (one with each foot)?", ["2", "two"], w("Walk cycle"), "cycles")]
    T += [choice("Easing in animation refers to:", ["making an object translucent", "speeding up at the start or slowing down at the end instead of constant speed", "making the UI simpler", "removing frames"], 1, w("Easing", "Twelve basic principles of animation"), "timing")]
    T += [exact("Which animation principle says a character should hold a pose that reads clearly in silhouette?", ["staging", "solid drawing", "appeal"], w("Twelve basic principles of animation"), "principles")]
    T += [exact("What transformation matrix dimension is used for 3D rotation plus translation in homogeneous coordinates?", ["4x4", "4 by 4", "4×4"], w("Homogeneous coordinates", "Transform matrix"), "math")]
    T += [choice("The dot product of two unit vectors gives:", ["a vector perpendicular to both", "the cosine of the angle between them", "their sum", "their cross-sectional area"], 1, w("Dot product"), "math")]
    T += [choice("The cross product of two 3D vectors gives:", ["a scalar", "a vector perpendicular to both, with length equal to the parallelogram area", "their angle in degrees", "their average"], 1, w("Cross product"), "math")]
    T += [exact("What is the name for the spherical interpolation between two rotations that keeps constant angular speed?", ["slerp", "spherical linear interpolation"], w("Slerp"), "math")]
    T += [choice("Onion skinning lets an animator:", ["peel textures off a mesh", "see faint copies of previous and next frames while drawing the current one", "export to video", "bake physics"], 1, w("Onion skinning"), "process")]
    T += [exact("Which 3D application has a 'Dope Sheet' and 'Graph Editor', uses Cycles and EEVEE render engines, and is free software?", ["Blender"], w("Blender (software)"), "blender")]
    T += [exact("Which rendering technique traces the path of light rays per pixel to compute reflections and shadows physically?", ["ray tracing", "raytracing", "path tracing"], w("Ray tracing (graphics)"), "rendering")]
    T += [choice("Rasterisation renders a triangle by:", ["tracing rays from the camera", "determining which pixels the projected triangle covers and shading them", "subdividing it until it is a point", "solving a wave equation"], 1, w("Rasterisation"), "rendering")]
    T += [order("Order these stages of a typical 3D character pipeline.", [("concept art", "concept"), ("modelling", "model"), ("UV unwrapping and texturing", "uv|textur"), ("rigging", "rig"), ("animation", "animat")], w("3D modeling", "Rigging (animation)"), "process")]
    T += [match("Match each Blender mode to what it edits.", [("Object Mode", "object mode", "whole objects: position, rotation, scale", "whole|position|rotation|scale|transform"), ("Edit Mode", "edit mode", "the mesh's vertices, edges and faces", "vert|edge|face|mesh"), ("Sculpt Mode", "sculpt mode", "the surface with brushes like clay", "brush|clay|surface"), ("Pose Mode", "pose mode", "an armature's bones for posing", "bone|armature|pos")], [BLENDER + "editors/3dview/modes.html"], "blender")]
    T += [short("Explain why a game character mesh is usually built from quads rather than triangles during modelling, even though the GPU renders triangles.", [["edge ?loop|edge flow|topology|deform|subdiv"], ["triangl|convert|render"]], "Quads give clean edge loops that follow the body, so the mesh deforms and subdivides predictably; the engine converts them to triangles at export, which is trivial.", w("Polygon mesh", "Edge loop"), "topology")]
    T += [short("Name two reasons to keep a game mesh 'low poly' and one technique that keeps it looking detailed.", [["performance|frame ?rate|memory|draw|budget|faster|vertex count|cheap"], ["normal map|bake|baking|texture|lod|level of detail"]], "Low-poly meshes are cheaper to render and store, keeping frame rate and memory within budget; detail is baked from a high-poly sculpt into normal maps so the surface still reads as detailed.", w("Low poly", "Normal mapping"), "modeling")]
    T += [exact("What is the name of the Blender render engine designed for real-time viewport rendering, introduced in 2.80?", ["EEVEE", "Eevee"], [BLENDER + "render/eevee/introduction.html"], "blender")]
    return T


def art_fundamentals():
    T = []
    T += [exact("On the traditional (RYB) painter's colour wheel, what is the complementary colour of red?", ["green"], w("Complementary colors", "Color wheel"), "colour")]
    T += [exact("In the RGB additive model, what colour is produced by mixing full red and full green light?", ["yellow"], w("RGB color model"), "colour")]
    T += [exact("In the RGB model, what is the complementary colour of blue (the colour opposite it on the RGB wheel)?", ["yellow"], w("Complementary colors", "RGB color model"), "colour")]
    T += [choice("Analogous colours are:", ["opposite each other on the wheel", "next to each other on the wheel", "black, white and grey", "the three primaries"], 1, w("Analogous colors"), "colour")]
    T += [exact("What are the three primary colours of the subtractive CMY printing model? Name them.", ["cyan, magenta, yellow", "cyan magenta yellow", "cyan, magenta and yellow"], w("CMYK color model"), "colour")]
    T += [exact("In HSV/HSL colour models, what does the H stand for?", ["hue"], w("HSL and HSV"), "colour")]
    T += [choice("'Value' in colour theory means:", ["how pure the colour is", "how light or dark the colour is", "its position on the wheel", "its price"], 1, w("Value (color)", "Lightness"), "colour")]
    T += [choice("Saturation (chroma) describes:", ["lightness", "the intensity or purity of a hue", "the temperature of a light source", "the texture of paint"], 1, w("Colorfulness"), "colour")]
    T += [exact("What colour temperature in kelvin is roughly 'daylight' white, commonly quoted as 6500 K and used as the sRGB white point? Give the number.", ["6500", "6500 K", "D65"], w("Color temperature", "SRGB"), "light")]
    T += [choice("Warm colours such as red and orange tend to:", ["recede into the background", "advance towards the viewer", "look smaller", "look colder"], 1, w("Warm and cool colors"), "colour")]
    T += [exact("What is the most common form of colour blindness, affecting red-green discrimination in roughly 8% of men?", ["red-green colour blindness", "red-green", "deuteranomaly", "deuteranopia", "red green color blindness"], w("Color blindness"), "accessibility")]
    T += [exact("Which three-light setup uses a key light, a fill light and a back (rim) light?", ["three-point lighting", "three point lighting"], w("Three-point lighting"), "lighting")]
    T += [choice("In three-point lighting, the fill light's job is to:", ["create the main shadows", "soften the shadows cast by the key light", "separate the subject from the background", "light the background only"], 1, w("Fill light"), "lighting")]
    T += [choice("The back light (rim light) mainly:", ["lights the face", "creates a bright edge that separates the subject from the background", "colours the shadows", "replaces the key"], 1, w("Back light"), "lighting")]
    T += [exact("What lighting pattern, named after a Dutch painter, leaves a small triangle of light on the shadowed cheek?", ["Rembrandt lighting", "Rembrandt"], w("Rembrandt lighting"), "lighting")]
    T += [exact("What Italian term describes strong contrasts between light and dark in painting?", ["chiaroscuro"], w("Chiaroscuro"), "lighting")]
    T += [choice("A specular highlight is:", ["the diffuse colour of a surface", "the bright reflection of a light source on a shiny surface", "a shadow", "a texture seam"], 1, w("Specular highlight"), "lighting")]
    T += [exact("Which reflectance model says a perfectly matte surface looks equally bright from every viewing angle?", ["Lambertian", "Lambertian reflectance", "Lambert"], w("Lambertian reflectance"), "lighting")]
    T += [choice("The Fresnel effect means that a surface:", ["gets darker when wet", "reflects more at grazing angles than head-on", "casts no shadow", "is always metallic"], 1, w("Fresnel equations"), "lighting")]
    T += [exact("Subsurface scattering is important for rendering which kind of material realistically, such as skin, wax or milk?", ["translucent", "translucent materials", "skin", "semi-translucent"], w("Subsurface scattering"), "lighting")]
    T += [exact("What composition principle divides a frame into unequal parts in the ratio about 1.618 to 1?", ["golden ratio", "golden section", "phi"], w("Golden ratio"), "composition")]
    T += [choice("Negative space is:", ["the subject of the picture", "the empty area around and between subjects", "a dark colour", "an error in the drawing"], 1, w("Negative space"), "composition")]
    T += [exact("What are 'leading lines' in composition?", ["lines that guide the viewer's eye to the subject", "lines that lead the eye", "lines guiding the eye toward the focal point"], w("Leading line"), "composition")]
    T += [exact("Which school of psychology gave art its principles of grouping such as proximity, similarity and closure?", ["Gestalt", "Gestalt psychology"], w("Gestalt psychology"), "perception")]
    T += [choice("Figure-ground perception describes:", ["drawing a figure's feet on the ground", "separating a subject (figure) from its background (ground)", "shading the floor", "a type of brush"], 1, w("Figure–ground (perception)"), "perception")]
    T += [exact("In one-point perspective, parallel lines receding from the viewer meet at how many vanishing points?", ["1", "one"], w("Vanishing point", "Perspective (graphical)"), "perspective")]
    T += [exact("In the sRGB standard the transfer curve is approximately a power of what exponent, hence 'gamma 2.2'?", ["2.2", "2,2"], w("Gamma correction", "SRGB"), "colour")]
    T += [choice("High dynamic range (HDR) rendering followed by tone mapping is needed because:", ["monitors have more range than real scenes", "real scene brightness spans a far wider range than a display can show, so it is compressed", "colours are stored as text", "shadows are always black"], 1, w("High-dynamic-range imaging", "Tone mapping"), "rendering")]
    T += [exact("What is the name for the pleasing blur of out-of-focus highlights in photography?", ["bokeh"], w("Bokeh"), "photography")]
    T += [exact("In typography, what is the adjustment of space between two specific letters called?", ["kerning"], w("Kerning"), "typography")]
    T += [exact("In typography, what is the vertical space between lines of text called?", ["leading", "line spacing", "line height"], w("Leading"), "typography")]
    T += [choice("A serif typeface:", ["has small strokes at the ends of letters", "has no small strokes at the ends of letters", "is always bold", "is only for headings"], 0, w("Serif"), "typography")]
    T += [exact("What pixel-art technique alternates pixels of two colours to simulate a third colour or gradient?", ["dithering"], w("Dithering"), "pixel-art")]
    T += [choice("Vector graphics differ from raster graphics because they:", ["are made of pixels", "are described by shapes and curves, so they scale without blur", "cannot be coloured", "only exist in 3D"], 1, w("Vector graphics", "Raster graphics"), "graphics")]
    T += [exact("What rendering style uses flat bands of colour and dark outlines to look hand-drawn, as in 'The Legend of Zelda: The Wind Waker'?", ["cel shading", "cel-shading", "toon shading"], w("Cel shading"), "style")]
    T += [exact("Which German art school (1919-1933) promoted the idea that form follows function and shaped modern design?", ["Bauhaus"], w("Bauhaus"), "history")]
    T += [order("Order these from darkest to lightest value.", [("black", "black"), ("dark grey", "dark gr[ae]y"), ("mid grey", "mid|middle"), ("white", "white")], w("Value (color)"), "colour")]
    T += [match("Match each colour harmony to its definition.", [("complementary", "complementary", "two colours opposite each other on the wheel", "opposite"), ("triadic", "triadic", "three colours evenly spaced around the wheel", "three|evenly|120"), ("monochromatic", "monochromatic", "one hue in different values and saturations", "one hue|single hue|same hue")], w("Color harmony"), "colour")]
    T += [short("Explain how to make a focal point stand out in a game scene using at least two of: contrast, colour, light, detail.", [["contrast|brighter|lighter|light"], ["saturat|colour|color|warm|complement"], ["detail|rest|less|simpl|empty|negative space"]], "Light the focal point brighter than its surroundings for contrast, give it a saturated or complementary colour against a muted background, and keep detail concentrated there while the rest stays simple.", w("Focal point (art)", "Visual hierarchy"), "composition", min_required=2)]
    T += [short("Why do artists often paint shadows with a cooler colour rather than just a darker version of the local colour?", [["sky|ambient|blue|cool|bounce|reflected"], ["warm|sun|key|light source"]], "Shadows are lit by the cool blue sky and bounced ambient light rather than the warm sun, so they read cooler than the lit side; pure black or darker local colour looks dead.", w("Warm and cool colors", "Shadow"), "lighting")]
    return T


def audio_music():
    T = []
    T += [exact("How many semitones are in an octave?", ["12", "twelve"], w("Octave", "Semitone"), "pitch")]
    T += [exact("What is the standard tuning frequency of the A above middle C (A4) in hertz?", ["440", "440 Hz"], w("A440 (pitch standard)"), "pitch")]
    T += [exact("A perfect fifth spans how many semitones?", ["7", "seven"], w("Interval (music)"), "intervals")]
    T += [exact("A major third spans how many semitones?", ["4", "four"], w("Interval (music)", "Major chord"), "intervals")]
    T += [choice("A major triad is built from:", ["root, minor third, perfect fifth", "root, major third, perfect fifth", "root, fourth, fifth", "root, major second, major third"], 1, w("Major chord", "Triad (music)"), "chords")]
    T += [choice("A minor triad differs from a major triad by:", ["a lowered fifth", "a lowered third", "a raised root", "an added seventh"], 1, w("Minor chord"), "chords")]
    T += [exact("Which scale has the pattern whole, whole, half, whole, whole, whole, half?", ["major scale", "major", "Ionian"], w("Major scale"), "scales")]
    T += [exact("How many notes does a pentatonic scale have per octave?", ["5", "five"], w("Pentatonic scale"), "scales")]
    T += [exact("What diagram arranges the twelve keys so that neighbours are a perfect fifth apart?", ["circle of fifths"], w("Circle of fifths"), "keys")]
    T += [choice("In 4/4 time, the top number means:", ["a quarter note gets the beat", "four beats per bar", "four bars per phrase", "the tempo is 4"], 1, w("Time signature"), "rhythm")]
    T += [choice("In 3/4 time, the bottom number means:", ["three beats per bar", "the quarter note gets one beat", "three quarter notes per piece", "the key has three flats"], 1, w("Time signature"), "rhythm")]
    T += [exact("What is the Italian term for a gradual increase in loudness?", ["crescendo"], w("Dynamics (music)"), "dynamics")]
    T += [exact("What musical term means to play gradually slower?", ["ritardando", "rallentando", "rit.", "rall."], w("Tempo"), "tempo")]
    T += [choice("Syncopation is:", ["playing exactly on the beat", "stressing beats or parts of beats that are normally weak", "playing very loudly", "tuning the instrument"], 1, w("Syncopation"), "rhythm")]
    T += [choice("Timbre is:", ["how high or low a note is", "the tone colour that makes a violin sound different from a flute at the same pitch", "how loud a note is", "the length of a note"], 1, w("Timbre"), "sound")]
    T += [exact("The Nyquist-Shannon theorem says the sample rate must be at least how many times the highest frequency you want to capture?", ["2", "two", "twice"], w("Nyquist–Shannon sampling theorem"), "digital")]
    T += [exact("CD-quality audio uses a sample rate of how many hertz?", ["44100", "44,100", "44.1 kHz", "44100 Hz"], w("Sample rate", "Compact Disc Digital Audio"), "digital")]
    T += [exact("CD-quality audio uses how many bits per sample?", ["16", "sixteen"], w("Audio bit depth"), "digital")]
    T += [choice("Aliasing in digital audio happens when:", ["the volume is too high", "frequencies above half the sample rate fold back as false lower tones", "the file is compressed", "two tracks play together"], 1, w("Aliasing"), "digital")]
    T += [exact("Roughly how many decibels louder is a sound with ten times the power?", ["10", "10 dB", "ten"], w("Decibel"), "loudness")]
    T += [exact("A doubling of sound pressure corresponds to about how many decibels?", ["6", "6 dB", "six"], w("Decibel", "Sound pressure"), "loudness")]
    T += [exact("What is the approximate speed of sound in air at 20 °C, in metres per second?", ["343", "343 m/s", "340", "344"], w("Speed of sound"), "acoustics")]
    T += [exact("What effect makes a siren sound higher as it approaches and lower as it moves away?", ["Doppler effect", "Doppler"], w("Doppler effect"), "acoustics")]
    T += [choice("A low-pass filter:", ["lets low frequencies through and attenuates high ones", "lets high frequencies through", "boosts the midrange", "removes silence"], 0, w("Low-pass filter"), "processing")]
    T += [choice("Reverb (reverberation) simulates:", ["a single distinct echo", "the many reflections of a room that blur together into a tail", "pitch shifting", "distortion"], 1, w("Reverberation"), "processing")]
    T += [choice("A compressor in audio:", ["makes files smaller", "reduces the dynamic range by lowering loud parts above a threshold", "adds reverb", "raises the pitch"], 1, w("Dynamic range compression"), "processing")]
    T += [exact("What four-stage envelope shape (attack, decay, sustain, ...) describes how a synth note evolves? Name the fourth stage.", ["release"], w("Envelope (music)"), "synthesis")]
    T += [exact("What synthesis method shapes a bright waveform by filtering out harmonics?", ["subtractive synthesis", "subtractive"], w("Subtractive synthesis"), "synthesis")]
    T += [choice("Frequency modulation (FM) synthesis creates timbres by:", ["filtering noise", "modulating one oscillator's frequency with another at audio rate", "recording real instruments", "adding reverb"], 1, w("Frequency modulation synthesis"), "synthesis")]
    T += [exact("What is the name of the art of recreating everyday sound effects (footsteps, cloth) in sync with picture?", ["Foley"], w("Foley (filmmaking)"), "sound-design")]
    T += [choice("Adaptive music in games:", ["is always the same loop", "changes layers, intensity or transitions in response to gameplay state", "is only used in menus", "is recorded live each session"], 1, w("Adaptive music"), "game-audio")]
    T += [exact("What is a short recurring musical theme tied to a character or idea called (a term from Wagner's operas)?", ["leitmotif", "leitmotiv"], w("Leitmotif"), "composition")]
    T += [exact("What music format of early consoles uses the console's own sound chip and is now a genre?", ["chiptune", "chip music", "8-bit"], w("Chiptune"), "game-audio")]
    T += [choice("The inverse-square law for sound means that doubling the distance from a point source:", ["halves the intensity", "quarters the intensity", "doubles the intensity", "does not change the intensity"], 1, w("Inverse-square law", "Sound attenuation"), "acoustics")]
    T += [exact("What transform turns a time-domain audio signal into its frequency components?", ["Fourier transform", "FFT", "fast Fourier transform", "discrete Fourier transform"], w("Fourier transform"), "digital")]
    T += [choice("White noise has:", ["equal power per octave", "equal power per hertz across the spectrum", "only low frequencies", "a single frequency"], 1, w("White noise", "Pink noise"), "sound")]
    T += [order("Order these note durations from longest to shortest.", [("whole note", "whole"), ("half note", "half"), ("quarter note", "quarter"), ("eighth note", "eighth")], w("Rhythm", "Musical note"), "rhythm")]
    T += [match("Match each audio effect to what it does.", [("EQ", "\\bEQ\\b|equali", "boosts or cuts frequency bands", "frequenc|band|boost|cut"), ("delay", "delay", "repeats the signal after a set time", "repeat|echo|time"), ("limiter", "limiter", "stops peaks exceeding a ceiling", "peak|ceiling|exceed|clip")], w("Equalization (audio)", "Delay (audio effect)", "Limiter"), "processing")]
    T += [short("Explain why a game footstep sound should have several randomly chosen variations with slight pitch changes.", [["repetiti|same|monoton|machine ?gun|fatigue|robotic|identical"], ["variation|vary|random|pitch"]], "Playing the identical sample every step sounds robotic and fatiguing (the machine-gun effect); several variations with small random pitch and volume changes read as natural footsteps.", w("Sound design", "Sound effect"), "sound-design")]
    T += [short("Why do sounds placed far from the listener in a 3D game usually get a low-pass filter as well as lower volume?", [["high frequenc|air|absorb|attenuat|treble|muffl"], ["distance|far|realistic|cue"]], "Air absorbs high frequencies over distance, so distant sounds are duller as well as quieter; filtering the highs gives the brain a distance cue that volume alone does not.", w("Sound attenuation", "Sound localization"), "game-audio")]
    return T


def writing_narrative():
    T = []
    T += [exact("How many acts are in the classical dramatic structure used by most screenplays (setup, confrontation, resolution)?", ["3", "three"], w("Three-act structure"), "structure")]
    T += [exact("Which mythologist described the 'hero's journey' or monomyth in 'The Hero with a Thousand Faces'?", ["Joseph Campbell", "Campbell"], w("Hero's journey", "Joseph Campbell"), "structure")]
    T += [exact("Which German novelist's 19th-century pyramid divides a drama into exposition, rising action, climax, falling action and denouement?", ["Gustav Freytag", "Freytag"], w("Dramatic structure"), "structure")]
    T += [choice("'Chekhov's gun' is the principle that:", ["every story needs a weapon", "every element introduced must become necessary; a gun shown in act one must fire later", "the villain always has a gun", "stories should start with a bang"], 1, w("Chekhov's gun"), "craft")]
    T += [choice("Dramatic irony occurs when:", ["a character says the opposite of what they mean", "the audience knows something a character does not", "the ending is sad", "the narrator lies"], 1, w("Dramatic irony"), "craft")]
    T += [exact("What is the term for an untrustworthy narrator whose account the reader cannot take at face value?", ["unreliable narrator"], w("Unreliable narrator"), "pov")]
    T += [choice("Foreshadowing is:", ["a summary at the end", "a hint early in the story about what will happen later", "the shadow a character casts", "a flashback"], 1, w("Foreshadowing"), "craft")]
    T += [exact("Which point of view uses 'I' and tells the story from inside one character's head?", ["first person", "first-person"], w("Point of view (literature)", "Narration"), "pov")]
    T += [exact("The advice 'show, don't tell' asks writers to convey emotion through what instead of stating it?", ["action, dialogue and sensory detail", "actions and details", "action", "concrete details"], w("Show, don't tell"), "craft")]
    T += [exact("What is the underlying meaning beneath what characters literally say called?", ["subtext"], w("Subtext"), "dialogue")]
    T += [choice("A character arc is:", ["the shape of a character's eyebrows", "the inner change a character undergoes over the story", "the list of a character's lines", "a plot hole"], 1, w("Character arc"), "character")]
    T += [exact("What is the term for the moment of greatest tension where the main conflict comes to a head?", ["climax"], w("Climax (narrative)"), "structure")]
    T += [exact("What French word names the part after the climax where loose ends are tied up?", ["denouement", "dénouement"], w("Dénouement"), "structure")]
    T += [exact("What is a 'MacGuffin'?", ["an object everyone wants that drives the plot but matters little in itself", "a plot device that motivates the characters", "an object that drives the plot"], w("Plot (narrative)"), "craft")]
    T += [choice("In a dialogue tree, the player:", ["reads a linear script", "chooses among responses, each leading to different lines or outcomes", "types free text that is never parsed", "watches a cutscene"], 1, w("Dialogue tree"), "interactive")]
    T += [choice("A branching narrative differs from a linear one because:", ["it has no ending", "player choices lead to different paths and sometimes different endings", "it is told in verse", "it has only one character"], 1, w("Branching narrative"), "interactive")]
    T += [exact("Which 20th-century Japanese four-part story structure (introduction, development, twist, conclusion) avoids a central conflict?", ["kishotenketsu", "kishōtenketsu"], w("Kishōtenketsu"), "structure")]
    T += [choice("Worldbuilding is:", ["building levels in an engine", "constructing the imaginary setting's history, rules, cultures and geography", "writing the ending first", "casting actors"], 1, w("Worldbuilding"), "world")]
    T += [exact("What is 'flavor text' in a game?", ["short descriptive text that adds atmosphere but has no rules effect", "descriptive text with no mechanical effect", "text for atmosphere"], w("Flavor text"), "interactive")]
    T += [exact("In Aristotle's 'Poetics', what Greek term names the purging of pity and fear that tragedy produces?", ["catharsis"], w("Poetics (Aristotle)"), "theory")]
    T += [choice("'Stakes' in storytelling means:", ["wooden posts in the setting", "what the characters stand to lose or gain, which gives the conflict weight", "the budget of the film", "the font size"], 1, w("Stakes"), "craft")]
    T += [exact("What narrative technique interrupts the present to show earlier events?", ["flashback", "analepsis"], w("Narrative structure"), "craft")]
    T += [exact("Which grammatical voice puts the actor first ('The player opens the door') and is usually preferred in clear writing?", ["active voice", "active"], w("Active voice"), "style")]
    T += [exact("What is the comma before 'and' in a list of three or more items called?", ["Oxford comma", "serial comma"], w("Oxford comma"), "style")]
    T += [choice("The Flesch-Kincaid grade level measures:", ["how funny a text is", "how hard a text is to read, from sentence and word length", "the number of pages", "grammar errors"], 1, w("Flesch–Kincaid readability tests"), "style")]
    T += [exact("A haiku has how many syllables in total across its three lines?", ["17", "seventeen"], w("Haiku"), "forms")]
    T += [exact("A Shakespearean sonnet has how many lines?", ["14", "fourteen"], w("Sonnet"), "forms")]
    T += [choice("A metaphor differs from a simile because a metaphor:", ["uses 'like' or 'as'", "states one thing is another without 'like' or 'as'", "is always about animals", "rhymes"], 1, w("Metaphor", "Simile"), "figures")]
    T += [exact("What is the term for a stereotyped, instantly recognisable character type such as 'the wise mentor'?", ["archetype", "stock character"], w("Archetype", "Stock character"), "character")]
    T += [exact("Which of the three rhetorical appeals named by Aristotle relies on the speaker's credibility?", ["ethos"], w("Ethos", "Rhetoric"), "rhetoric")]
    T += [exact("Which rhetorical appeal works through the audience's emotions?", ["pathos"], w("Pathos"), "rhetoric")]
    T += [choice("A cutscene is:", ["a deleted scene", "a non-interactive sequence that advances the story between gameplay", "a level editor", "the scoring screen"], 1, w("Cutscene"), "interactive")]
    T += [exact("What do we call storytelling where the plot is not generated by the author but emerges from systems and player actions?", ["emergent narrative"], w("Emergent narrative"), "interactive")]
    T += [exact("What are 'beats' in screenwriting?", ["the smallest units of story action or change", "small units of action or emotional change", "moments of change"], w("Screenwriting"), "craft")]
    T += [order("Order the five parts of Freytag's pyramid.", [("exposition", "exposition"), ("rising action", "rising"), ("climax", "climax"), ("falling action", "falling"), ("denouement", "denouement|dénouement|resolution")], w("Dramatic structure"), "structure")]
    T += [match("Match each narrative point of view to its pronoun or feature.", [("first person", "first", "narrator says 'I'", "\\bI\\b|'I'"), ("second person", "second", "the reader is addressed as 'you'", "you"), ("third person limited", "third person limited|limited", "'he' or 'she', inside one character's thoughts", "one character|single character|inside"), ("third person omniscient", "omniscient", "a narrator who knows every character's thoughts", "all|every|knows")], w("Point of view (literature)", "Narration"), "pov")]
    T += [short("Give two ways a quest description in a game can show the stakes instead of just stating the objective.", [["dialogue|npc|character|voice|says|pleads"], ["consequence|what happens if|lose|timer|threat|detail|show"]], "Let an NPC plead for help in their own words with a concrete detail of what they will lose, and show the consequence in the world (a burning farm, a countdown) rather than writing 'Save the village'.", w("Stakes", "Quest (video games)"), "interactive")]
    T += [short("Why do writers recommend reading dialogue aloud when editing?", [["natural|rhythm|sound|flow|stilted|awkward|cadence"], ["aloud|ear|hear"]], "Reading aloud catches stilted rhythm and lines nobody would say; the ear hears awkward cadence that the eye skips.", w("Dialogue", "Editing"), "dialogue")]
    T += [choice("'Ludonarrative' refers to:", ["the game's loading narration", "the story told by gameplay itself, as opposed to cutscenes", "the credits", "a type of microphone"], 1, w("Ludonarrative dissonance", "Video game writing"), "interactive")]
    T += [exact("What do we call a narrative where the player's knowledge grows through notes, logs and objects scattered in the environment?", ["environmental storytelling"], w("Environmental storytelling"), "interactive")]
    return T


def ux_design():
    T = []
    T += [exact("Fitts's law predicts the time to reach a target from its distance and what other property?", ["size", "width"], w("Fitts's law"), "laws")]
    T += [exact("Hick's law says decision time grows with the number of what?", ["choices", "options", "alternatives"], w("Hick's law"), "laws")]
    T += [exact("Miller's law gives the approximate number of items a person can hold in working memory as seven plus or minus how many?", ["2", "two"], w("Miller's law"), "laws")]
    T += [choice("An affordance is:", ["a discount", "a property of an object that suggests how it can be used, like a handle that invites pulling", "a colour scheme", "a bug"], 1, w("Affordance"), "concepts")]
    T += [exact("Who wrote 'The Design of Everyday Things' and popularised the terms affordance and signifier in design?", ["Don Norman", "Donald Norman", "Norman"], w("Don Norman", "The Design of Everyday Things"), "literature")]
    T += [exact("Which usability consultant published the ten usability heuristics widely used for heuristic evaluation?", ["Jakob Nielsen", "Nielsen"], w("Jakob Nielsen (usability consultant)", "Heuristic evaluation"), "literature")]
    T += [choice("Progressive disclosure means:", ["showing everything at once", "showing only the most needed options first and revealing advanced ones on request", "hiding the save button", "a slow animation"], 1, w("Progressive disclosure"), "concepts")]
    T += [choice("A dark pattern is:", ["a dark colour theme", "an interface designed to trick users into doing things they did not intend", "a loading spinner", "a UX research method"], 1, w("Dark pattern"), "ethics")]
    T += [exact("WCAG recommends a minimum contrast ratio for normal body text of what value (AA level)?", ["4.5:1", "4.5 to 1", "4.5"], w("Web Content Accessibility Guidelines", "Contrast ratio"), "accessibility")]
    T += [exact("What does WCAG stand for?", ["Web Content Accessibility Guidelines"], w("Web Content Accessibility Guidelines"), "accessibility")]
    T += [choice("A screen reader is:", ["a bigger monitor", "software that reads interface text aloud for blind or low-vision users", "a QR code app", "a reading app for ebooks only"], 1, w("Screen reader"), "accessibility")]
    T += [exact("What is the recommended minimum touch target size in Apple's and Google's guidelines, roughly, in points or dp (give the common figure of 44-48)?", ["44", "48", "44 pt", "48 dp", "44x44", "48x48"], w("Touchscreen", "Material Design"), "mobile")]
    T += [exact("In the System Usability Scale (SUS), how many questions does the questionnaire have?", ["10", "ten"], w("System usability scale"), "research")]
    T += [exact("A SUS score above roughly what value is considered above average?", ["68"], w("System usability scale"), "research")]
    T += [choice("A/B testing compares:", ["two fonts on paper", "two versions of a design shown to different users to measure which performs better", "the designer against the developer", "alpha and beta releases"], 1, w("A/B testing"), "research")]
    T += [choice("Card sorting is used to:", ["play games with users", "learn how users group and label content, informing information architecture", "sort bug reports", "pick a colour palette"], 1, w("Card sorting", "Information architecture"), "research")]
    T += [exact("What do we call a fictional, research-based representation of a target user with a name, goals and frustrations?", ["persona", "user persona"], w("Persona (user experience)"), "research")]
    T += [exact("What low-fidelity sketch of a screen's layout, without colour or final content, is used early in design?", ["wireframe"], w("Wireframe (website)"), "process")]
    T += [choice("The 'empty state' of a screen is:", ["a crash", "what users see when there is no data yet, which should guide them to a first action", "the logout page", "a blank error"], 1, w("Empty state"), "patterns")]
    T += [choice("A modal window:", ["can be ignored while using the rest of the app", "blocks interaction with the rest of the app until it is dismissed", "is always full screen", "cannot have buttons"], 1, w("Modal window"), "patterns")]
    T += [exact("What is the Gestalt principle that elements close together are perceived as a group?", ["proximity"], w("Gestalt psychology"), "perception")]
    T += [exact("What is the design term for consistent spacing and alignment columns that structure a layout?", ["grid", "grid system", "layout grid"], w("Grid (graphic design)"), "layout")]
    T += [choice("Visual hierarchy is created mainly through:", ["random placement", "size, contrast, colour, spacing and position so the eye reads the most important thing first", "the file format", "the programming language"], 1, w("Visual hierarchy"), "layout")]
    T += [exact("What is the term for the gap between how a system works and how the user believes it works?", ["mental model mismatch", "mental model", "gulf of evaluation", "mismatch of mental models"], w("Mental model"), "concepts")]
    T += [choice("Onboarding in an app is:", ["the hiring process", "the first-run experience that teaches users what the product does and gets them to value quickly", "a boat feature", "the settings page"], 1, w("Onboarding"), "patterns")]
    T += [exact("Which 'KISS' principle advises designers to avoid unnecessary complexity? Expand the acronym's first two words.", ["keep it simple", "keep it simple, stupid", "keep it simple stupid"], w("KISS principle"), "principles")]
    T += [choice("Responsive web design means a layout that:", ["answers emails", "adapts to different screen sizes using flexible grids and media queries", "loads in under a second", "uses only images"], 1, w("Responsive web design"), "layout")]
    T += [exact("What is a 'microinteraction'?", ["a small, single-purpose interaction with feedback, like a toggle animating", "a tiny moment of feedback", "a small interaction"], w("Microinteraction"), "patterns")]
    T += [exact("In game UI, what is the name of the overlay showing health, ammo and map while playing?", ["HUD", "heads-up display"], w("Heads-up display (video games)"), "games")]
    T += [choice("Skeuomorphism is:", ["a flat style", "making digital elements imitate real-world materials and objects, like a leather-bound notes app", "an accessibility tool", "a typeface"], 1, w("Skeuomorph"), "style")]
    T += [exact("What term describes an interface's quality of letting users discover what actions are possible?", ["discoverability"], w("Discoverability"), "concepts")]
    T += [exact("What research method observes users in their own environment while they do real tasks?", ["contextual inquiry", "field study", "ethnography", "ethnographic research"], w("Contextual inquiry", "Ethnography"), "research")]
    T += [choice("Cognitive load in UX refers to:", ["the server CPU", "the mental effort a user must spend to use the interface", "the number of images", "the page weight in kilobytes"], 1, w("Cognitive load"), "concepts")]
    T += [exact("What five-point agreement scale (strongly disagree to strongly agree) is common in UX surveys?", ["Likert scale", "Likert"], w("Likert scale"), "research")]
    T += [order("Order these steps of the design-thinking process (Stanford d.school version).", [("empathize", "empath"), ("define", "define"), ("ideate", "ideate"), ("prototype", "prototype"), ("test", "test")], w("Design thinking"), "process")]
    T += [match("Match each Nielsen heuristic to an example.", [("visibility of system status", "status", "a progress bar during an upload", "progress|upload|loading"), ("error prevention", "error prevention|prevent", "a confirmation before deleting", "confirm|delete"), ("recognition rather than recall", "recognition|recall", "showing recent files instead of asking for a path", "recent|show|instead")], w("Heuristic evaluation"), "principles")]
    T += [short("A player repeatedly misses the 'Ready' button in your lobby menu on phones. Name two likely causes and a fix for each.", [["small|size|target|44|48|thumb|reach|bottom|edge"], ["contrast|colour|color|affordance|look like a button|label|visual"]], "The button is probably too small and too far from the thumb; enlarge it to at least 44-48 points and move it to the bottom reach zone. It may also not look pressable; give it a clear filled style, label and contrast.", w("Fitts's law", "Touchscreen"), "mobile")]
    T += [short("Why should error messages say what went wrong and how to fix it, rather than showing a code like 'Error 0x8004'?", [["recover|fix|next step|what to do|action"], ["plain|understand|human|language|meaning|readable"]], "Users cannot act on an opaque code; a plain-language message that names the problem and the recovery step lets them continue without support.", w("Error message", "Heuristic evaluation"), "patterns")]
    T += [exact("What is the usability term for how quickly a new user can accomplish basic tasks the first time?", ["learnability"], w("Learnability", "Usability"), "concepts")]
    T += [exact("Which colour-vision issue means UI must never rely on colour alone (e.g. red vs green status) to convey information?", ["colour blindness", "color blindness", "colour vision deficiency", "red-green colour blindness"], w("Color blindness", "Web accessibility"), "accessibility")]
    return T


def production_management():
    T = []
    T += [exact("What chart shows tasks as horizontal bars against a calendar, named after the engineer who popularised it?", ["Gantt chart", "Gantt"], w("Gantt chart"), "planning")]
    T += [exact("In the critical path method, the critical path is the sequence of tasks with how much total float (slack)?", ["0", "zero", "none"], w("Critical path method"), "planning")]
    T += [choice("A work breakdown structure (WBS) is:", ["a list of broken builds", "a hierarchical decomposition of the project's deliverables into smaller pieces of work", "the team's holiday calendar", "a bug tracker"], 1, w("Work breakdown structure"), "planning")]
    T += [exact("In Scrum, what is the name of the fixed-length iteration, typically one to four weeks?", ["sprint"], w("Sprint (software development)", "Scrum (software development)"), "agile")]
    T += [exact("In Scrum, what is the ordered list of everything that might be needed in the product called?", ["product backlog", "backlog"], w("Product backlog"), "agile")]
    T += [choice("Brooks's law states that adding people to a late software project:", ["finishes it sooner", "makes it later", "has no effect", "halves the bugs"], 1, w("Brooks's law", "The Mythical Man-Month"), "laws")]
    T += [exact("Parkinson's law says work expands to fill what?", ["the time available", "the time available for its completion", "available time"], w("Parkinson's law"), "laws")]
    T += [choice("The planning fallacy is the tendency to:", ["plan too much", "underestimate the time and cost a task will take, even with past experience", "skip planning", "plan in secret"], 1, w("Planning fallacy"), "estimation")]
    T += [exact("What estimation game has team members reveal cards simultaneously to agree on a story's size?", ["planning poker", "scrum poker"], w("Planning poker"), "estimation")]
    T += [choice("A burndown chart shows:", ["budget spent on coffee", "remaining work against time, ideally falling to zero at the end of the sprint", "team mood", "server uptime"], 1, w("Burndown chart"), "agile")]
    T += [exact("In Agile, 'velocity' measures how many of what a team completes per sprint?", ["story points", "points", "story points or stories"], w("Velocity (software development)", "Story point"), "agile")]
    T += [exact("What Japanese word names the visual board method with columns such as To Do, Doing and Done, limiting work in progress?", ["kanban"], w("Kanban (development)", "Kanban board"), "agile")]
    T += [choice("A 'WIP limit' on a Kanban board exists to:", ["limit the number of team members", "cap how many items are in progress at once so work flows and finishes", "limit meeting length", "cap the budget"], 1, w("Kanban (development)"), "agile")]
    T += [exact("What is the term for the stress period of long overtime before a game ships?", ["crunch", "crunch time"], w("Crunch (video games)"), "people")]
    T += [exact("In the Eisenhower matrix, tasks are sorted by urgency and what other dimension?", ["importance"], w("Eisenhower method"), "time")]
    T += [exact("The Pomodoro Technique uses focused work intervals of how many minutes?", ["25"], w("Pomodoro Technique"), "time")]
    T += [choice("The sunk cost fallacy is:", ["investing more because of what has already been spent, rather than future value", "cutting a feature early", "refusing to spend any money", "a type of budget"], 0, w("Sunk cost"), "decisions")]
    T += [exact("What does 'MVP' stand for in product development?", ["minimum viable product"], w("Minimum viable product"), "product")]
    T += [choice("A retrospective (retro) is a meeting where the team:", ["demos to customers", "reflects on how the last iteration went and agrees improvements", "plans the budget", "interviews candidates"], 1, w("Retrospective"), "agile")]
    T += [exact("What root-cause technique asks the same one-word question about five times in a row?", ["five whys", "5 whys"], w("Five whys"), "quality")]
    T += [exact("What is the fishbone diagram for cause analysis also called, after its inventor?", ["Ishikawa diagram", "Ishikawa"], w("Ishikawa diagram"), "quality")]
    T += [choice("A milestone in a project plan is:", ["a task that takes a long time", "a zero-duration marker of a significant point, like 'alpha complete'", "a type of risk", "a meeting room"], 1, w("Milestone (project management)"), "planning")]
    T += [exact("In the software release cycle, which stage comes after alpha and is feature-complete but still being tested?", ["beta"], w("Software release life cycle"), "release")]
    T += [exact("What is the name of a short daily meeting where each person says what they did, will do and what blocks them?", ["stand-up", "daily stand-up", "daily scrum", "standup"], w("Stand-up meeting"), "agile")]
    T += [choice("Technical debt is:", ["money owed to the IT department", "the future cost of shortcuts in code that must be paid in rework", "a loan for servers", "a bug bounty"], 1, w("Technical debt"), "engineering")]
    T += [exact("What does the 'S' in SMART goals usually stand for?", ["specific"], w("SMART criteria"), "goals")]
    T += [exact("In OKRs, what does 'KR' stand for?", ["key results", "key result"], w("OKR"), "goals")]
    T += [choice("A SWOT analysis lists:", ["sprints, work, output, time", "strengths, weaknesses, opportunities, threats", "scope, workload, owners, timeline", "staff, wages, overheads, taxes"], 1, w("SWOT analysis"), "strategy")]
    T += [exact("What is the break-even point?", ["where total revenue equals total cost", "revenue equals costs", "no profit and no loss"], w("Break-even (economics)"), "finance")]
    T += [choice("A fixed cost is one that:", ["changes with every unit produced", "stays the same regardless of how much is produced, like rent", "is paid once in cash", "is always small"], 1, w("Fixed cost"), "finance")]
    T += [exact("What is ROI short for?", ["return on investment"], w("Return on investment"), "finance")]
    T += [exact("Which US rating board assigns E, T and M ratings to games?", ["ESRB", "Entertainment Software Rating Board"], w("Entertainment Software Rating Board"), "compliance")]
    T += [exact("What is the European game age-rating system called?", ["PEGI"], w("PEGI"), "compliance")]
    T += [choice("COPPA (US) requires parental consent before collecting personal data from children under what age?", ["10", "13", "16", "18"], 1, w("Children's Online Privacy Protection Act"), "compliance")]
    T += [exact("Which Creative Commons licence element requires you to credit the creator (two letters)?", ["BY", "attribution", "CC BY"], w("Creative Commons license"), "licensing")]
    T += [choice("The Creative Commons 'SA' (ShareAlike) element means:", ["you may not share", "adaptations must be released under the same licence", "you must pay the author", "commercial use is banned"], 1, w("Creative Commons license"), "licensing")]
    T += [choice("The Creative Commons 'NC' element means:", ["no changes allowed", "no commercial use", "no credit needed", "no copies"], 1, w("Creative Commons license"), "licensing")]
    T += [exact("Which short permissive software licence requires only that its copyright notice is kept, and is used by Lua and Godot?", ["MIT", "MIT License", "MIT licence"], w("MIT License"), "licensing")]
    T += [order("Order these video game production phases.", [("pre-production", "pre-?production"), ("production", "(?<!pre-)(?<!post-)production"), ("alpha", "alpha"), ("beta", "beta"), ("release", "release|gold|launch")], w("Video game development", "Software release life cycle"), "release")]
    T += [match("Match each Scrum role to its responsibility.", [("product owner", "product owner", "orders the backlog and decides what is most valuable", "backlog|value|priorit"), ("scrum master", "scrum master", "coaches the process and removes impediments", "process|impediment|block|coach"), ("development team", "development team|developers", "builds the increment", "build|increment|work")], w("Scrum (software development)"), "agile")]
    T += [short("Your three-person team has four weeks before a showcase and a feature list that would take eight. Describe how you decide what to cut.", [["priorit|most important|core|must|mvp|minimum|value"], ["cut|drop|defer|later|scope|postpone"], ["risk|dependenc|demo|showcase|player"]], "Rank the features by what the showcase must prove, keep the core loop and anything the demo depends on, and defer the rest; cut the risky, isolated features first and leave buffer for polish and bugs.", w("Scope management", "Minimum viable product"), "planning", min_required=2)]
    return T


def math_facts():
    T = []
    T += [exact("What is the value of pi to two decimal places?", ["3.14"], w("Pi"), "constants")]
    T += [exact("What is the name of the theorem relating the sides of a right triangle: a^2 + b^2 = c^2?", ["Pythagorean theorem", "Pythagoras"], w("Pythagorean theorem"), "geometry")]
    T += [exact("How many degrees are in a full circle?", ["360"], w("Degree (angle)"), "geometry")]
    T += [exact("How many radians are in a full circle? Give the expression.", ["2π", "2 pi", "2pi", "6.28"], w("Radian"), "geometry")]
    T += [exact("What is the sum of the interior angles of a triangle in degrees?", ["180"], w("Triangle"), "geometry")]
    T += [exact("What is the formula for the area of a circle with radius r?", ["πr^2", "pi r^2", "πr²", "pi*r^2", "pi r squared", "π r^2"], w("Area", "Circle"), "geometry")]
    T += [exact("What is the formula for the volume of a sphere with radius r?", ["4/3 π r^3", "(4/3)πr^3", "4/3 pi r^3", "4πr³/3", "4/3*pi*r^3"], w("Sphere", "Volume"), "geometry")]
    T += [choice("The quadratic formula solves ax^2 + bx + c = 0 as x =", ["(-b ± √(b²-4ac)) / 2a", "(b ± √(b²+4ac)) / 2a", "-b / 2a", "√(b²-4ac)"], 0, w("Quadratic formula"), "algebra")]
    T += [exact("What is the name of the expression b^2 - 4ac in the quadratic formula?", ["discriminant"], w("Quadratic equation"), "algebra")]
    T += [exact("What is the derivative of x^2 with respect to x?", ["2x"], w("Derivative"), "calculus")]
    T += [exact("What is the derivative of sin(x)?", ["cos(x)", "cos x", "cosine"], w("Derivative", "Trigonometric functions"), "calculus")]
    T += [exact("What is the integral of 1/x dx (ignoring the constant)?", ["ln|x|", "ln x", "ln(x)", "natural log of x", "ln|x| + C"], w("Integral", "Logarithm"), "calculus")]
    T += [choice("The chain rule is used to differentiate:", ["a sum of functions", "a composition of functions f(g(x))", "a constant", "an integral"], 1, w("Chain rule"), "calculus")]
    T += [exact("The fundamental theorem of calculus links differentiation with what other operation?", ["integration"], w("Fundamental theorem of calculus"), "calculus")]
    T += [exact("What is the mean of 2, 4, 6 and 8?", ["5"], w("Mean"), "statistics")]
    T += [exact("What is the median of 3, 9, 1, 7, 5?", ["5"], w("Median"), "statistics")]
    T += [exact("What is the mode of 2, 3, 3, 5, 7, 3, 5?", ["3"], w("Mode (statistics)"), "statistics")]
    T += [choice("The standard deviation is:", ["the most common value", "the square root of the variance, a measure of spread", "the middle value", "the largest minus the smallest"], 1, w("Standard deviation", "Variance"), "statistics")]
    T += [exact("In a normal distribution, roughly what percentage of values lie within one standard deviation of the mean?", ["68", "68%", "68.3", "about 68"], w("Normal distribution"), "statistics")]
    T += [exact("What theorem explains why the mean of many independent samples tends to a normal distribution?", ["central limit theorem"], w("Central limit theorem"), "statistics")]
    T += [exact("What is the probability of rolling a 6 on one fair six-sided die? Give a fraction.", ["1/6", "0.1667", "0.167", "16.7%"], w("Probability", "Dice"), "probability")]
    T += [exact("What rule computes P(A|B) from P(B|A), P(A) and P(B)?", ["Bayes' theorem", "Bayes theorem", "Bayes"], w("Bayes' theorem"), "probability")]
    T += [exact("What is 5 factorial (5!)?", ["120"], w("Factorial"), "combinatorics")]
    T += [exact("How many ways can you choose 2 items from 5 (order does not matter)?", ["10"], w("Combination", "Binomial coefficient"), "combinatorics")]
    T += [exact("How many ways can 4 distinct items be arranged in a row?", ["24"], w("Permutation"), "combinatorics")]
    T += [exact("What is log base 10 of 1000?", ["3"], w("Logarithm"), "algebra")]
    T += [exact("What is 2 to the power 10?", ["1024"], w("Exponentiation"), "algebra")]
    T += [exact("What is the greatest common divisor of 12 and 18?", ["6"], w("Greatest common divisor"), "number-theory")]
    T += [exact("What is the least common multiple of 4 and 6?", ["12"], w("Least common multiple"), "number-theory")]
    T += [exact("Which algorithm finds the greatest common divisor by repeated division with remainder?", ["Euclidean algorithm", "Euclid's algorithm", "Euclid"], w("Euclidean algorithm"), "number-theory")]
    T += [choice("Big O notation O(n log n) describes the time of which sorting algorithm in the average case?", ["bubble sort", "merge sort", "insertion sort", "counting every pair"], 1, w("Big O notation", "Merge sort"), "complexity")]
    T += [exact("What is the dot product of vectors (1, 2, 3) and (4, 5, 6)?", ["32"], w("Dot product"), "linear-algebra")]
    T += [exact("What is the determinant of the 2x2 matrix [[a, b], [c, d]]?", ["ad - bc", "ad-bc", "ad − bc"], w("Determinant"), "linear-algebra")]
    T += [exact("What is the name of the matrix with ones on the diagonal and zeros elsewhere?", ["identity matrix", "identity"], w("Matrix (mathematics)"), "linear-algebra")]
    T += [choice("The sign test is a non-parametric test that uses:", ["the exact values of differences", "only whether each paired difference is positive or negative", "the variance of both groups", "regression slopes"], 1, w("Sign test"), "statistics")]
    T += [exact("A p-value below what conventional threshold is usually called 'statistically significant'?", ["0.05", "5%", ".05"], w("P-value", "Statistical hypothesis testing"), "statistics")]
    T += [exact("What interpolation draws a straight line between two known points to estimate values between them?", ["linear interpolation", "lerp"], w("Linear interpolation"), "numerics")]
    T += [exact("In IEEE 754 single precision, how many bits does a float occupy?", ["32"], w("IEEE 754", "Floating-point arithmetic"), "numerics")]
    T += [order("Order these numbers from smallest to largest: 0.5, 1/3, 3/4, 0.1.", [("0.1", "0\\.1\\b"), ("1/3", "1/3|0\\.33"), ("0.5", "0\\.5\\b|1/2"), ("3/4", "3/4|0\\.75")], w("Fraction", "Decimal"), "arithmetic")]
    T += [match("Match each term to its meaning.", [("mean", "\\bmean\\b", "the sum divided by the count", "sum|divided|average"), ("median", "median", "the middle value when sorted", "middle|sorted"), ("mode", "\\bmode\\b", "the most frequent value", "frequent|common|often")], w("Mean", "Median", "Mode (statistics)"), "statistics")]
    return T


def physics_facts():
    T = []
    T += [exact("Newton's second law relates force, mass and acceleration as F = ?", ["ma", "m a", "m×a", "mass times acceleration", "m*a"], w("Newton's laws of motion"), "mechanics")]
    T += [exact("What is the SI unit of force?", ["newton", "N"], w("Newton (unit)"), "units")]
    T += [exact("What is the SI unit of energy?", ["joule", "J"], w("Joule"), "units")]
    T += [exact("What is the SI unit of power?", ["watt", "W"], w("Watt"), "units")]
    T += [exact("What is the SI unit of pressure?", ["pascal", "Pa"], w("Pascal (unit)"), "units")]
    T += [exact("What is the acceleration due to gravity near Earth's surface, to one decimal place in m/s^2?", ["9.8", "9.81"], w("Gravitational acceleration"), "mechanics")]
    T += [exact("What is the formula for kinetic energy?", ["1/2 m v^2", "½mv²", "0.5 m v^2", "(1/2)mv^2", "half m v squared", "1/2mv^2"], w("Kinetic energy"), "energy")]
    T += [exact("What is the formula for gravitational potential energy near Earth's surface?", ["mgh", "m g h", "m*g*h"], w("Potential energy"), "energy")]
    T += [choice("Momentum is:", ["mass times velocity", "mass times acceleration", "force times distance", "velocity squared"], 0, w("Momentum"), "mechanics")]
    T += [choice("In an elastic collision:", ["only momentum is conserved", "both momentum and kinetic energy are conserved", "only kinetic energy is conserved", "neither is conserved"], 1, w("Elastic collision"), "collisions")]
    T += [exact("What is the coefficient of restitution of a perfectly elastic collision?", ["1", "one", "1.0"], w("Coefficient of restitution"), "collisions")]
    T += [exact("Newton's third law: for every action there is an equal and opposite ...?", ["reaction"], w("Newton's laws of motion"), "mechanics")]
    T += [choice("Newton's first law says an object with no net force on it:", ["slows to a stop", "keeps its velocity (stays at rest or moves uniformly)", "accelerates", "falls"], 1, w("Newton's laws of motion"), "mechanics")]
    T += [exact("Hooke's law states the force of a spring is proportional to its what?", ["extension", "displacement", "stretch", "deformation", "extension from rest length"], w("Hooke's law"), "oscillation")]
    T += [exact("Terminal velocity is reached when the drag force equals what other force?", ["weight", "gravity", "gravitational force", "the force of gravity"], w("Terminal velocity"), "mechanics")]
    T += [exact("At what launch angle (in degrees, no air resistance, level ground) does a projectile travel farthest?", ["45"], w("Projectile motion"), "mechanics")]
    T += [choice("Centripetal force on an object in circular motion points:", ["outward from the centre", "toward the centre of the circle", "along the velocity", "opposite to gravity"], 1, w("Centripetal force"), "mechanics")]
    T += [exact("Torque equals force times what?", ["lever arm", "distance", "perpendicular distance", "moment arm", "radius"], w("Torque"), "rotation")]
    T += [exact("What principle says a floating body displaces its own weight of fluid?", ["Archimedes' principle", "Archimedes"], w("Archimedes' principle", "Buoyancy"), "fluids")]
    T += [choice("Bernoulli's principle states that in a flowing fluid, where speed is higher:", ["pressure is higher", "pressure is lower", "density is lower", "temperature is higher"], 1, w("Bernoulli's principle"), "fluids")]
    T += [exact("What is the density of water in kg/m^3, approximately?", ["1000", "1,000"], w("Density"), "fluids")]
    T += [exact("What is absolute zero in degrees Celsius?", ["-273.15", "-273", "−273.15"], w("Kelvin", "Temperature"), "thermo")]
    T += [exact("The second law of thermodynamics says the total entropy of an isolated system never does what?", ["decreases", "decrease", "goes down"], w("Laws of thermodynamics", "Entropy"), "thermo")]
    T += [choice("Heat transfer by convection happens through:", ["electromagnetic waves", "the bulk movement of a fluid", "vibration through a solid", "sound"], 1, w("Convection", "Heat transfer"), "thermo")]
    T += [exact("What is the speed of light in vacuum, to three significant figures, in m/s?", ["3.00e8", "3e8", "300000000", "3 x 10^8", "3×10^8", "299792458", "2.998e8", "300,000,000"], w("Speed of light"), "optics")]
    T += [exact("Which law relates angles of incidence and refraction: n1 sin θ1 = n2 sin θ2?", ["Snell's law", "Snell"], w("Snell's law"), "optics")]
    T += [exact("Ohm's law relates voltage, current and resistance as V = ?", ["IR", "I R", "I×R", "current times resistance", "I*R"], w("Ohm's law"), "electricity")]
    T += [exact("Electrical power equals voltage times what?", ["current"], w("Electric power"), "electricity")]
    T += [choice("In a series circuit, the total resistance of two resistors is:", ["their sum", "their product", "the reciprocal of the sum of reciprocals", "the smaller one"], 0, w("Series and parallel circuits"), "electricity")]
    T += [choice("In a parallel circuit, adding another resistor:", ["raises the total resistance", "lowers the total resistance", "does not change it", "doubles it"], 1, w("Series and parallel circuits"), "electricity")]
    T += [exact("Which law says a changing magnetic flux through a loop induces an electromotive force?", ["Faraday's law", "Faraday's law of induction", "Faraday"], w("Faraday's law of induction"), "magnetism")]
    T += [exact("What is the SI unit of frequency?", ["hertz", "Hz"], w("Frequency"), "waves")]
    T += [exact("Wave speed equals frequency times what?", ["wavelength"], w("Wave", "Wavelength"), "waves")]
    T += [choice("The Doppler effect changes the observed:", ["amplitude", "frequency", "speed of light", "mass"], 1, w("Doppler effect"), "waves")]
    T += [exact("What is the name of the time it takes half of a radioactive sample to decay?", ["half-life", "half life"], w("Half-life"), "nuclear")]
    T += [exact("Einstein's mass-energy equivalence is written E = ?", ["mc^2", "mc²", "m c^2", "mc2"], w("Mass–energy equivalence"), "relativity")]
    T += [choice("Verlet integration is popular in game physics because it:", ["needs no time step", "is stable and handles constraints well by storing previous positions instead of velocities", "is exact for all forces", "uses no memory"], 1, w("Verlet integration"), "simulation")]
    T += [choice("The simple (explicit) Euler method for a falling object:", ["is exact", "accumulates error and can gain energy with large time steps", "needs no derivative", "cannot be used for velocity"], 1, w("Euler method", "Numerical integration"), "simulation")]
    T += [order("Order these from lowest to highest frequency in the electromagnetic spectrum.", [("radio", "radio"), ("infrared", "infrared"), ("visible light", "visible"), ("X-rays", "x-?ray")], w("Electromagnetic spectrum"), "waves")]
    T += [match("Match each quantity to its SI unit.", [("force", "force", "newton", "newton"), ("energy", "energy", "joule", "joule"), ("power", "power", "watt", "watt"), ("pressure", "pressure", "pascal", "pascal")], w("International System of Units"), "units")]
    return T


def computer_science():
    T = []
    T += [exact("What is the worst-case time complexity of binary search on a sorted array of n items?", ["O(log n)", "log n", "logarithmic"], w("Binary search algorithm"), "algorithms")]
    T += [exact("What is the average time complexity of quicksort?", ["O(n log n)", "n log n"], w("Quicksort"), "algorithms")]
    T += [exact("What is the worst-case time complexity of bubble sort?", ["O(n^2)", "O(n²)", "n^2", "quadratic", "n squared"], w("Bubble sort"), "algorithms")]
    T += [choice("A stack is a data structure with which access order?", ["first in, first out", "last in, first out", "random", "sorted"], 1, w("Stack (abstract data type)"), "data-structures")]
    T += [choice("A queue is:", ["last in, first out", "first in, first out", "sorted by key", "a tree"], 1, w("Queue (abstract data type)"), "data-structures")]
    T += [exact("What data structure gives average O(1) lookup by key using a hash function?", ["hash table", "hash map", "dictionary", "hashmap"], w("Hash table"), "data-structures")]
    T += [exact("Which graph search explores all neighbours at the current depth before going deeper, and finds shortest paths in unweighted graphs?", ["breadth-first search", "BFS"], w("Breadth-first search"), "graphs")]
    T += [exact("Which graph search goes as deep as possible along each branch before backtracking?", ["depth-first search", "DFS"], w("Depth-first search"), "graphs")]
    T += [choice("Dynamic programming solves problems by:", ["random guessing", "storing solutions to overlapping subproblems so each is computed once", "always taking the locally best choice", "parallel threads"], 1, w("Dynamic programming"), "algorithms")]
    T += [exact("What is the technique of caching a function's results for repeated inputs called?", ["memoization", "memoisation"], w("Memoization"), "algorithms")]
    T += [exact("What is the name of the problem Alan Turing proved undecidable: whether an arbitrary program will finish running?", ["halting problem"], w("Halting problem"), "theory")]
    T += [choice("P versus NP asks whether:", ["every problem can be parallelised", "every problem whose solution can be verified quickly can also be solved quickly", "computers can halt", "programs can be compiled"], 1, w("P versus NP problem"), "theory")]
    T += [exact("What model of computation with states and transitions is used for parsers, game AI and regular expressions?", ["finite-state machine", "finite state machine", "state machine", "FSM", "finite automaton"], w("Finite-state machine"), "theory")]
    T += [exact("What memory-management technique automatically frees objects no longer reachable, used by Lua, Java and C#?", ["garbage collection"], w("Garbage collection (computer science)"), "memory")]
    T += [exact("What memory-management technique frees an object when its count of references drops to zero?", ["reference counting"], w("Reference counting"), "memory")]
    T += [choice("A race condition occurs when:", ["a program runs too fast", "the result depends on the unpredictable timing of concurrent operations", "two cars collide in a game", "the CPU overheats"], 1, w("Race condition"), "concurrency")]
    T += [exact("What is the situation where two threads each wait for a lock the other holds, so neither proceeds?", ["deadlock"], w("Deadlock"), "concurrency")]
    T += [exact("What primitive guarantees that only one thread at a time runs a critical section?", ["mutex", "mutual exclusion", "lock"], w("Mutual exclusion"), "concurrency")]
    T += [choice("A coroutine differs from a thread because it:", ["runs on another CPU core", "yields control cooperatively at explicit points instead of being preempted", "cannot hold state", "always runs forever"], 1, w("Coroutine"), "concurrency")]
    T += [exact("What do we call a function that captures variables from the scope where it was created?", ["closure"], w("Closure (computer programming)"), "languages")]
    T += [choice("A pure function:", ["always returns the same output for the same input and has no side effects", "modifies global state", "reads the clock", "writes to a file"], 0, w("Pure function"), "languages")]
    T += [exact("Which design pattern lets one object notify many subscribers when its state changes, the basis of events and signals?", ["observer", "observer pattern", "publish-subscribe"], w("Observer pattern"), "patterns")]
    T += [exact("Which design pattern ensures a class has only one instance with a global access point?", ["singleton"], w("Singleton pattern"), "patterns")]
    T += [exact("What architecture pattern used by many game engines stores data in components attached to entities and logic in systems?", ["entity component system", "ECS", "entity-component-system"], w("Entity component system"), "architecture")]
    T += [exact("What does the 'S' in SOLID stand for?", ["single responsibility", "single responsibility principle", "single-responsibility"], w("SOLID"), "principles")]
    T += [exact("What does the acronym DRY stand for?", ["don't repeat yourself", "do not repeat yourself"], w("Don't repeat yourself"), "principles")]
    T += [exact("In the model-view-controller pattern, which part holds the data and rules?", ["model"], w("Model–view–controller"), "patterns")]
    T += [choice("The ACID properties of a database transaction are:", ["atomicity, consistency, isolation, durability", "accuracy, cost, integrity, delivery", "async, cache, index, data", "add, create, insert, delete"], 0, w("ACID"), "databases")]
    T += [exact("What language is used to query relational databases?", ["SQL"], w("SQL"), "databases")]
    T += [exact("What database structure speeds up lookups on a column at the cost of extra writes and storage?", ["index"], w("Database index"), "databases")]
    T += [choice("The CAP theorem says a distributed store can guarantee at most two of:", ["cost, availability, performance", "consistency, availability, partition tolerance", "cache, API, protocol", "compression, accuracy, parallelism"], 1, w("CAP theorem"), "distributed")]
    T += [exact("How many bits are in a byte?", ["8", "eight"], w("Byte"), "data")]
    T += [exact("What is the decimal value of the hexadecimal number FF?", ["255"], w("Hexadecimal"), "data")]
    T += [exact("What is the binary representation of decimal 10?", ["1010"], w("Binary number"), "data")]
    T += [exact("What representation lets computers store negative integers so that addition works unchanged?", ["two's complement"], w("Two's complement"), "data")]
    T += [exact("Which character encoding is backward compatible with ASCII and uses one to four bytes per code point?", ["UTF-8"], w("UTF-8"), "data")]
    T += [exact("What is the term for the byte order where the most significant byte comes first?", ["big-endian", "big endian"], w("Endianness"), "data")]
    T += [choice("Why can 0.1 + 0.2 differ from 0.3 in floating-point arithmetic?", ["the CPU is faulty", "0.1 and 0.2 have no exact binary representation, so rounding error appears", "addition is not defined for decimals", "the numbers overflow"], 1, w("Floating-point arithmetic", "Round-off error"), "numerics")]
    T += [exact("What attack injects malicious database commands through unsanitised user input?", ["SQL injection"], w("SQL injection"), "security")]
    T += [exact("What web attack injects scripts into pages viewed by other users?", ["cross-site scripting", "XSS"], w("Cross-site scripting"), "security")]
    T += [exact("What should be added to each password before hashing so identical passwords get different hashes?", ["salt", "a salt"], w("Salt (cryptography)"), "security")]
    T += [choice("The principle of least privilege says:", ["give every user admin rights", "give each component only the permissions it needs to do its job", "privileges should be hidden", "the server has fewest rights"], 1, w("Principle of least privilege"), "security")]
    T += [exact("In public-key cryptography, which key is used to decrypt a message encrypted with your public key?", ["private key", "your private key", "the private key"], w("Public-key cryptography"), "security")]
    T += [exact("What is the name of the protocol that encrypts HTTP traffic, giving HTTPS its S?", ["TLS", "Transport Layer Security", "SSL/TLS"], w("Transport Layer Security", "HTTPS"), "security")]
    T += [exact("Which neural network architecture introduced in 2017 ('Attention Is All You Need') underlies large language models?", ["transformer"], w("Transformer (deep learning architecture)"), "ml")]
    T += [choice("Overfitting means a model:", ["is too small to learn", "fits the training data too closely and generalises poorly to new data", "trains too slowly", "has no parameters"], 1, w("Overfitting"), "ml")]
    T += [exact("Which optimisation method updates parameters in the direction that decreases the loss, step by step?", ["gradient descent"], w("Gradient descent"), "ml")]
    T += [exact("Which lightweight scripting language from Brazil (1993) uses tables as its only data-structuring mechanism and is the ancestor of Luau?", ["Lua"], w("Lua (programming language)"), "languages")]
    T += [order("Order these by typical speed, fastest first.", [("CPU register", "register"), ("L1 cache", "l1|cache"), ("RAM", "ram|main memory"), ("SSD", "ssd|disk")], w("Cache (computing)", "Random-access memory"), "hardware")]
    T += [match("Match each data structure to a typical use.", [("priority queue", "priority queue|heap", "always taking the smallest or most urgent item next", "smallest|urgent|next|min"), ("trie", "trie", "prefix lookup of words for autocomplete", "prefix|autocomplete|word"), ("linked list", "linked list", "cheap insertion and removal in the middle", "insert|remov|middle")], w("Priority queue", "Trie", "Linked list"), "data-structures")]
    T += [short("Explain why a hash table lookup can degrade from O(1) to O(n) and how to prevent it.", [["collision|same bucket|same hash|bucket"], ["resize|load factor|rehash|good hash|distribut|balanced tree|treeif"]], "If many keys collide into the same bucket the chain grows and lookup walks it linearly; keep the load factor low by resizing, use a well-distributed hash function, or switch long chains to balanced trees.", w("Hash table", "Hash function"), "data-structures")]
    return T


def networking():
    T = []
    T += [exact("How many layers does the OSI reference model have?", ["7", "seven"], w("OSI model"), "models")]
    T += [exact("Which OSI layer is the transport layer (give its number)?", ["4", "four", "layer 4"], w("OSI model"), "models")]
    T += [choice("TCP differs from UDP because TCP:", ["is connectionless and unreliable", "provides reliable, ordered, connection-oriented delivery", "has smaller headers and no acknowledgements", "is used only for video"], 1, w("Transmission Control Protocol", "User Datagram Protocol"), "transport")]
    T += [choice("Fast-paced game state updates usually use UDP because:", ["it is encrypted", "a late retransmitted packet is useless, so no retransmission and lower latency is preferred", "it guarantees ordering", "it is newer"], 1, w("User Datagram Protocol", "Netcode"), "games")]
    T += [exact("What three-step exchange opens a TCP connection?", ["three-way handshake", "SYN, SYN-ACK, ACK", "3-way handshake"], w("Three-way handshake"), "transport")]
    T += [exact("How many bits are in an IPv4 address?", ["32"], w("IPv4"), "addressing")]
    T += [exact("How many bits are in an IPv6 address?", ["128"], w("IPv6"), "addressing")]
    T += [exact("What system translates human-readable names like example.com into IP addresses?", ["DNS", "Domain Name System"], w("Domain Name System"), "naming")]
    T += [exact("What protocol automatically assigns IP addresses to devices joining a network?", ["DHCP", "Dynamic Host Configuration Protocol"], w("Dynamic Host Configuration Protocol"), "addressing")]
    T += [exact("What does NAT stand for?", ["network address translation"], w("Network address translation"), "addressing")]
    T += [choice("The default port of HTTPS is:", ["80", "443", "22", "8080"], 1, w("HTTPS", "Port (computer networking)"), "ports")]
    T += [choice("The default port of HTTP is:", ["80", "443", "25", "53"], 0, w("HTTP", "Port (computer networking)"), "ports")]
    T += [exact("What is the default port of SSH?", ["22"], w("Secure Shell"), "ports")]
    T += [exact("What is round-trip time (RTT)?", ["the time for a packet to go to the destination and a reply to come back", "time to go and come back", "the time for a request and its response to travel there and back"], w("Round-trip delay"), "latency")]
    T += [choice("Jitter in networking is:", ["the average delay", "the variation in packet delay", "packet loss", "bandwidth"], 1, w("Jitter"), "latency")]
    T += [choice("Bandwidth measures:", ["how long a packet takes", "how much data can be transferred per unit time", "the number of hops", "the cable length"], 1, w("Bandwidth (computing)"), "capacity")]
    T += [exact("What header field decremented at each router prevents packets from looping forever?", ["TTL", "time to live", "hop limit"], w("Time to live"), "ip")]
    T += [exact("What does MTU stand for?", ["maximum transmission unit"], w("Maximum transmission unit"), "ip")]
    T += [exact("What is the standard Ethernet MTU in bytes?", ["1500", "1,500"], w("Maximum transmission unit", "Ethernet"), "ip")]
    T += [exact("What protocol does the 'ping' utility use?", ["ICMP", "Internet Control Message Protocol"], w("Ping (networking utility)", "Internet Control Message Protocol"), "tools")]
    T += [exact("Which protocol maps an IP address to a MAC address on a local network?", ["ARP", "Address Resolution Protocol"], w("Address Resolution Protocol"), "link")]
    T += [choice("A MAC address is:", ["assigned by DHCP", "a hardware address of a network interface", "a web address", "a routing table entry"], 1, w("MAC address"), "link")]
    T += [exact("Which routing protocol connects autonomous systems across the Internet?", ["BGP", "Border Gateway Protocol"], w("Border Gateway Protocol"), "routing")]
    T += [exact("What protocol provides full-duplex, persistent two-way messaging over a single TCP connection, used by many web games?", ["WebSocket", "WebSockets"], w("WebSocket"), "web")]
    T += [exact("Which transport protocol, built on UDP, underlies HTTP/3?", ["QUIC"], w("QUIC", "HTTP/3"), "web")]
    T += [choice("Head-of-line blocking means:", ["the first player in a queue wins", "a lost or delayed packet holds up delivery of later packets behind it", "the router drops the head of the queue", "the first byte is encrypted"], 1, w("Head-of-line blocking"), "transport")]
    T += [choice("Nagle's algorithm:", ["encrypts packets", "delays small TCP sends to combine them, which can add latency to games", "doubles bandwidth", "compresses headers"], 1, w("Nagle's algorithm"), "transport")]
    T += [exact("What netcode technique lets a client show its own movement immediately instead of waiting for the server's confirmation?", ["client-side prediction", "client prediction", "prediction"], w("Client-side prediction"), "games")]
    T += [exact("What netcode technique has the server rewind the world to the time a shot was fired, so a laggy client's aim is judged fairly?", ["lag compensation", "server-side rewind", "server rewind"], w("Lag compensation"), "games")]
    T += [choice("Dead reckoning in multiplayer games means:", ["killing lagging players", "extrapolating an object's position from its last known velocity until an update arrives", "counting dead players", "resetting the clock"], 1, w("Dead reckoning"), "games")]
    T += [choice("A lockstep protocol:", ["sends only inputs and waits for every peer's input before advancing a simulation step", "sends full world state every frame", "locks the server", "uses no synchronisation"], 0, w("Lockstep protocol"), "games")]
    T += [exact("What type of attack floods a server with traffic from many machines to make it unavailable?", ["DDoS", "distributed denial of service", "distributed denial-of-service"], w("Denial-of-service attack"), "security")]
    T += [exact("What device or software filters traffic by rules such as allowed ports and addresses?", ["firewall"], w("Firewall (computing)"), "security")]
    T += [choice("A reverse proxy:", ["hides clients from servers", "sits in front of servers, forwarding client requests to them (load balancing, TLS termination)", "resolves names", "assigns IPs"], 1, w("Reverse proxy"), "infra")]
    T += [exact("What does CDN stand for?", ["content delivery network", "content distribution network"], w("Content delivery network"), "infra")]
    T += [exact("Which protocol keeps computer clocks synchronised over a network?", ["NTP", "Network Time Protocol"], w("Network Time Protocol"), "time")]
    T += [exact("What does a certificate authority (CA) do?", ["issues and signs digital certificates that vouch for a server's identity", "signs certificates", "vouches for identities by issuing certificates"], w("Certificate authority"), "security")]
    T += [exact("In CIDR notation, how many host addresses does a /24 IPv4 network have in total (including network and broadcast)?", ["256"], w("Classless Inter-Domain Routing"), "addressing")]
    T += [order("Order these layers of the Internet protocol suite from bottom to top.", [("link", "link"), ("internet (IP)", "internet|\\bip\\b"), ("transport (TCP/UDP)", "transport|tcp"), ("application (HTTP)", "application|http")], w("Internet protocol suite"), "models")]
    T += [match("Match each protocol to its job.", [("DNS", "dns", "name to address lookup", "name|address|lookup|resolv"), ("DHCP", "dhcp", "handing out IP configuration", "hand|assign|config|lease"), ("TLS", "tls", "encrypting a connection", "encrypt|secure"), ("ICMP", "icmp", "control and error messages such as ping", "control|error|ping|unreachable")], w("Domain Name System", "Dynamic Host Configuration Protocol", "Transport Layer Security", "Internet Control Message Protocol"), "protocols")]
    T += [short("Explain why interpolating remote players slightly in the past (e.g. 100 ms) makes their movement smooth, and what it costs.", [["buffer|between (two )?(updates|snapshots)|two (known )?(positions|states)|interpolat"], ["delay|behind|latency|cost|later|lag"]], "The client renders remote players between two received snapshots instead of guessing ahead, so movement is smooth even with jitter; the cost is that you see them about one update interval in the past.", w("Interpolation", "Netcode"), "games")]
    return T


# ---------------------------------------------------------------- numeric tasks (computed)

def numeric_tasks():
    rng = random.Random(20261018)
    T = []
    # physics: F = m a
    for m, a, obj in [(2, 3, "a crate"), (12.5, 0.8, "a cart"), (70, 1.5, "a sprinter"), (0.25, 40, "a tennis ball")]:
        T.append(numeric(f"{obj.capitalize()} of mass {m} kg accelerates at {a} m/s^2. Using Newton's second law, what net force acts on it in newtons?", round(m * a, 3), [OPENSTAX + "university-physics-volume-1"] + w("Newton's laws of motion"), "newton-2", unit="N"))
    # kinetic energy
    for m, v, obj in [(0.5, 12, "a thrown stone"), (1200, 25, "a car"), (80, 8, "a cyclist with bike")]:
        T.append(numeric(f"What is the kinetic energy of {obj} of mass {m} kg moving at {v} m/s? Give joules.", 0.5 * m * v * v, [OPENSTAX + "university-physics-volume-1"] + w("Kinetic energy"), "kinetic-energy", unit="J"))
    # potential energy
    for m, h, obj in [(3, 10, "a flowerpot"), (60, 2.5, "a climber"), (0.2, 150, "a drone battery")]:
        T.append(numeric(f"Using g = 9.8 m/s^2, how much gravitational potential energy does {obj} of mass {m} kg gain when lifted {h} m? Answer in joules.", m * 9.8 * h, [OPENSTAX + "university-physics-volume-1"] + w("Potential energy"), "potential-energy", unit="J"))
    # free fall time
    for h in [20, 45, 80]:
        T.append(numeric(f"An object is dropped from rest from {h} m. Ignoring air resistance and taking g = 9.8 m/s^2, how many seconds does it take to hit the ground?", math.sqrt(2 * h / 9.8), [OPENSTAX + "university-physics-volume-1"] + w("Free fall"), "free-fall", rel=0.02, unit="s"))
    # projectile range
    for v, deg in [(20, 45), (30, 30), (15, 60)]:
        T.append(numeric(f"A projectile is launched at {v} m/s at {deg} degrees above level ground. With g = 9.8 m/s^2 and no air resistance, what is its horizontal range in metres?", v * v * math.sin(math.radians(2 * deg)) / 9.8, [OPENSTAX + "university-physics-volume-1"] + w("Projectile motion"), "projectile", rel=0.02, unit="m"))
    # Ohm's law
    for v, r in [(12, 4), (9, 450), (230, 23)]:
        T.append(numeric(f"A {r} ohm resistor is connected across {v} volts. What current flows, in amperes?", v / r, [OPENSTAX + "university-physics-volume-2"] + w("Ohm's law"), "ohm", rel=0.01, unit="A"))
    # electric power
    for v, i in [(5, 2), (120, 0.5), (3.7, 1.2)]:
        T.append(numeric(f"A device draws {i} A at {v} V. What electrical power does it use, in watts?", v * i, [OPENSTAX + "university-physics-volume-2"] + w("Electric power"), "power", unit="W"))
    # wave speed
    for f, lam in [(440, 0.78), (2000, 0.1715), (50, 6.86)]:
        T.append(numeric(f"A sound wave has frequency {f} Hz and wavelength {lam} m. What is its speed in m/s?", f * lam, [OPENSTAX + "university-physics-volume-1"] + w("Wave"), "wave-speed", rel=0.01, unit="m/s"))
    # music: frequency of note n semitones from A4
    for n, name in [(12, "A5, one octave above A4"), (-12, "A3, one octave below A4"), (3, "C5, three semitones above A4"), (-9, "C4 (middle C), nine semitones below A4"), (7, "E5, seven semitones above A4")]:
        T.append(numeric(f"With A4 = 440 Hz and twelve-tone equal temperament, what is the frequency of {name}? Answer in hertz.", 440 * 2 ** (n / 12), w("Equal temperament", "A440 (pitch standard)"), "equal-temperament", rel=0.005, unit="Hz"))
    # tempo: duration of a bar
    for bpm, beats in [(120, 4), (90, 3), (140, 4)]:
        T.append(numeric(f"A song is at {bpm} beats per minute in {beats}/4 time. How many seconds does one bar last?", 60 / bpm * beats, w("Tempo", "Time signature"), "tempo", rel=0.01, unit="s"))
    # audio: samples per second of audio buffer
    for sr, ms in [(44100, 10), (48000, 20), (22050, 50)]:
        T.append(numeric(f"At a sample rate of {sr} Hz, how many samples are in {ms} milliseconds of mono audio?", sr * ms / 1000, w("Sample rate"), "samples", rel=0.001))
    # decibels
    for ratio in [100, 1000, 2]:
        T.append(numeric(f"One sound has {ratio} times the power of another. By how many decibels is it louder (10 log10 of the power ratio)?", 10 * math.log10(ratio), w("Decibel"), "decibel", rel=0.01, unit="dB"))
    # animation frames
    for fps, s in [(24, 2.5), (30, 4), (60, 0.75)]:
        T.append(numeric(f"An animation runs at {fps} frames per second. How many frames are in a {s}-second shot?", fps * s, w("Frame rate"), "frames", rel=0.001))
    # frame budget ms
    for fps in [30, 60, 144]:
        T.append(numeric(f"To hold a steady {fps} frames per second, how many milliseconds may one frame take at most?", 1000 / fps, w("Frame rate"), "frame-budget", rel=0.01, unit="ms"))
    # 3D: triangles in a quad grid
    for a, b in [(10, 10), (32, 16), (4, 100)]:
        T.append(numeric(f"A flat terrain mesh is a grid of {a} by {b} quads. If each quad is split into two triangles, how many triangles does it have?", a * b * 2, w("Triangle mesh", "Polygon mesh"), "mesh-triangles", rel=0.001))
    for a, b in [(10, 10), (32, 16)]:
        T.append(numeric(f"A grid of {a} by {b} quads shares vertices between neighbours. How many vertices does it have?", (a + 1) * (b + 1), w("Polygon mesh", "Vertex (geometry)"), "mesh-vertices", rel=0.001))
    # colour: complementary hue
    for h, name in [(30, "orange"), (200, "a sky blue"), (300, "a magenta")]:
        T.append(numeric(f"A colour has hue {h} degrees on the HSV wheel ({name}). What is the hue of its complementary colour, in degrees (0-359)?", (h + 180) % 360, w("HSL and HSV", "Complementary colors"), "complement-hue", tol=0.5))
    # colour: hex to decimal channel
    for hexv in ["#FF8000", "#1E90FF", "#7F7F7F"]:
        r = int(hexv[1:3], 16)
        T.append(numeric(f"What is the decimal value of the red channel of the colour {hexv}?", r, w("RGB color model", "Hexadecimal"), "hex-channel", tol=0.5))
    # contrast ratio
    for l1, l2 in [(1.0, 0.0), (0.5, 0.1), (0.8, 0.2)]:
        T.append(numeric(f"Two colours have relative luminances {l1} and {l2}. Using the WCAG formula (L1 + 0.05) / (L2 + 0.05), what is their contrast ratio?", (l1 + 0.05) / (l2 + 0.05), w("Contrast ratio", "Web Content Accessibility Guidelines"), "contrast", rel=0.02))
    # math: percentages / ratios
    for price, pct in [(80, 25), (1500, 8), (12.5, 40)]:
        T.append(numeric(f"A {price} coin item is discounted by {pct}%. What is the new price?", price * (1 - pct / 100), [OPENSTAX + "prealgebra-2e"] + w("Percentage"), "percent", rel=0.005))
    for a, b in [(3, 4), (5, 12), (8, 15)]:
        T.append(numeric(f"A right triangle has legs {a} and {b}. What is the length of its hypotenuse?", math.hypot(a, b), [OPENSTAX + "prealgebra-2e"] + w("Pythagorean theorem"), "pythagoras", rel=0.001))
    for r in [3, 7.5]:
        T.append(numeric(f"What is the area of a circle of radius {r} units? Use pi = 3.14159.", math.pi * r * r, [OPENSTAX + "prealgebra-2e"] + w("Area"), "circle-area", rel=0.005))
    for n, k in [(6, 2), (10, 3), (8, 4)]:
        T.append(numeric(f"How many different teams of {k} can be formed from {n} players (order does not matter)?", math.comb(n, k), [OPENSTAX + "statistics"] + w("Combination"), "combinations", tol=0.5))
    # probability: at least one success
    for p, n in [(0.1, 5), (0.25, 3), (0.02, 20)]:
        T.append(numeric(f"A chest has a {p:.0%} chance of a rare drop each time it is opened. What is the probability of at least one rare drop in {n} openings? Give a decimal.", 1 - (1 - p) ** n, [OPENSTAX + "statistics"] + w("Probability", "Independence (probability theory)"), "at-least-one", rel=0.02))
    # expected value
    for cost, win, pwin in [(10, 50, 0.1), (5, 100, 0.03), (2, 6, 0.5)]:
        T.append(numeric(f"A game costs {cost} coins to play and pays {win} coins with probability {pwin}. What is the expected net gain per play in coins (may be negative)?", pwin * win - cost, [OPENSTAX + "statistics"] + w("Expected value"), "expected-value", tol=0.01))
    # elo expected score
    for d in [200, 400, -100]:
        T.append(numeric(f"In the Elo system, a player is rated {d:+d} points relative to an opponent. What is the player's expected score, 1 / (1 + 10^(-d/400))? Give a decimal.", 1 / (1 + 10 ** (-d / 400)), w("Elo rating system"), "elo", rel=0.02))
    # statistics: mean / sd
    for data in [[4, 8, 15, 16, 23, 42], [10, 10, 10, 20], [2.5, 3.5, 6.0]]:
        T.append(numeric(f"What is the arithmetic mean of these playtest session lengths in minutes: {', '.join(str(x) for x in data)}?", sum(data) / len(data), [OPENSTAX + "statistics"] + w("Mean"), "mean", rel=0.005))
    for data in [[2, 4, 4, 4, 5, 5, 7, 9], [1, 2, 3, 4, 5]]:
        mu = sum(data) / len(data)
        sd = math.sqrt(sum((x - mu) ** 2 for x in data) / len(data))
        T.append(numeric(f"What is the population standard deviation of {', '.join(str(x) for x in data)}?", sd, [OPENSTAX + "statistics"] + w("Standard deviation"), "stdev", rel=0.02))
    # networking: transfer time, hosts, bandwidth-delay
    for mb, mbps in [(100, 50), (4000, 200), (25, 8)]:
        T.append(numeric(f"How many seconds does it take to download a {mb} megabyte game update over a steady {mbps} megabit-per-second link (8 bits per byte)?", mb * 8 / mbps, [CNP3] + w("Bandwidth (computing)"), "transfer-time", rel=0.01, unit="s"))
    for prefix in [24, 26, 20]:
        T.append(numeric(f"How many usable host addresses does an IPv4 /{prefix} subnet have (total minus network and broadcast)?", 2 ** (32 - prefix) - 2, [CNP3] + w("Classless Inter-Domain Routing", "Subnetwork"), "subnet-hosts", tol=0.5))
    for mbps, ms in [(100, 20), (10, 150)]:
        T.append(numeric(f"A link has {mbps} Mbit/s bandwidth and {ms} ms round-trip time. What is its bandwidth-delay product in bits?", mbps * 1e6 * ms / 1000, [CNP3] + w("Bandwidth-delay product"), "bdp", rel=0.01))
    for hz, players in [(20, 10), (60, 4)]:
        T.append(numeric(f"A game server sends each of {players} players one 200-byte snapshot {hz} times per second. How many kilobits per second does it send in total (1 kilobit = 1000 bits)?", players * 200 * 8 * hz / 1000, w("Netcode", "Bandwidth (computing)"), "snapshot-bandwidth", rel=0.01, unit="kbit/s|kb/s|kbps|kilobit"))
    # production: schedule / budget
    for people, weeks, rate in [(3, 8, 1500), (5, 12, 2000)]:
        T.append(numeric(f"A team of {people} people works {weeks} weeks at a loaded cost of {rate} per person-week. What is the labour cost of the phase?", people * weeks * rate, [OPENSTAX + "introduction-business"] + w("Budget", "Estimation (project management)"), "labour-cost", rel=0.001))
    for points, velocity in [(120, 15), (90, 12)]:
        T.append(numeric(f"A backlog holds {points} story points and the team's velocity is {velocity} points per two-week sprint. How many sprints will it take (round up to a whole sprint)?", math.ceil(points / velocity), w("Velocity (software development)", "Story point"), "sprints", tol=0.5))
    for fixed, price, varc in [(20000, 10, 2), (5000, 4.99, 0.49)]:
        T.append(numeric(f"A game has fixed costs of {fixed} and sells at {price} per copy with a variable cost of {varc} per copy. How many copies must it sell to break even (round up)?", math.ceil(fixed / (price - varc)), [OPENSTAX + "introduction-business"] + w("Break-even (economics)"), "break-even", tol=0.5))
    # critical path: tiny graphs
    T.append(numeric("Tasks: Design 3 days, then Art 5 days and Code 7 days in parallel after Design, then Test 2 days after both. What is the project's critical path length in days?", 3 + 7 + 2, w("Critical path method"), "critical-path", tol=0.5, unit="days?"))
    T.append(numeric("Tasks: Concept 2 days; Modelling 6 days after Concept; Rigging 3 days after Modelling; Texturing 4 days after Modelling (parallel with Rigging); Animation 5 days after Rigging and Texturing. How many days is the critical path?", 2 + 6 + 4 + 5, w("Critical path method"), "critical-path-2", tol=0.5, unit="days?"))
    T.append(numeric("A sprint has 10 working days and the team of 4 loses one person for 3 days to illness. How many person-days of capacity remain?", 4 * 10 - 3, w("Sprint (software development)"), "capacity", tol=0.5))
    # game design: drop rate expected attempts
    for p in [0.05, 0.2]:
        T.append(numeric(f"A boss drops a rare item with probability {p} per kill. On average, how many kills until the first drop (the expected value of a geometric distribution)?", 1 / p, [OPENSTAX + "statistics"] + w("Expected value", "Loot (video games)"), "geometric", rel=0.01))
    # level design: scale
    T.append(numeric("A Roblox-style character is about 5 studs tall and represents a 1.8 m person. How many metres does a 40-stud-wide room represent?", 40 * 1.8 / 5, w("Scale (ratio)"), "scale", rel=0.01, unit="m"))
    T.append(numeric("A level is designed for a 10-minute playthrough at a walking speed of 4 m/s with 40% of time spent moving. Roughly how many metres of path should it contain?", 600 * 0.4 * 4, w("Pacing", "Level design"), "path-length", rel=0.01, unit="m"))
    # writing: reading time
    for words, wpm in [(1500, 250), (800, 200)]:
        T.append(numeric(f"A quest text has {words} words. At {wpm} words per minute, how many minutes does it take to read?", words / wpm, w("Readability"), "reading-time", rel=0.01, unit="min"))
    rng.shuffle(T)
    return T


# ---------------------------------------------------------------- multi-step reasoning tasks (rubric keys)

def reasoning_tasks():
    T = []
    T.append(rubric("Plan a first level for a 3D platformer that teaches wall-jumping. Describe the sequence of rooms or beats and say why each is there.", [["safe|no (danger|hazard|penalty)|cannot (die|fail)|low stakes|introduc"], ["(single|one|first) wall|simple|basic"], ["combine|chain|two walls|harder|variation|twist|develop"], ["checkpoint|respawn|retry"], ["test|final|challenge|prove|conclude"]], "Beat 1: a safe pit where a single wall-jump is the only way out, no hazards, so the player discovers the move. Beat 2: two or three single wall-jumps with a checkpoint before each, adding small gaps. Beat 3: a twist, chaining wall-jumps between two walls over a harmless drop. Beat 4: a final challenge combining the chain with a moving platform and a checkpoint right before it, so retries are cheap.", w("Level design", "Kishōtenketsu", "Checkpoint (video games)"), "plan-level", min_required=4))
    T.append(rubric("You have 6 weeks, 2 developers and 1 artist to ship a small co-op puzzle game demo. Lay out a week-by-week schedule with milestones and say what you would cut first if week 4 slips.", [["week ?1|first week|pre-?production|prototype|greybox"], ["milestone|alpha|beta|feature[- ]complete|content lock"], ["playtest|test"], ["buffer|slack|polish|bug|fix"], ["cut|drop|defer|scope"]], "Week 1: prototype the core puzzle mechanic in greybox (devs) while the artist sets the style. Weeks 2-3: build 5 puzzles, milestone 'alpha: all puzzles playable'. Week 4: art pass and co-op networking, milestone 'feature complete'. Week 5: playtests with outsiders, bug fixing. Week 6: polish and buffer, milestone 'demo build'. If week 4 slips, cut puzzles 4-5 and any optional art first, never the playtest week.", w("Project management", "Milestone (project management)", "Scope management"), "plan-schedule", min_required=4))
    T.append(rubric("Players say your tycoon game 'gets boring after 20 minutes'. Diagnose three likely design causes and propose a fix for each.", [["loop|repetiti|same action|grind"], ["progression|unlock|goal|milestone|new (content|mechanic)"], ["feedback|reward|juice|celebrat"], ["pac|curve|too (slow|fast)|plateau|cost"]], "Cause 1: the core loop never changes (collect, buy, repeat) so add a new mechanic or layer every few minutes, such as workers or automation. Cause 2: the progression curve plateaus, with the next purchase costing too many minutes of income; retune costs so a new unlock arrives every 2-3 minutes. Cause 3: weak feedback, so rewards pass unnoticed; add celebration moments, sounds and visible changes to the plot when upgrades land.", w("Core gameplay loop", "Game balance", "Progression system"), "diagnose-design", min_required=3))
    T.append(rubric("A multiplayer shooter map has one team winning 70% of rounds. Walk through how you would find out why and what you would change.", [["data|telemetry|heat ?map|record|watch|replay|statistic"], ["spawn|sight ?line|line of sight|cover|chok|route|asymmetr"], ["mirror|symmetr|balance|move|rotate|swap sides|side swap"], ["playtest|test again|measure|verify|re-?run"]], "First gather data: kill heatmaps, round timers and replays to see where the winning team gets its kills. Likely causes are an asymmetric sightline or a spawn that reaches cover or the objective first. Fix by adding cover to break the sightline or moving the spawn so both sides reach the objective in equal time, or have teams swap sides each half. Then playtest again and check the win rate moves toward 50%.", w("Game balance", "Line of sight (video games)", "Spawn (video games)"), "diagnose-balance", min_required=3))
    T.append(rubric("Budget a 12-week production for an indie game with a team of 4 earning a loaded 1,200 per person-week, plus 3,000 for software and 2,500 for a contract composer. Give the total and explain a 15% contingency.", [["57,?600|57600"], ["63,?100|63100"], ["contingency|buffer|reserve|unexpected|risk"], ["9,?465|9465|72,?565|72565"]], "Labour: 4 x 12 x 1,200 = 57,600. Add software 3,000 and composer 2,500 for a base budget of 63,100. A 15% contingency (9,465) covers unknowns like a delayed milestone or extra audio, giving 72,565 in total.", [OPENSTAX + "introduction-business"] + w("Budget", "Cost overrun"), "budget", min_required=3))
    T.append(rubric("A player reports that the game 'feels floaty'. Explain what that usually means and give a step-by-step tuning plan for the jump.", [["gravity|fall(s)? (too )?slow|hang|air ?time"], ["higher gravity|increase gravity|faster fall|fall multiplier|shorter"], ["anticipation|squash|stretch|land|impact|sound|particle"], ["test|iterate|measure|compare|playtest"]], "Floaty usually means too little gravity and too long an air time, so the arc feels weightless. Step 1: raise gravity, especially on the way down (a fall multiplier), and shorten the hang at the apex. Step 2: add a quick anticipation crouch and a landing squash with dust and a thud sound. Step 3: compare before and after with playtesters and keep tuning the apex time toward roughly half a second.", w("Game feel", "Twelve basic principles of animation", "Gravity"), "diagnose-feel", min_required=3))
    T.append(rubric("Design a colour palette for a horror game's hospital level. State the dominant hue, the accent, how you light the player's path, and one accessibility check.", [["desaturat|muted|green|teal|sickly|cold|cool|grey|gray"], ["accent|red|warm|contrast|emergency"], ["light|lit|guide|lead|path|glow"], ["colour ?blind|color ?blind|contrast ratio|deuteran|not (rely|only) on colour"]], "Dominant hue: desaturated sickly green-teal with cold grey walls to feel clinical. Accent: a warm red reserved for blood, exit signs and danger so it reads instantly. Light the path with flickering warm lights above doors the player should take, leaving side rooms dark. Accessibility: check the red accent against the green walls in a deuteranopia simulator and add shape cues so danger is not colour only.", w("Color theory", "Warm and cool colors", "Color blindness"), "design-palette", min_required=3))
    T.append(rubric("Your co-op game shows other players teleporting and rubber-banding on a 150 ms connection. Reason through the netcode causes and propose a fix order.", [["interpolat|buffer|snapshot|smooth"], ["prediction|reconcil|rollback|correct"], ["tick|update rate|send rate|hz|packet"], ["measure|test|simulate (lag|latency)|artificial latency|network emulat"]], "Teleporting means remote positions are applied the moment they arrive; interpolate remote players between the last two snapshots with a small buffer. Rubber-banding means the server corrects the local player harshly; use client-side prediction with smooth reconciliation instead of snapping. Check the server tick and send rate (20 Hz is a fine start) and test with simulated 150 ms latency and 2% loss before and after each change.", w("Client-side prediction", "Netcode", "Interpolation"), "diagnose-netcode", min_required=3))
    T.append(rubric("A level's frame rate drops from 60 to 25 only in the forest area. Describe how you would diagnose and fix it.", [["profil|measure|frame time|gpu|cpu"], ["draw call|overdraw|poly|triangle|vertex|instanc|batch"], ["lod|level of detail|cull|occlusion|distance|impostor|billboard"], ["shadow|light|transparen|particle|foliage"]], "Profile first to see if the forest is CPU-bound (many draw calls) or GPU-bound (overdraw, shadows). Trees usually mean thousands of draw calls and heavy transparency overdraw from leaves; batch or instance the trees, add LODs and impostors for distant ones, enable occlusion culling, and reduce shadow-casting distance for foliage. Re-measure after each step.", w("Level of detail (computer graphics)", "Occlusion culling", "Graphics pipeline"), "diagnose-performance", min_required=3))
    T.append(rubric("Write a short outline for a three-act quest about a lighthouse keeper who has vanished, giving the inciting incident, midpoint twist and resolution with a choice.", [["act (1|one|i)|inciting|vanish|missing|keeper"], ["midpoint|twist|reveal|discover"], ["act (3|three|iii)|resolution|choice|choose|decide|ending"], ["stake|storm|ship|danger|why it matters|consequence"]], "Act 1: a storm is coming and ships will wreck without the light; the keeper has vanished, so the player must relight it. Midpoint twist: the player finds the keeper's journal and learns she left on purpose to stop a smuggler using the light to lure ships. Act 3: the player catches the smuggler at the lamp and must choose to relight the beacon for the fleet or keep it dark to save the keeper hiding on the rocks; the choice changes the epilogue.", w("Three-act structure", "Plot twist", "Branching narrative"), "plan-quest", min_required=3))
    T.append(rubric("Players skip your tutorial and then get lost. Diagnose the problem using UX principles and propose a redesign.", [["forced|modal|wall of text|long|boring|skip"], ["learn by doing|contextual|just[- ]in[- ]time|progressive disclosure|in context"], ["affordance|signifier|visual|cue|highlight|guide|breadcrumb"], ["measure|analytic|funnel|test|drop[- ]?off"]], "A long modal tutorial up front is skipped because it blocks play and asks players to remember things they have no context for. Replace it with progressive disclosure: teach each control the first time it is needed with a short contextual prompt, and use visual signifiers such as lit doorways to guide the path. Measure the drop-off funnel before and after to confirm fewer players get lost.", w("Progressive disclosure", "Onboarding", "Affordance"), "diagnose-ux", min_required=3))
    T.append(rubric("Plan a 90-second music cue for a boss fight with three phases. Say how tempo, instrumentation and key change per phase and how the cue adapts to the player's health.", [["tempo|bpm|faster|accelerat"], ["layer|instrument|add|drum|brass|string|choir|synth"], ["key|modulat|minor|dissonan|semitone|higher"], ["adaptive|health|low health|stinger|transition|loop|state"]], "Phase 1: 120 BPM, low strings and a sparse drum pattern in D minor, looping. Phase 2: adds brass stabs and doubles the drums, modulating up a semitone to raise tension. Phase 3: 140 BPM, full choir layer and a dissonant pedal tone. The cue is adaptive: each phase is a loop with transition stingers, and when the player drops under 25% health a heartbeat layer fades in and the high frequencies are filtered.", w("Adaptive music", "Tempo", "Leitmotif"), "plan-music", min_required=3))
    T.append(rubric("A spring-driven character controller oscillates forever instead of settling. Reason about the physics and name the fix.", [["damping|damper|friction|drag"], ["underdamp|energy|no (loss|dissipation)|conserv|oscillat"], ["critical|ratio|coefficient|tune|increase"], ["time ?step|integrat|euler|stability|dt"]], "A spring with no damping conserves energy, so it oscillates forever; add a damping force proportional to velocity. Tune toward critical damping (damping ratio near 1) so it settles fastest without overshoot. Also check the integrator: a large time step with explicit Euler can add energy and look like endless bouncing, so clamp dt or use semi-implicit Euler.", w("Simple harmonic motion", "Hooke's law", "Euler method"), "diagnose-physics", min_required=3))
    T.append(rubric("Design a fair matchmaking plan for a new 1v1 game with few players online. Explain the rating system, how you widen the search, and how you avoid discouraging beginners.", [["elo|glicko|rating|mmr|skill"], ["widen|expand|window|range|wait|time"], ["new player|beginner|placement|provisional|protect|bot|separate"], ["measure|win ?rate|50|retention|monitor"]], "Use a Glicko-style rating with uncertainty so new players converge quickly. Start searching within 50 rating points and widen the window every 10 seconds, capping wait at a minute. Protect beginners with placement matches against other new players or bots, and never match a provisional player with a veteran. Monitor win rates toward 50% and early retention to tune the widening speed.", w("Matchmaking (video games)", "Glicko rating system", "Elo rating system"), "plan-matchmaking", min_required=3))
    T.append(rubric("Estimate how many polygons a mobile game can afford per frame if the budget is 300,000 triangles, 20 enemies are on screen at 4,000 each and the environment uses 150,000. Show the reasoning and say what you would do if a boss needs 60,000.", [["80,?000|80000"], ["70,?000|70000"], ["lod|level of detail|reduce|fewer enemies|cull|budget|impostor"], ["remaining|left|subtract|300,?000"]], "Enemies take 20 x 4,000 = 80,000 and the environment 150,000, so 230,000 of the 300,000 budget is used and 70,000 remain. A 60,000-triangle boss nearly fills that, leaving nothing for effects or the player, so give the boss LODs, drop enemies to a lower LOD while the boss is present, or cull distant environment detail.", w("Low poly", "Level of detail (computer graphics)"), "budget-polygons", min_required=3))
    T.append(rubric("Explain, step by step, how you would check whether a new lesson for an AI assistant actually improves its answers rather than just appearing to, using a paired test.", [["same (tasks|questions|set)|paired|pair"], ["with and without|baseline|control|both"], ["sign test|p-?value|significan|binomial|statistic"], ["held[- ]?out|unseen|not tuned|separate|blind"]], "Pick a held-out set of tasks the lesson was not written from. Answer every task twice, with and without the lesson, same model and settings, interleaved. Count the tasks that flip from fail to pass and pass to fail and run a sign test; keep the lesson only if the improvement is significant (p below 0.05), not merely positive.", w("Sign test", "Statistical hypothesis testing"), "plan-experiment", min_required=3))
    T.append(rubric("Diagnose why a Simple English Wikipedia-style explanation of gravity for ten-year-olds is failing with its readers: it uses 'gravitational acceleration', three equations and no example. Rewrite the first paragraph.", [["simpl|plain|short|everyday|jargon|technical"], ["example|drop|ball|apple|fall|jump"], ["pull|attract|toward|down"], ["equation|number|formula"]], "The paragraph fails because it uses jargon and equations before any picture of what gravity does. Rewrite: Gravity is the pull that makes things fall. Drop a ball and it falls to the ground because the Earth pulls it. Gravity pulls everything toward the Earth, which is why you come back down after you jump. Bigger things pull harder, and the Earth is very big, so it pulls very hard.", w("Plain language", "Readability", "Gravity"), "rewrite-plain", min_required=3))
    T.append(rubric("Plan a two-week playtest for a puzzle game: who you recruit, what you measure, how you run sessions, and how you turn findings into changes.", [["recruit|participant|tester|players? who|new|target"], ["measure|time|complet|stuck|hint|record|observe|metric"], ["think[- ]aloud|observe|don'?t help|do not help|silent|session"], ["priorit|severity|fix|iterate|change|retest"]], "Recruit 8-10 players matching the target audience who have never seen the game. Measure time per puzzle, where players get stuck, hints requested and completion rate, recording the screen. Run one-hour sessions where players think aloud and the moderator does not help. Afterwards rank findings by how many players hit them and how badly, fix the top issues, and retest in week two.", w("Playtest", "Usability testing"), "plan-playtest", min_required=3))
    T.append(rubric("A friend's game raised its price from 5 to 8 and sales fell 50%. Reason about price elasticity and revenue, and recommend what to do next.", [["elastic"], ["revenue|5 ?x|8 ?x|half|0\\.5|less (money|revenue)|lower revenue|fell"], ["test|experiment|a/b|region|discount|sale|data"], ["value|content|bundle|perceived|position"]], "Demand looks elastic: a 60% price rise cut units by half, so revenue fell from 5 per unit on N sales to 8 on N/2, that is 4N versus 5N, about 20% less. Test prices rather than guess: try 6 and 7 in different regions or during a sale and compare revenue, and consider adding content or a bundle so the higher price matches perceived value.", [OPENSTAX + "introduction-business"] + w("Price elasticity of demand", "Pricing"), "diagnose-pricing", min_required=3))
    T.append(rubric("Explain how to turn a 2D top-down maze into a procedural generator, from data structure to guaranteed solvability, in steps.", [["grid|cell|array|tile"], ["dfs|depth[- ]first|prim|kruskal|recursive backtrack|spanning tree|wilson"], ["connected|solvable|path|reach|spanning|every cell"], ["seed|random|loop|door|variation|dead end"]], "Represent the maze as a grid of cells with four walls each. Carve passages with a randomised depth-first search (recursive backtracker): start at a cell, visit a random unvisited neighbour, knock down the wall between them, and backtrack when stuck. Because this builds a spanning tree, every cell is reachable, so a start and exit anywhere are always solvable. Seed the random generator for reproducible levels and optionally knock out a few extra walls to add loops.", w("Maze", "Depth-first search", "Procedural generation"), "plan-procgen", min_required=3))
    return T


DOMAINS = {
    "game-design": game_design, "level-design": level_design, "animation-3d": animation_3d,
    "art-fundamentals": art_fundamentals, "audio-music": audio_music, "writing-narrative": writing_narrative,
    "ux-design": ux_design, "production-management": production_management, "math": math_facts,
    "physics": physics_facts, "computer-science": computer_science, "networking": networking,
    "numeric": numeric_tasks, "reasoning": reasoning_tasks,
}
PREFIX = {"game-design": "GD", "level-design": "LD", "animation-3d": "AN", "art-fundamentals": "ART", "audio-music": "AUD",
          "writing-narrative": "WR", "ux-design": "UX", "production-management": "PM", "math": "MATH", "physics": "PHY",
          "computer-science": "CS", "networking": "NET", "numeric": "NUM", "reasoning": "RSN"}


def build_task(domain: str, index: int, item) -> tuple[dict, str]:
    kind, prompt, key, urls, topic, reference = item
    task_id = f"KN-{PREFIX[domain]}-{index:03d}"
    scope = {"exact": "the final answer line names the expected value", "numeric": "a number within tolerance on the final answer line",
             "choice": "the chosen option letter or text", "order": "the required items appear in order",
             "match": "each pair appears together in one line or sentence", "short": "required facts (regexes) are present",
             "rubric": "required rubric points (regexes) are present and the answer has enough words"}[kind]
    task = {
        "id": task_id,
        "topic": topic or domain,
        "category": "knowledge-" + domain,
        "difficulty": 3 if kind == "rubric" else 2 if kind in ("numeric", "short", "order", "match") else 1,
        "goal": f"Answer a {domain} question correctly ({kind} key).",
        "prompt": prompt,
        "run_mode": "automated",
        "fixture_status": "not_needed",
        "fixtures": [],
        "split": "development",
        "source_urls": urls,
        "scoring_scope": f"knowledge check: {scope}; not code",
        "budget": {"model_calls": 1, "tool_calls": 2, "output_tokens": 600 if kind == "rubric" else 300, "wall_seconds": 240},
        "pass_conditions": [f"The answer satisfies the {kind} key (star.knowledge_checks)"],
        "required_evidence": ["answer.md", "check-results.json"],
        "auto": {"code": False, "answer": key},
    }
    return task, reference


def main() -> None:
    references = []
    total = 0
    for domain, maker in DOMAINS.items():
        tasks = []
        for index, item in enumerate(maker(), 1):
            task, reference = build_task(domain, index, item)
            tasks.append(task)
            references.append({"id": task["id"], "reference": reference})
        path = OUT / f"knowledge-{domain}-{DATE}.json"
        path.write_text(json.dumps(tasks, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        total += len(tasks)
        print(f"{domain}: {len(tasks)} tasks -> {path.name}")
    (OUT / f"knowledge-references-{DATE}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in references), encoding="utf-8")
    print("total", total)


if __name__ == "__main__":
    main()
