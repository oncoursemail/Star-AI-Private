# Design tools

STAR can help with the look of your game, app or website: colours, fonts, layouts, design notes, pictures and
simple 3D models. Most of these work by just asking in a chat.

## Colours, fonts and layout ideas

**Status: Available** (works offline, nothing to switch on)

Ask about a palette, colour scheme, font pairing, typography, design system, contrast, a website or a landing
page, for example: *"Suggest a dark fantasy colour palette and a font pairing for my game's menus, with good
contrast."*

STAR then searches a design library bundled with it (88 interface styles, 192 colour palettes, 74 font
pairings and 119 usability rules) and checks colour contrast against the common WCAG readability standard.
Nothing is sent to the internet for this.

The starter idea **Design a Roblox inventory UI** on a new chat is a good place to begin for game menus.

## DESIGN.md design notes

**Status: Available** (saving the file is **Opt-in**)

A `DESIGN.md` file is a short, structured description of a project's colours, text styles, spacing and
components that people and AI tools can both read. Ask STAR to **draft**, **check** or **read** one, for example
*"Draft a DESIGN.md for a cosy farming game UI."*

STAR shows the result in the chat. To let STAR save it into your project folder, set a **Workspace folder** and
turn on **Allow workspace writes** in Settings → **Advanced settings** → **Developer permissions**. Both start off.

## Check UI evidence across states and devices

**Status: Experimental, off by default.** The existing read-only visual auditor can now take an optional
UI evidence contract: required screens, viewport sizes, interface states, input methods and motion preferences.
It distinguishes missing evidence from failing checks, and detects stale source, screenshot and trace bindings.
It does not run the application or certify design quality. See [UI evidence contracts](ui-evidence-contract.md)
for activation, the file format, examples and the precise limits of the result.

## Pictures

**Status: Opt-in** (needs ComfyUI on this PC)

- **Create or edit pictures:** use **+ → Create image**. See [Create image](chatting.md#create-image).
- **Ask about a picture:** attach it with **+ → Add photos and files** and ask your question.
- **Visual references:** on **Projects**, the **Visual references** panel lets you **Pin an image** (up to 12)
  that STAR should keep in mind for this project, **Compare latest image** or **Compare a file** against your
  references, and **Remove for good**. Turn off **Use this project's visual references** in Settings → **Where
  STAR generates** if you do not want STAR to use them.

## Simple 3D models with Blender

**Status: Opt-in** (early draft)

If Blender is installed on your PC, STAR can create simple new 3D scenes from basic shapes (blocks, cones,
rocks, stylised trees, arches, roofs) and save them as a `.blend` file and a `.glb` file you can import into
Roblox Studio yourself.

1. Install Blender from the official Blender website.
2. In STAR, open **Tools** (or Settings) and find the Blender panel (**Blender for Brain 2**).
3. Turn on **Enable**, then click **Test local Blender**. Fill in **Blender executable** only if STAR cannot
   find Blender by itself.
4. To let STAR make files, also turn on **Permit creating new Blender scenes**. STAR only ever writes new
   files in its own folder. It never changes your existing `.blend` files and never runs other scripts.
5. Ask in a chat, for example with the starter idea **Plan a Blender model**.

Results are simple blockouts, not finished art. Review them in Blender and import them into Studio by hand.

## Map plans

**Status: Available.** Planning Roblox maps and blockouts is covered in [Roblox tools](roblox-tools.md#map-plans).

## Asset Forge

**Status: Opt-in** (experimental). Tools → **STAR Tool Workshop** → **Enable experimental Asset Forge
planning** is off by default. It is a planning aid still being tested; leave it off unless you are helping test it.
