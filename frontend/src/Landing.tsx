/**
 * The public STAR website. It never talks to the native Qt bridge and never reads local data:
 * everything on the page is editorial content, captures of the interface, or public GitHub release data.
 */
import {Suspense,useEffect,useMemo,useRef,useState} from 'react'
import {ArrowDown,ArrowUpRight,Menu,X} from 'lucide-react'
import {StarLockup,StarMark} from './SiteBrand'
import {SiteMascotHero,SiteMascotFooter} from './SiteMascot'
import {SiteFeatures} from './SiteFeatures'
import {SiteLearning} from './SiteLearning'
import {SiteBrain} from './SiteBrain'
import {SiteHonest} from './SiteHonest'
import {SiteDownload} from './SiteDownload'
import {LINKS,SOURCE_VERSION,currentRelease,formatDate,releaseFiles} from './siteContent'
import {compareVersions,fetchLatestStableRelease,latestStable} from './githubPublic'
import type {ReleaseInfo} from './githubPublic'
import {builtSnapshot,delay,staticMode,useActiveSection,useHeaderState,useReveal} from './siteHooks'
import './site.css'

const sections=[
 {id:'features',label:'Features'},
 {id:'learning',label:'How it learns'},
 {id:'brain',label:'Brain map'},
 {id:'honest',label:'Honest numbers'}
] as const
const sectionIds=sections.map(section=>section.id)

