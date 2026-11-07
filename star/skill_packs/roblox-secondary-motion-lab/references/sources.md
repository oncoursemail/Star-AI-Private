# Sources checked October 20, 2026

S1. SmartBone 2, upstream repository and README: https://github.com/smartbone-org/SmartBone-2
The upstream documents bone animation, wind, dynamic frustum culling, collision and rotational/distance/rope/spring constraints. Its README directs source users to src-build for the optimized build. No upstream code or reference media is copied into this package. Pin a concrete upstream revision before benchmarking; this recovery kit contains no such head-to-head measurements.

S2. Roblox AnimationConstraint: https://create.roblox.com/docs/reference/engine/classes/AnimationConstraint
Official rig-migration and API guidance for physical joints, Transform scheduling and kinematic/force-driven operation. Check the actual place's rig mode instead of assuming every existing rig has migrated.

S3. Roblox Bone: https://create.roblox.com/docs/reference/engine/classes/Bone
Official metadata marks Bone.Transform and TransformedWorldCFrame as not replicated. A custom solver's positions still need a tested coordinate-space and animation-ownership adapter.

S4. Macklin, Mueller and Chentanez, XPBD: Position-Based Simulation of Compliant Constrained Dynamics, MIG 2016, DOI 10.1145/2994258.2994272.
Paper landing page: https://doi.org/10.1145/2994258.2994272
Author explanation: https://blog.mmacklin.com/2016/09/15/xpbd/
This is a known published method, not an invention claimed by STAR. The new kernel implements a small distance-only subset with simple exponential velocity damping, not the paper's full dissipative formulation. Numerical residual, integration error and collision quality still require measurement.

S5. Roblox MicroProfiler: https://create.roblox.com/docs/performance-optimization/microprofiler
Use frame-time traces and instrumented script sections; inspect target mobile devices and compare consistent workloads. No native Roblox profile was collected for this recovery kit.

S6. Luau 0.743: https://github.com/luau-lang/luau/releases/tag/0.743
The pinned official Ubuntu archive used for portable checks has SHA-256:
99d45afb4afaee00ba631c526c8e8c76c67b60f6f119953ce6409be6d6953663
The executable was downloaded and checked in an isolated temporary test directory on the authorized STAR server, not installed into a running service. Portable Luau success is not native Roblox acceptance.
