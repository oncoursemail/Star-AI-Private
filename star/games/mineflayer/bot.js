// STAR's Minecraft client (driven by star/games/minecraft.py over JSON lines on stdin/stdout).
// Config comes from the STAR_MC_CONFIG environment variable: {host, port, username, auth, version, profilesFolder}.
// Plain player actions only: walk (pathfinder), chat, dig, place. No fly, reach, x-ray or combat automation.
'use strict'
const readline = require('readline')
const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')

const cfg = JSON.parse(process.env.STAR_MC_CONFIG || '{}')
const emit = (event) => process.stdout.write(JSON.stringify(event) + '\n')

const bot = mineflayer.createBot({
  host: cfg.host || 'localhost',
  port: cfg.port || 25565,
  username: cfg.username || 'Star',
  auth: cfg.auth || 'offline',
  version: cfg.version || false,
  profilesFolder: cfg.profilesFolder,
  onMsaCode: (data) => emit({ type: 'auth_code', uri: data.verification_uri, code: data.user_code })
})
bot.loadPlugin(pathfinder)

const playerCount = () => Object.keys(bot.players).filter((name) => name !== bot.username).length

bot.once('spawn', () => {
  bot.pathfinder.setMovements(new Movements(bot))
  emit({ type: 'spawn', players: playerCount() })
})
bot.on('playerJoined', () => emit({ type: 'players', count: playerCount() }))
bot.on('playerLeft', () => emit({ type: 'players', count: playerCount() }))
bot.on('chat', (username, message) => {
  if (username !== bot.username) emit({ type: 'chat', username, message })
})
bot.on('whisper', (username, message) => {
  if (username !== bot.username) emit({ type: 'whisper', username, message })
})
bot.on('kicked', (reason) => emit({ type: 'kicked', reason: String(reason).slice(0, 300) }))
bot.on('error', (err) => emit({ type: 'error', message: String(err && err.message).slice(0, 300) }))
bot.on('end', (reason) => { emit({ type: 'end', reason: String(reason) }); process.exit(0) })

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function gather (blockName, count) {
  const info = bot.registry.blocksByName[blockName]
  if (!info) return 0
  let got = 0
  for (const pos of bot.findBlocks({ matching: info.id, maxDistance: 32, count })) {
    const block = bot.blockAt(pos)
    if (!block || block.name !== blockName) continue
    await bot.pathfinder.goto(new goals.GoalLookAtBlock(pos, bot.world))
    await bot.dig(block)
    await bot.pathfinder.goto(new goals.GoalBlock(pos.x, pos.y, pos.z)).catch(() => {}) // walk over the drop
    got += 1
  }
  return got
}

async function buildPillar (height) {
  const item = bot.inventory.items().find((i) => bot.registry.blocksByName[i.name] && !i.name.includes('sapling'))
  if (!item) return 0
  await bot.equip(item, 'hand')
  const base = bot.entity.position.floored().offset(1, -1, 0)
  let placed = 0
  for (let i = 0; i < height; i++) {
    const below = bot.blockAt(base.offset(0, i, 0))
    if (!below || below.name === 'air') break
    await bot.placeBlock(below, { x: 0, y: 1, z: 0 })
    placed += 1
    await sleep(400)
  }
  return placed
}

async function run (cmd) {
  switch (cmd.cmd) {
    case 'chat': bot.chat(String(cmd.text || '').slice(0, 250)); break
    case 'whisper': bot.whisper(String(cmd.username), String(cmd.text || '').slice(0, 200)); break
    case 'follow': {
      const target = bot.players[cmd.username] && bot.players[cmd.username].entity
      if (target) bot.pathfinder.setGoal(new goals.GoalFollow(target, 2), true)
      else emit({ type: 'done', task: 'follow', ok: false, note: 'cannot see them' })
      break
    }
    case 'stop': bot.pathfinder.setGoal(null); break
    case 'gather': emit({ type: 'done', task: 'gather', got: await gather(cmd.block, cmd.count || 4) }); break
    case 'build_pillar': emit({ type: 'done', task: 'build_pillar', placed: await buildPillar(cmd.height || 4) }); break
    case 'wander': {
      const d = cmd.distance || 16
      const p = bot.entity.position
      await bot.pathfinder.goto(new goals.GoalNear(p.x + (Math.random() * 2 - 1) * d, p.y,
        p.z + (Math.random() * 2 - 1) * d, 2)).catch(() => {})
      emit({ type: 'done', task: 'wander' })
      break
    }
    default: emit({ type: 'error', message: 'unknown command ' + cmd.cmd })
  }
}

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let cmd
  try { cmd = JSON.parse(line) } catch (e) { return }
  run(cmd).catch((err) => emit({ type: 'done', task: cmd.cmd, ok: false, note: String(err && err.message).slice(0, 200) }))
})
process.stdin.on('end', () => bot.quit())
