# Litha mesh node (Windows GPU PC)

Lends this PC's NVIDIA card to the STAR compute mesh while nobody needs it. One self-contained folder:

| File | What |
|---|---|
| `node_agent.py` | the node (Python standard library only, 3.9+) |
| `node.json` | this machine's settings (model, llama args, router URL, thresholds) |
| `install.cmd` / `uninstall.cmd` | per-user scheduled task (every 5 min, one copy via a mutex, hidden), firewall rule if admin |
| `engine\` | llama.cpp CUDA build (`llama-server.exe` + DLLs), optional if node.json points elsewhere |
| `models\` | the `.gguf` file(s) |
| `python\` | optional embeddable Python; otherwise `py -3` / `python.exe` on PATH / `LITHA_PYTHON` |
| `logs\` | `node.log` (state changes, loads, tok/s), `llama-server.log` |

## What it does
- `GET :8099/status` -> `{"node","state","reason","gpu":{name,vram_total_mb,vram_free_mb,util},"ram_free_mb","models":[{id,url,ctx,loaded,tok_s,...}],"ts"}`.
- `POST :8099/load` (`{"model":"litha-fast"}`, optional `"wait":true`) and `POST :8099/unload`: `Authorization: Bearer <mesh token>`.
  After `/unload` the node stays unloaded until the next `/load`.
- `:8098/v1/...`: the model (OpenAI-compatible), same token. llama-server itself listens on 127.0.0.1:18098 only; the
  node forwards to it, counts requests in flight and answers 503 while the model is not loaded.
- Self-registers with the mesh router every 30 s (`POST <router_url>/mesh/register`, token, `{"node","status_url","model_url"}`),
  so a PC with an unknown address joins by itself. `router_url` in node.json; empty = no registration.
- Busy guard every 2.5 s: full-screen program in front, a known game/stream/VR program (Roblox player/Studio, OBS,
  Streamlabs, Rec Room / Metallic RC, SteamVR, Oculus, VRChat, Minecraft Bedrock), any program under
  `\steamapps\common\`, Minecraft Java (javaw with "minecraft" in its path or window title), another program's GPU load
  (>= 40 % on two looks while the model is not answering), other programs growing video memory by 1200 MB, or not
  enough free video memory to load. Then llama-server is killed at once (the card is free in about a second) and the
  state is `busy`; the model comes back after `resume_seconds` (180) with nothing in the way.
- States: `idle` (loaded, serving), `busy`, `away` (not loaded: loading, unloaded on request, failed), `off` (file `OFF`).
- Test hook: create the file `FAKE_BUSY` in the folder -> busy within one poll; delete it -> reload after `resume_seconds`.
- Mesh token: `%USERPROFILE%\.star\mesh_token` (created with 32 random bytes if missing). Every node and the router
  must have the SAME token: copy the file, never paste it into chat or a commit.

Commands (in the folder): `python node_agent.py status | load | unload | off | on`.

## Install on this PC
1. Put `llama-server.exe` (CUDA build) + DLLs in `engine\` and the model in `models\`, or point node.json at them
   (`~` and relative paths work).
2. Copy the mesh token to `%USERPROFILE%\.star\mesh_token`.
3. Set `node`, `router_url`, `llama_args`, `need_free_vram_mb` in node.json (see "Model settings").
4. Run `install.cmd`. As administrator it also adds the firewall rule (TCP 8098,8099, remote LocalSubnet only, program
   = the python.exe that runs the node). Without admin rights the exact rule is written to `OWNER-TODO.txt`.
5. Check: `http://127.0.0.1:8099/status`.

Remove: `uninstall.cmd` (unloads, stops, deletes the task; the folder and token stay).

## STAR's PC (`D:\Litha`), one command from the owner's PC
Needs Windows OpenSSH on her PC with this PC's key (address and user unknown on 2026-10-27). From the owner's PC,
in the installed copy of this folder:

```
python node_agent.py deploy --ssh <user>@<her-pc> --dir D:\Litha ^
  --engine %USERPROFILE%\models\llama.cpp ^
  --model %USERPROFILE%\models\litha\gemma-4-12b-it-qat-q4_0.gguf ^
  --node-json node-star-pc.json
```

`--python <folder>` also copies a Python (an embeddable Python unzipped to a folder) into `D:\Litha\python` when her PC
has none. `deploy` copies the package, the engine, the model (about 7 GB) and the mesh token, then runs `install.cmd`
there (admin session: the firewall rule is added). `node-star-pc.json` = node.json with `"node": "star-pc"`,
`"llama_server": "engine/llama-server.exe"`, `"model_path": "models/gemma-4-12b-it-qat-q4_0.gguf"`, the router URL and
the RTX 4060 settings below. Without ssh: copy the same files by hand into `D:\Litha` (+ the token into
`%USERPROFILE%\.star\`) and run `D:\Litha\install.cmd` as administrator.

Her games/streams are already in the block list; add others to `block_processes` in her node.json.

## Model settings (8 GB cards, gemma-4-12b QAT Q4_0, 7.0 GB file)
The file does not fit fully next to a desktop's ~1.5 GB, so the default keeps 46 of 48 layers on the card with a q8_0
KV cache: `--fit off -ngl 46 -fa on -ctk q8_0 -ctv q8_0 -t 4 -np 1 --jinja`, `ctx 8192`, `need_free_vram_mb 5800`.
Replace with the bench lane's best settings (docs/agents/litha-engine-bench-20261027.md). A 4 GB card (GTX 1650)
cannot hold this model; give it a 4B model or leave `autoload` false.
