import {useEffect, useRef, useState} from 'react'
import type {KeyboardEvent as ReactKeyboardEvent, ReactNode, RefObject} from 'react'
import {AnimatePresence, motion} from 'motion/react'
import {ArrowRight, ArrowUp, BookOpen, Check, ChevronDown, File as FileIcon, Globe, ImagePlus, Mic, MonitorUp, Paperclip, Plus, Square, Users, X} from 'lucide-react'
import {VoiceCallButton} from './VoiceCall'
import {MusicRecognitionButton,SongLookupRow,type SongLookup} from './MusicRecognition'
import type {Connection} from './connection'
import {menuIn} from './motion'
import {useMotionVariants,useStarReducedMotion} from './MotionPolicy'
import {COUNTER_FROM,PROMPT_LIMITS,overLimitMessage,promptKind,promptLength} from './promptLimits'

export type ChatMode = 'fast' | 'auto' | 'agent'
/** A capability that is either usable now or says exactly why it is not. */
export type Availability = {ok: boolean; reason?: string}

const MODES: Array<{id: ChatMode; label: string; hint: string}> = [
  {id: 'fast', label: 'Fast', hint: 'Quick answer. Can read and calculate attached files.'},
  {id: 'auto', label: 'Auto', hint: 'STAR picks the route from your request.'},
  {id: 'agent', label: 'Agent', hint: 'Plans, uses permitted tools, then checks its work. Slower.'},
]

const fileName = (path: string) => path.split(/[\\/]/).pop() || path

/** Close a floating layer on outside press or Escape, and hand focus back to its trigger. */
export function useDismiss(open: boolean, close: () => void, wrap: RefObject<HTMLElement | null>, trigger: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) close()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      close()
      trigger.current?.focus()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open, close, wrap, trigger])
}

/** Open a floating layer upward unless there is not enough room above it (the composer sits mid-page when a chat is empty). */
function sideFor(trigger: HTMLElement | null, needed: number): 'above' | 'below' {
  if (!trigger) return 'above'
  const box = trigger.getBoundingClientRect()
  const above = box.top - (trigger.closest('.thread')?.getBoundingClientRect().top ?? 0)
  const below = window.innerHeight - box.bottom
  return above < needed && below > above ? 'below' : 'above'
}

