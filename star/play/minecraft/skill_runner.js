// STAR's Minecraft skill runner and state stream, for the Mineflayer client (star/games/mineflayer/bot.js).
//
// Wire-up in bot.js (two lines):
//   const play = require('../../play/minecraft/skill_runner.js')
//   const playHandle = play.install(bot, emit)          // after createBot; then in run(cmd), before `default:`
//   ... if (await playHandle(cmd)) return
//
// Commands in:  {cmd: 'run_skill', id, name, code, args, deps: {name: code}, timeout_ms}
//               {cmd: 'stop_skill'}
// Events out:   {type: 'state', t, health, food, pos, yaw, pitch, hostiles: [[name, dist]], players: [[name, dist]],
//                inventory: {item: count}, skill}   (every 1000/hz ms)
//               {type: 'skill_result', id, name, ok, error, ms, before, after}
//               {type: 'death'} / {type: 'respawn'}
// A skill is the body of `async function (bot, args, h)`; `h` has goals, sleep, look (a human-paced turn), skill
// (call another learned skill by name) and log. Skills run in a fresh vm context with only those names. Node's vm
// is NOT a security boundary: the Python side refuses code with require/process/import/eval/constructor before it
// gets here, and only STAR's own planner writes skills (never text copied from chat). Plain player actions only.
'use strict'
const vm = require('vm')

const FORBIDDEN = /\b(require|process|import|eval|Function|globalThis|constructor|__proto__|prototype|child_process)\b/

const HOSTILE = new Set(['zombie', 'skeleton', 'creeper', 'spider', 'cave_spider', 'enderman', 'witch', 'drowned',
  'husk', 'stray', 'phantom', 'pillager', 'vindicator', 'slime', 'magma_cube', 'blaze', 'ghast', 'hoglin',
  'piglin_brute', 'warden', 'silverfish', 'zombie_villager', 'evoker', 'ravager', 'guardian', 'bogged', 'breeze'])

function inventory (bot) {
  const out = {}
  for (const item of (bot.inventory && bot.inventory.items ? bot.inventory.items() : [])) {
    out[item.name] = (out[item.name] || 0) + item.count
  }
  return out
}

function snapshot (bot) {
  const p = bot.entity && bot.entity.position
  return { pos: p ? [round(p.x), round(p.y), round(p.z)] : null, inventory: inventory(bot),
    health: bot.health, food: bot.food }
}

function round (v) { return Math.round(v * 10) / 10 }

function nearby (bot, radius) {
  const me = bot.entity && bot.entity.position
  const hostiles = []
  const players = []
  if (!me) return { hostiles, players }
  for (const entity of Object.values(bot.entities || {})) {
    if (!entity || entity === bot.entity || !entity.position) continue
    const dist = entity.position.distanceTo(me)
    if (dist > radius) continue
    if (entity.type === 'player') players.push([entity.username || entity.name, round(dist)])
    else if (HOSTILE.has(entity.name)) hostiles.push([entity.name, round(dist)])
  }
  hostiles.sort((a, b) => a[1] - b[1])
  players.sort((a, b) => a[1] - b[1])
  return { hostiles: hostiles.slice(0, 8), players: players.slice(0, 8) }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// A person turns their view in a bell-shaped sweep (minimum jerk), longer for bigger turns, not in one frame.
async function humanLook (bot, yaw, pitch) {
  const y0 = bot.entity.yaw
  const p0 = bot.entity.pitch
  let dy = yaw - y0
  while (dy > Math.PI) dy -= 2 * Math.PI
  while (dy < -Math.PI) dy += 2 * Math.PI
  const angle = Math.hypot(dy, pitch - p0)
  const ms = 120 + 180 * Math.log2(1 + angle / 0.15)
  const steps = Math.max(2, Math.round(ms / 25))
  for (let i = 1; i <= steps; i++) {
    const t = i / steps
    const s = t * t * t * (10 - 15 * t + 6 * t * t)
    await bot.look(y0 + dy * s, p0 + (pitch - p0) * s, true)
    await sleep(ms / steps)
  }
}

async function lookAtPos (bot, pos) {
  const eye = bot.entity.position.offset(0, bot.entity.height || 1.62, 0)
  const dx = pos.x - eye.x
  const dy = pos.y - eye.y
  const dz = pos.z - eye.z
  const yaw = Math.atan2(-dx, -dz)
  const pitch = Math.atan2(dy, Math.sqrt(dx * dx + dz * dz))
  await humanLook(bot, yaw, pitch)
}

function compile (code) {
  if (FORBIDDEN.test(code)) throw new Error('refused: skill code uses a forbidden name')
  return vm.runInNewContext('(async function (bot, args, h) {\n' + code + '\n})', Object.create(null),
    { timeout: 1000 })
}

async function runSkill (bot, name, code, args, deps, timeoutMs, extra) {
  const compiled = {}
  const helpers = {
    goals: extra && extra.goals,
    sleep,
    look: (pos) => lookAtPos(bot, pos),
    log: (...parts) => { if (extra && extra.log) extra.log(parts.join(' ')) },
    skill: async (dep, depArgs) => {
      if (!(dep in deps)) throw new Error('unknown skill ' + dep)
      compiled[dep] = compiled[dep] || compile(deps[dep])
      return compiled[dep](bot, depArgs || {}, helpers)
    }
  }
  const fn = compile(code)
  let timer
  const timeout = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('timeout after ' + timeoutMs + ' ms')), timeoutMs)
  })
  try {
    return await Promise.race([fn(bot, args || {}, helpers), timeout])
  } finally {
    clearTimeout(timer)
  }
}

function install (bot, emit, options) {
  const opts = options || {}
  const hz = opts.hz || 10
  let current = ''
  let goals = opts.goals
  if (!goals) {
    try { goals = require('mineflayer-pathfinder').goals } catch (e) { goals = {} }
  }
  const timer = setInterval(() => {
    if (!bot.entity) return
    const near = nearby(bot, 24)
    emit({ type: 'state', t: Date.now(), health: bot.health, food: bot.food, pos: snapshot(bot).pos,
      yaw: round(bot.entity.yaw), pitch: round(bot.entity.pitch), hostiles: near.hostiles, players: near.players,
      inventory: inventory(bot), skill: current })
  }, Math.round(1000 / hz))
  if (bot.on) {
    bot.on('death', () => emit({ type: 'death' }))
    bot.on('respawn', () => emit({ type: 'respawn' }))
    bot.on('end', () => clearInterval(timer))
  }

  return async function handle (cmd) {
    if (cmd.cmd === 'stop_skill') {
      if (bot.pathfinder) bot.pathfinder.setGoal(null)
      if (bot.clearControlStates) bot.clearControlStates()
      return true
    }
    if (cmd.cmd !== 'run_skill') return false
    const before = snapshot(bot)
    const started = Date.now()
    current = cmd.name
    let ok = true
    let error = ''
    try {
      await runSkill(bot, cmd.name, String(cmd.code || ''), cmd.args, cmd.deps || {}, cmd.timeout_ms || 60000,
        { goals, log: opts.log })
    } catch (err) {
      ok = false
      error = String(err && err.message).slice(0, 300)
      if (bot.pathfinder) bot.pathfinder.setGoal(null)
    }
    current = ''
    emit({ type: 'skill_result', id: cmd.id, name: cmd.name, ok, error, ms: Date.now() - started, before,
      after: snapshot(bot) })
    return true
  }
}

module.exports = { install, runSkill, snapshot, nearby, compile, FORBIDDEN }
