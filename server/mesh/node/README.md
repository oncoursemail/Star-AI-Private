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
- Busy guard every 2.5 s: full-screen program in front; a stream or VR program running (OBS, Streamlabs, XSplit,
  SteamVR, Oculus; also from the tray); a game showing a window (Roblox player/Studio, Rec Room / Metallic RC, VRChat,
  Minecraft Bedrock, any program under `\steamapps\common\`, Minecraft Java = javaw with "minecraft" in its path or
  window title; a leftover game process with no window does not count); another program's GPU load (>= 40 % on two
  looks while the model is not answering); other programs growing video memory by 1200 MB; or not enough free video
  memory to load. Then llama-server is killed at once (the card is free in about a second) and the
  state is `busy`; the model comes back after `resume_seconds` (180) with nothing in the way.
- States: `idle` (loaded, serving), `draining`, `busy`, `away` (not loaded: loading, unloaded on request, failed),
  `off` (file `OFF`). Memory pressure (a lower ngl step, too little free memory, others +1200 MB) while an answer
  runs -> `draining`: no new requests (503; the router skips it), the answers in flight finish (at most
  `drain_seconds`, 30), then the reload/unload. Games, stream/VR programs, full screen and FAKE_BUSY still stop the
  model at once (state `busy` first); a stream cut that way ends with an SSE error event (`node_cut`) and the
  router continues the answer on the next backend.
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
Args: `-lm none --fit off -ngl 99 -fa on -ctk q4_0 -ctv q4_0 -np 1 -b 512 -ub 128 -t 4 --jinja --reasoning off`,
`ctx 8192`.

**Speculative decoding (MTP drafter, 2026-10-28, docs/agents/litha-speed-20261028.md):** the top ladder step
`[100, 7330, ["--model-draft", "models/mtp-gemma-4-12B-it-qat-Q4_0.gguf", "--spec-type", "draft-mtp",
"--spec-draft-n-max", "4", "-ngld", "99"]]` adds Google's 12B QAT assistant as a multi-token-prediction drafter
(GGUF: unsloth/gemma-4-12B-it-qat-GGUF `MTP/mtp-gemma-4-12B-it-Q4_0.gguf`, 254 MB; needs llama.cpp with
`draft-mtp`, b11936 has it). 20 eval prompts: 45 -> 86 tok/s, 4.5 -> 2.5 s per 200 tokens, 52% of drafted tokens
accepted; +250 MB on the card (7263 MB loaded at -c 8192 -ub 128). With -ub 256 it does not fit next to the desktop
and spills into shared memory (38 tok/s, slower than no drafter). `ngl 100` = all layers, ranked above the plain 99
step, so a busier desktop falls back to plain -ngl 99; a step whose .gguf is missing loads without its extra args.
Prompt reading is ~900-1100 tok/s with the drafter and -ub 128 (vs ~1300-1450 before). The owner's apps (Metallic Launcher/QtWebEngine, browser, Discord) need room on the same card, so the node
keeps `vram_reserve_mb` (1536) free as nvidia-smi reports it (memory.free): `ngl_ladder` lists [ngl, the model's
measured card memory]; the node loads the highest step that still leaves the reserve. Measured on the owner's RTX
3060 Ti (2026-10-28, -c 8192, q4_0 KV, -np 1):

| -ngl | model's card memory | gen tok/s |
|---|---|---|
| 99 | 7011 MB | 46.8 |
| 47 | 6771 MB | 34.6 |
| 46 | 6649 MB | 30.3 |
| 44 | 6403 MB | 25.0 |
| 43 | 6277 MB | 22.5 |
| 42 | 6153 MB | 20.3-21.2 |
| 41 | 6029 MB | 18.5-18.9 |
| 40 | 5905 MB | 15.7-17.9 |

Default on the owner PC: `vram_reserve_mb` 150, `min_free_loaded_mb` 100, so -ngl 99 loads (~46 tok/s, ~200-500 MB
left free). Decided by screen recordings (2026-10-28, 60 s each, Metallic Launcher window on top, dropout counter):
node off 0 + 0, -ngl 40 generating 0, -ngl 99 generating 0 + 0 (195 MB free, 95% GPU), -ngl 99 idle 0. While
loaded, under `min_free_loaded_mb` free or other programs +1200 MB -> lower step or unload. The code defaults
(1536 / 800) are the cautious setting for a machine nobody has measured yet.
Other things tried: -np 2 costs ~200 MB more; q8_0 KV ~120 MB more; -c 6144/-ub 128 saves only ~20-40 MB; the output
layer on the CPU (`-ot token_embd\.weight=CPU`) gives the same tok/s per MB as fewer layers. RTX 4060 (STAR's PC): same
file and args; measure its ladder (her desktop use differs). A 4 GB card (GTX 1650) cannot hold this model.