export function Landing(){
 const root=useRef<HTMLDivElement>(null)
 const menuButton=useRef<HTMLButtonElement>(null)
 const [menu,setMenu]=useState(false)
 const [liveRelease,setLiveRelease]=useState<ReleaseInfo|null>(null)
 // The build-time snapshot gives the prerendered page a real release; GitHub's latest-release answer replaces it.
 useEffect(()=>{
  if(staticMode())return
  const controller=new AbortController()
  fetchLatestStableRelease(controller.signal).then(release=>{if(release)setLiveRelease(release)}).catch(()=>undefined)
  return ()=>controller.abort()
 },[])
 const latest=useMemo(()=>currentRelease(liveRelease,latestStable(builtSnapshot)),[liveRelease])
 const files=useMemo(()=>releaseFiles(latest),[latest])
 const header=useHeaderState(menu)
 const active=useActiveSection(sectionIds)
 // `?visualqa` freezes motion for screenshots. Read after mount so prerendered markup matches the first render.
 const [still,setStill]=useState(false)
 useEffect(()=>{setStill(staticMode())},[])
 useReveal(root)

 useEffect(()=>{
  if(!menu)return
  const onKey=(event:KeyboardEvent)=>{
   if(event.key==='Escape'){setMenu(false);menuButton.current?.focus()}
  }
  window.addEventListener('keydown',onKey)
  return ()=>window.removeEventListener('keydown',onKey)
 },[menu])

 const closeMenu=()=>setMenu(false)
 const sourceAhead=latest?compareVersions(SOURCE_VERSION,latest.tag)>0:false
 return <div className={'sw'+(still?' sw-still':'')} id="top" ref={root}>
  <a className="sw-skip" href="#main">Skip to content</a>

  <header className="sw-header" data-solid={header.solid||menu} data-hidden={header.hidden} data-past={header.past}>
   <div className="sw-wrap sw-header-row">
    <a className="sw-brand" href="#top" aria-label="STAR, back to top"><StarLockup size={26}/></a>
    <nav className="sw-nav" id="sw-nav" aria-label="Main" data-open={menu}>
     <ul>
      {sections.map(section=><li key={section.id}>
       <a href={'#'+section.id} aria-current={active===section.id?'true':undefined} onClick={closeMenu}>{section.label}</a>
      </li>)}
      <li className="sw-nav-out"><a href={LINKS.repo} target="_blank" rel="noopener noreferrer" onClick={closeMenu}>
       <ArrowUpRight size={16} aria-hidden="true"/> GitHub<span className="sw-sr"> (opens in a new tab)</span>
      </a></li>
     </ul>
    </nav>
    <div className="sw-header-actions">
     <a className="sw-btn sw-btn-primary sw-btn-compact" href="#download">Download</a>
     <button ref={menuButton} type="button" className="sw-menu-button" aria-label={menu?'Close menu':'Open menu'}
      aria-expanded={menu} aria-controls="sw-nav" onClick={()=>setMenu(open=>!open)}>
      {menu?<X size={20} aria-hidden="true"/>:<Menu size={20} aria-hidden="true"/>}
     </button>
    </div>
   </div>
  </header>

  <main id="main" tabIndex={-1}>
   <section className="sw-hero" aria-labelledby="sw-hero-title">
    <div className="sw-wrap sw-hero-grid">
     <div className="sw-hero-copy">
      <h1 id="sw-hero-title" className="sw-enter" style={delay(0)}>An AI that runs on machines you&nbsp;own.</h1>
      <p className="sw-lede sw-enter" style={delay(90)}>
       STAR is a chat app for Windows 11. It talks to a model on your PC or on your own server, helps you build
       Roblox games, makes pictures, searches the web, and practises at night to get better, with you deciding
       what it&nbsp;keeps.
      </p>
      <div className="sw-cta sw-enter" style={delay(170)}>
       <a className="sw-btn sw-btn-primary" href="#download"><ArrowDown size={18} aria-hidden="true"/> Download for Windows</a>
       <a className="sw-btn sw-btn-quiet" href="#features">See what is in 1.0</a>
      </div>
      <p className="sw-hero-meta sw-enter" style={delay(250)}>
       {!latest&&<>Release details are unavailable here. <a href={LINKS.latest} target="_blank" rel="noopener noreferrer">Check GitHub Releases</a>.</>}
       {latest&&!sourceAhead&&<>Free for Windows 11. <a href={latest.url} target="_blank" rel="noopener noreferrer">{latest.tag}</a>, published {formatDate(latest.publishedAt,'long')}.</>}
       {latest&&sourceAhead&&<>This page describes {SOURCE_VERSION}, which is not published yet. The download is {latest.tag}, published {formatDate(latest.publishedAt,'long')}.</>}
      </p>
     </div>
     <SiteMascotHero/>
    </div>
   </section>

   <section className="sw-story" aria-labelledby="sw-story-title">
    <div className="sw-wrap sw-story-grid">
     <h2 id="sw-story-title">Your model, your disk, your&nbsp;say.</h2>
     <div className="sw-story-text">
      <p>Most AI apps rent you a model in someone else's data centre. STAR goes the other way. The model runs on a PC
       or a server you own, your chats stay in a folder on your disk, and anything that can touch your files, your
       screen or Roblox Studio stays off until you switch it on.</p>
      <p>1.0 is the first release where the whole picture works together: a chat app that feels familiar, a server
       brain that needs no graphics card, tools for Roblox and design, and a learning loop you can inspect and undo.</p>
     </div>
    </div>
   </section>

   {/* Each boundary hydrates as its own task, so the prerendered page never blocks input for long. */}
   <Suspense><SiteFeatures latest={latest}/></Suspense>
   <Suspense><SiteLearning/></Suspense>
   <Suspense><SiteBrain/></Suspense>
   <Suspense><SiteHonest/></Suspense>
   <Suspense><SiteDownload latest={latest} files={files} releaseLive={liveRelease!==null} snapshotAt={builtSnapshot?.generatedAt??null}/></Suspense>
  </main>

  <footer className="sw-footer">
   <div className="sw-wrap sw-footer-grid">
    <div className="sw-footer-brand">
     <SiteMascotFooter/>
     <div>
      <span className="sw-footer-mark"><StarMark size={20}/><strong>STAR</strong></span>
      <p>An AI that runs on machines you own. Built in the open.</p>
      <p className="sw-fine">This site sets no cookies and runs no analytics. Release details come from GitHub's public API.</p>
     </div>
    </div>
    <nav aria-label="Product">
     <h2>Product</h2>
     <ul>
      <li><a href="#download">Download</a></li>
      <li><a href={LINKS.notes} target="_blank" rel="noopener noreferrer">1.0 release notes</a></li>
      <li><a href={LINKS.releases} target="_blank" rel="noopener noreferrer">All releases</a></li>
      <li><a href={LINKS.commits} target="_blank" rel="noopener noreferrer">Changelog</a></li>
     </ul>
    </nav>
    <nav aria-label="Documentation">
     <h2>Docs</h2>
     <ul>
      <li><a href={LINKS.readme} target="_blank" rel="noopener noreferrer">README</a></li>
      <li><a href={LINKS.start} target="_blank" rel="noopener noreferrer">Getting started</a></li>
      <li><a href={LINKS.security} target="_blank" rel="noopener noreferrer">Security and autonomy</a></li>
      <li><a href={LINKS.docs} target="_blank" rel="noopener noreferrer">All documents</a></li>
     </ul>
    </nav>
    <nav aria-label="Project">
     <h2>Project</h2>
     <ul>
      <li><a href={LINKS.repo} target="_blank" rel="noopener noreferrer">Source on GitHub</a></li>
      <li><a href={LINKS.pulls} target="_blank" rel="noopener noreferrer">Work in progress</a></li>
      <li><a href={LINKS.issues} target="_blank" rel="noopener noreferrer">Report a problem</a></li>
      <li><a href={LINKS.newIssue} target="_blank" rel="noopener noreferrer">Suggest an idea</a></li>
     </ul>
    </nav>
   </div>
   <div className="sw-wrap">
    <div className="sw-footer-base">
     <span>© 2026 STAR Intelligence</span>
     <span>No licence file has been published yet. Icons: Lucide (ISC).</span>
     <span>Site built from source v{SOURCE_VERSION}</span>
    </div>
   </div>
  </footer>
 </div>
}