function ModeControl({value, onChange, disabled, onDone}: {value: ChatMode; onChange: (mode: ChatMode) => void; disabled: boolean; onDone?: () => void}) {
  const onKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const index = MODES.findIndex(mode => mode.id === value)
    const next = MODES[(index + step + MODES.length) % MODES.length]
    onChange(next.id)
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-mode="${next.id}"]`)?.focus()
  }
  return (
    <div className="cmp-modes" role="radiogroup" aria-label="How STAR should work" onKeyDown={onKey}>
      {MODES.map(mode => (
        <button
          key={mode.id}
          type="button"
          role="radio"
          data-mode={mode.id}
          aria-checked={value === mode.id}
          aria-label={mode.label}
          aria-describedby={'cmp-mode-hint-' + mode.id}
          tabIndex={value === mode.id ? 0 : -1}
          className={'cmp-mode' + (value === mode.id ? ' is-on' : '')}
          disabled={disabled}
          onClick={() => {
            onChange(mode.id)
            onDone?.()
          }}
        >
          <span className="cmp-mode-text">
            <span className="cmp-mode-label">{mode.label}</span>
            <small id={'cmp-mode-hint-' + mode.id}>{mode.hint}</small>
          </span>
          {value === mode.id && <Check size={15} className="cmp-mode-check" aria-hidden="true" />}
        </button>
      ))}
    </div>
  )
}

function MenuItem({icon, label, hint, checked, availability, onSelect}: {icon: ReactNode; label: string; hint?: string; checked?: boolean; availability?: Availability; onSelect: () => void}) {
  const blocked = availability && !availability.ok
  return (
    <button
      type="button"
      role={checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
      aria-checked={checked === undefined ? undefined : checked}
      aria-disabled={blocked || undefined}
      className={'cmp-menu-item' + (blocked ? ' is-blocked' : '')}
      onClick={() => {
        if (!blocked) onSelect()
      }}
    >
      <span className="cmp-menu-icon">{icon}</span>
      <span className="cmp-menu-text">{label}</span>
      {checked ? <Check size={15} className="cmp-menu-check" aria-hidden="true" /> : (blocked ? availability?.reason : hint) && <small title={blocked ? availability?.reason : hint}>{blocked ? availability?.reason : hint}</small>}
    </button>
  )
}

export type ComposerProps = {
  inputRef: RefObject<HTMLTextAreaElement | null>
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  busy: boolean
  stopping: boolean
  files: string[]
  onRemoveFile: (index: number) => void
  onAttach: () => void
  onTranscribe: () => void
  mode: ChatMode
  onMode: (mode: ChatMode) => void
  imageMode: boolean
  onImageMode: (on: boolean) => void
  imageReady: boolean
  onImageSetup: () => void
  imageSize: string
  onImageSize: (size: string) => void
  teamMode: boolean
  onTeamMode: (on: boolean) => void
  team: Availability
  research: boolean
  onResearch: (on: boolean) => void
  web: Availability
  githubSource: boolean
  onGithubSource: (on: boolean) => void
  connection: Connection
  onOpenConnection: () => void
  /** The "Use my PC" switch (UsePcSwitch), shown beside the model chip when STAR Server is the provider. */
  usePc?: ReactNode
  /** "Look at my screen": asks first (ScreenConsent), then attaches one screenshot. Absent where it cannot work. */
  onLookAtScreen?: () => void
  /** Small thumbnails for attachments that have one (a screenshot), keyed by path. */
  previews?: Record<string, string>
  /** Song recognition, present only while Settings > Song recognition is on: the dialog button and the
   *  per-message approval for an attached WAV. */
  song?: {lookup: SongLookup | null; onLookup: (value: SongLookup | null) => void}
}

/** The sizes the host offers (star/image_gen.py SIZES). An attached picture keeps its own shape; Draft makes it small and fast. */
export const IMAGE_SIZES = [
  {id: 'square', label: 'Square 1024'},
  {id: 'wide', label: 'Wide 1280 x 720'},
  {id: 'tall', label: 'Tall 720 x 1280'},
  {id: 'draft', label: 'Draft 512 (fastest)'},
]

/** The one place a message is written: text, attachments, how STAR should work, and what it will talk to. */
export function Composer(props: ComposerProps) {
  const reducedMotion = useStarReducedMotion()
  const menuVariants = useMotionVariants(menuIn)
  const {inputRef, value, onChange, onSend, onStop, busy, stopping, files, mode, imageMode, teamMode, research, githubSource, connection} = props
  const [composerMenu, setComposerMenu] = useState(false)
  const [moreTools, setMoreTools] = useState(false)
  const [modeOpen, setModeOpen] = useState(false)
  const [statusOpen, setStatusOpen] = useState(false)
  const [side, setSide] = useState<'above' | 'below' | 'aside'>('above')
  const menuWrap = useRef<HTMLDivElement>(null)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const statusWrap = useRef<HTMLDivElement>(null)
  const statusTrigger = useRef<HTMLButtonElement>(null)
  const modeWrap = useRef<HTMLDivElement>(null)
  const modeTrigger = useRef<HTMLButtonElement>(null)
  useDismiss(composerMenu, () => setComposerMenu(false), menuWrap, menuTrigger)
  useDismiss(modeOpen, () => setModeOpen(false), modeWrap, modeTrigger)
  // The extra tools fold away again each time the menu closes, so the menu always opens short.
  useEffect(() => {
    if (!composerMenu) setMoreTools(false)
  }, [composerMenu])
  // The chosen mode takes focus when the picker opens, so arrow keys work at once.
  useEffect(() => {
    if (modeOpen) modeWrap.current?.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="true"]')?.focus()
  }, [modeOpen])
  useDismiss(statusOpen, () => setStatusOpen(false), statusWrap, statusTrigger)

  // Grow with the text up to a comfortable limit, then scroll inside.
  useEffect(() => {
    const node = inputRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = Math.min(node.scrollHeight, 208) + 'px'
  }, [value, inputRef, files.length, imageMode])

  // Arrow keys walk the menu; the first item takes focus when it opens.
  useEffect(() => {
    if (composerMenu) menuWrap.current?.querySelector<HTMLButtonElement>('[role^="menuitem"]')?.focus()
  }, [composerMenu])
  const onMenuKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') return
    event.preventDefault()
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]'))
    const at = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }
  const pick = (action: () => void) => {
    setComposerMenu(false)
    action()
  }
  // The host refuses a prompt over its limit (promptLimits.ts); say so here instead of sending a turn that fails.
  const kind = promptKind(imageMode, teamMode)
  const limit = PROMPT_LIMITS[kind]
  const length = promptLength(value)
  const tooLong = overLimitMessage(value, kind)
  const showCount = length >= limit * COUNTER_FROM
  const canSend = length > 0 && !busy && !tooLong
  const special = imageMode || teamMode

  return (
    <div className={'cmp' + (busy ? ' is-busy' : '')} role="group" aria-label="Message STAR">
      {files.length > 0 && (
        <ul className="cmp-files" aria-label="Attachments">
          {files.map((path, index) => (
            <li key={path} className={'cmp-file' + (props.previews?.[path] ? ' has-preview' : '')}>
              {props.previews?.[path] ? <img className="cmp-file-thumb" src={props.previews[path]} alt="" /> : <FileIcon size={14} aria-hidden="true" />}
              <span title={fileName(path)}>{fileName(path)}</span>
              <button type="button" aria-label={'Remove ' + fileName(path)} onClick={() => props.onRemoveFile(index)}>
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {props.song && !special && <SongLookupRow files={files} lookup={props.song.lookup} onLookup={props.song.onLookup} disabled={busy} />}
      <label className="sr-only" htmlFor="star-prompt">
        Message STAR
      </label>
      <textarea
        id="star-prompt"
        ref={inputRef}
        className="cmp-input"
        rows={1}
        placeholder={imageMode ? (files.length > 1 ? 'Describe what should appear in the masked area' : files.length === 1 ? 'Describe how to change the attached picture' : 'Describe the image you want to create') : teamMode ? 'Give the team an objective' : 'Message STAR'}
        value={value}
        aria-invalid={tooLong ? true : undefined}
        aria-describedby={showCount ? 'cmp-limit' : undefined}
        onChange={event => onChange(event.target.value)}
        onKeyDown={event => {
          // Enter sends; Shift+Enter adds a line; never send in the middle of IME composition.
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            if (canSend) onSend()
          }
        }}
      />
      {showCount && (
        <p id="cmp-limit" className={'cmp-limit' + (tooLong ? ' is-over' : '')} role={tooLong ? 'alert' : undefined}>
          <span className="cmp-limit-count">{length.toLocaleString('en-US')} / {limit.toLocaleString('en-US')}</span>
          {tooLong && <span className="cmp-limit-note">{tooLong}</span>}
        </p>
      )}
      <div className="cmp-bar">
        <div className="cmp-bar-left">
          <div className="cmp-pop-wrap" ref={menuWrap}>
            <button
              ref={menuTrigger}
              type="button"
              className={'cmp-icon-button' + (composerMenu ? ' is-open' : '')}
              title="Add files and tools"
              aria-label="Add files and tools"
              aria-haspopup="menu"
              aria-expanded={composerMenu}
              disabled={busy}
              onClick={() => {
                setSide(sideFor(menuTrigger.current, 264))
                setStatusOpen(false)
                setModeOpen(false)
                setComposerMenu(open => !open)
              }}
            >
              <Plus size={18} />
            </button>
            <AnimatePresence>
              {composerMenu && (
                <motion.div className="composer-menu cmp-menu" data-side={side} role="menu" aria-label="Add to this message" variants={menuVariants} initial={reducedMotion?false:'hidden'} animate="shown" exit="exit" onKeyDown={onMenuKey}>
                  <MenuItem icon={<Paperclip size={16} />} label="Add photos and files" availability={teamMode ? {ok: false, reason: 'Team runs are text only'} : undefined} onSelect={() => pick(props.onAttach)} />
                  {props.onLookAtScreen && <MenuItem icon={<MonitorUp size={16} />} label="Look at my screen" hint="Asks first" availability={teamMode ? {ok: false, reason: 'Team runs are text only'} : undefined} onSelect={() => pick(props.onLookAtScreen!)} />}
                  <MenuItem icon={<ImagePlus size={16} />} label="Create image" checked={imageMode} onSelect={() => pick(() => props.onImageMode(!imageMode))} />
                  <MenuItem icon={<Globe size={16} />} label="Search the web" checked={research} availability={imageMode ? {ok: false, reason: 'Not with images'} : props.web} onSelect={() => pick(() => props.onResearch(!research))} />
                  <div className="cmp-menu-rule" role="separator" />
                  <button type="button" role="menuitem" className="cmp-menu-item cmp-menu-more" aria-expanded={moreTools} onClick={() => setMoreTools(open => !open)}>
                    <span className="cmp-menu-icon"><ChevronDown size={16} className={moreTools ? 'is-open' : undefined} /></span>
                    <span className="cmp-menu-text">More</span>
                  </button>
                  {moreTools && <>
                    <MenuItem icon={<Mic size={16} />} label="Transcribe audio" hint="Adds the transcript" onSelect={() => pick(props.onTranscribe)} />
                    <MenuItem icon={<Users size={16} />} label="Use a team" hint="4 read-only stages" checked={teamMode} availability={imageMode ? {ok: false, reason: 'Not with images'} : props.team} onSelect={() => pick(() => props.onTeamMode(!teamMode))} />
                    <MenuItem icon={<BookOpen size={16} />} label="Read STAR source" hint="Read only" checked={githubSource} availability={special ? {ok: false, reason: 'Not in this mode'} : mode === 'agent' ? undefined : {ok: false, reason: 'Agent mode only'}} onSelect={() => pick(() => props.onGithubSource(!githubSource))} />
                  </>}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          {!special && (
            <div className="cmp-pop-wrap" ref={modeWrap}>
              <button ref={modeTrigger} type="button" className={'cmp-mode-trigger' + (modeOpen ? ' is-open' : '')} aria-haspopup="dialog" aria-expanded={modeOpen} aria-label={'Mode: ' + (MODES.find(item => item.id === mode)?.label ?? mode)} title="How STAR should work" disabled={busy}
                onClick={() => {
                  setSide(sideFor(modeTrigger.current, 200))
                  setComposerMenu(false)
                  setStatusOpen(false)
                  setModeOpen(open => !open)
                }}>
                {MODES.find(item => item.id === mode)?.label}
                <ChevronDown size={13} aria-hidden="true" />
              </button>
              <AnimatePresence>
                {modeOpen && (
                  <motion.div className="cmp-mode-pop" data-side={side} role="dialog" aria-label="Choose how STAR works" variants={menuVariants} initial={reducedMotion?false:'hidden'} animate="shown" exit="exit">
                    <ModeControl value={mode} onChange={props.onMode} disabled={busy} onDone={() => {
                      setModeOpen(false)
                      modeTrigger.current?.focus()
                    }} />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
          {imageMode && (
            <button type="button" className="composer-image-chip cmp-chip" aria-label="Stop creating an image" disabled={busy} onClick={() => props.onImageMode(false)}>
              <ImagePlus size={14} aria-hidden="true" /> Image <X size={13} aria-hidden="true" />
            </button>
          )}
          {imageMode && (
            <select className="cmp-size" aria-label="Image size" value={props.imageSize} disabled={busy} onChange={event => props.onImageSize(event.target.value)}>
              {IMAGE_SIZES.map(size => <option key={size.id} value={size.id}>{size.label}</option>)}
            </select>
          )}
          {imageMode && files.length < 2 && (
            <button type="button" className="cmp-link" disabled={busy} onClick={props.onAttach}>
              {files.length === 0 ? 'Attach a picture to edit it' : 'Add a mask (white = the part to change)'}
            </button>
          )}
          {imageMode && !props.imageReady && (
            <button type="button" className="cmp-link" onClick={props.onImageSetup}>
              Set up image creation <ArrowRight size={13} aria-hidden="true" />
            </button>
          )}
          {teamMode && (
            <button type="button" className="cmp-chip" aria-label="Stop using a team" disabled={busy} onClick={() => props.onTeamMode(false)}>
              <Users size={14} aria-hidden="true" /> Team <X size={13} aria-hidden="true" />
            </button>
          )}
          {research && !imageMode && (
            <button type="button" className="cmp-chip" aria-label="Stop searching the web" disabled={busy} onClick={() => props.onResearch(false)}>
              <Globe size={14} aria-hidden="true" /> Web <X size={13} aria-hidden="true" />
            </button>
          )}
          {githubSource && mode === 'agent' && !special && (
            <button type="button" className="cmp-chip" aria-label="Stop reading STAR source" disabled={busy} onClick={() => props.onGithubSource(false)}>
              <BookOpen size={14} aria-hidden="true" /> Source <X size={13} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="cmp-bar-right">
          {props.usePc}
          <div className="cmp-pop-wrap" ref={statusWrap}>
            <button ref={statusTrigger} type="button" className={'cmp-status is-' + connection.tone} aria-haspopup="dialog" aria-expanded={statusOpen} title={`${connection.label} — ${connection.state}`} onClick={() => {
              setSide(statusTrigger.current?.closest('.thread.is-empty') ? 'aside' : sideFor(statusTrigger.current, 260))
              setComposerMenu(false)
              setModeOpen(false)
              setStatusOpen(open => !open)
            }}>
              <span className="cmp-dot" aria-hidden="true" />
              <span className="cmp-status-label">{connection.label}</span>
              <span className="cmp-status-state">{connection.state}</span>
              <ChevronDown size={13} aria-hidden="true" />
            </button>
            <AnimatePresence>
              {statusOpen && (
                <motion.div className="cmp-status-pop" data-side={side} role="dialog" aria-label="Model connection" variants={menuVariants} initial={reducedMotion?false:'hidden'} animate="shown" exit="exit">
                  <p className={'cmp-status-head is-' + connection.tone}>
                    <span className="cmp-dot" aria-hidden="true" />
                    {connection.state}
                  </p>
                  <p className="cmp-status-note">{connection.note}</p>
                  <dl>
                    <dt>Provider</dt>
                    <dd>{connection.provider}</dd>
                    <dt>Model</dt>
                    <dd>{connection.model || 'None selected'}</dd>
                    {connection.answeredBy && (
                      <>
                        <dt>Answered by</dt>
                        <dd>{connection.answeredBy}</dd>
                      </>
                    )}
                    {connection.endpoint && (
                      <>
                        <dt>Address</dt>
                        <dd>{connection.endpoint}</dd>
                      </>
                    )}
                  </dl>
                  <button
                    type="button"
                    className="cmp-link"
                    onClick={() => {
                      setStatusOpen(false)
                      props.onOpenConnection()
                    }}
                  >
                    Model &amp; connection <ArrowRight size={13} aria-hidden="true" />
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          {props.song && <MusicRecognitionButton disabled={busy} />}
          <VoiceCallButton disabled={busy} />
          {busy ? (
            <button type="button" className="cmp-send is-stop" title="Stop" aria-label="Stop response" disabled={stopping} onClick={event => {
              // Send turns into Stop under the pointer, so the second click of a double-click lands here.
              // `detail` is the click count: only a deliberate single click (or the keyboard, 0) stops the turn.
              if (event.detail > 1) return
              onStop()
              inputRef.current?.focus() // the Stop button is about to disappear; keep focus somewhere useful
            }}>
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button type="button" className="cmp-send" title="Send (Enter)" aria-label="Send message" disabled={!canSend} onClick={onSend}>
              <ArrowUp size={18} strokeWidth={2.2} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
