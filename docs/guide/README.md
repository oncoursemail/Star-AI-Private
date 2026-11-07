# STAR user guide

STAR is an AI assistant that runs on your own Windows PC, made especially for building Roblox games. This guide is
written for everyone, not just programmers. Start with **Getting started**, then dip into whatever you need.

## Pages

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | What you need, installing STAR, giving it a brain, your first chat, updates |
| [Chatting with STAR](chatting.md) | The chat list (rename, delete, undo), modes, and the **+** menu: files, Look at my screen, Create image, web search |
| [Set up a STAR Server brain](star-server.md) | Using a more powerful computer on your home network as STAR's brain |
| [Talk to STAR on Discord](discord-bot.md) | Setting up your own private STAR bot |
| [Voice and calls](voice-and-calls.md) | Star's voice, turning recordings into text, and live calls (coming soon) |
| [Roblox tools](roblox-tools.md) | Roblox questions, Luau checks, map plans, connecting Roblox Studio safely, Studio Lab (coming soon) |
| [Design tools](design-tools.md) | Colours, fonts, DESIGN.md notes, pictures, simple Blender models |
| [UI evidence contracts](ui-evidence-contract.md) | Experimental checks for required screens, states, viewports and evidence bindings |
| [Self-learning](self-learning.md) | Lessons, corrections, night school, "What STAR learned this week", and how to undo it all |
| [Privacy and data](privacy-and-data.md) | What is stored where, what leaves your PC, deleting and backing up |
| [Troubleshooting and FAQ](troubleshooting.md) | Error messages and what to do, common questions, asking for help |
| [IK trace diagnostics](ik-trace-diagnostics.md) | Opt-in developer check of IK trace files (offline; does not change STAR) |
| [Computer driver recovery](computer-driver-recovery.md) | Opt-in safety for STAR's computer control: no uncertain replays, optional outcome waits |
| [Glossary](glossary.md) | Plain-language meanings of the words STAR uses |

## What the status labels mean

Every feature in this guide is marked with one of three labels:

- **Available**: in STAR now and works without extra setup (apart from having a brain).
- **Opt-in**: in STAR now, but you have to switch it on or install something extra first.
- **Coming soon**: being worked on, but not in STAR yet. Do not expect to find it in the app.

## Feature status at a glance

| Feature | Status | Notes |
|---|---|---|
| Chat with the brain on your PC | Available | Needs a graphics card with about 8 GB of video memory |
| Chat list: search, rename, delete with undo, copy | Available | No pinning yet |
| Fast / Auto / Agent modes | Available | |
| Add photos and files | Available | Video needs FFmpeg |
| Look at my screen | Available | Always asks first |
| Create image | Opt-in | Needs ComfyUI and an image model on your PC |
| Search the web | Opt-in | Needs a STAR Server with search, or a Brave/Tavily key |
| Transcribe audio | Opt-in | Needs the voice add-on |
| STAR Server brain | Opt-in | |
| Cloud AI providers | Opt-in | Your own key; never used unless you select one |
| Discord bot | Opt-in | Set up from a command window; early version |
| Choose Star's voice | Available | Preview needs the voice engine |
| Live voice calls in the app | Coming soon | |
| Roblox questions with sources | Available | Documentation search needs a STAR Server |
| Luau checks | Available | Full compiler check needs a STAR Server |
| Map plans | Available | Plans only |
| Roblox Studio: reading | Opt-in | |
| Roblox Studio: building in a test place | Opt-in | Off until you switch it on |
| Roblox Open Cloud test pipeline | Opt-in | Every action needs your approval |
| Studio Lab | Coming soon | |
| Colours, fonts, DESIGN.md | Available | Saving files is opt-in |
| UI evidence contracts | Opt-in | Experimental; checks supplied evidence, does not run the interface |
| Blender models | Opt-in | Early draft |
| Lessons and corrections | Available | |
| What STAR learned this week | Available | Empty until a release includes night school lessons |
| Night school | Coming soon | Runs on a STAR Server; results not shipped yet |

## About this guide

- It describes STAR's current development version (checked against the code in October 2026). The newest published
  installer is v0.9.0, so a few labels may differ slightly there.
- Screenshots come from STAR's design review and show example chats, not real data.
- Developer and technical documents live one folder up, in [docs](../).
