// @vitest-environment jsdom
import {useRef,useState} from 'react'
import {afterEach,describe,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {Composer} from './Composer'
import type {Connection} from './connection'
import {MotionPolicy} from './MotionPolicy'
import {readyToIdentify,songDisclosure,type SongLookup,type SongStatus} from './MusicRecognition'

afterEach(cleanup)
const connection:Connection={tone:'unverified',label:'This PC · demo',state:'Not checked',provider:'This PC',model:'demo',endpoint:'',note:''}

function Harness({files,song}:{files:string[];song?:{lookup:SongLookup|null;onLookup:(value:SongLookup|null)=>void}}){
 const inputRef=useRef<HTMLTextAreaElement>(null)
 const [value,setValue]=useState('')
 const noop=()=>{}
 return <MotionPolicy reduced><Composer inputRef={inputRef} value={value} onChange={setValue} onSend={noop} onStop={noop} busy={false} stopping={false}
  files={files} onRemoveFile={noop} onAttach={noop} onTranscribe={noop} mode="auto" onMode={noop} imageMode={false} onImageMode={noop}
  imageReady={false} onImageSetup={noop} imageSize="square" onImageSize={noop} teamMode={false} onTeamMode={noop} team={{ok:true}}
  research={false} onResearch={noop} web={{ok:true}} githubSource={false} onGithubSource={noop} connection={connection} onOpenConnection={noop}
  song={song}/></MotionPolicy>
}

describe('song recognition in the composer',()=>{
 it('shows nothing while the setting is off, even with a WAV attached',()=>{
  render(<Harness files={['C:/clips/song.wav']}/>)
  expect(screen.queryByText(/Identify the song/)).toBeNull()
 })
 it('approves one lookup of the attached WAV, saying what goes where, and a catalog change withdraws it',()=>{
  const onLookup=vi.fn()
  const {rerender}=render(<Harness files={['C:/clips/song.wav']} song={{lookup:null,onLookup}}/>)
  const box=screen.getByRole('checkbox',{name:/Identify the song/})
  expect(box.closest('label')?.textContent).toContain('AudD (api.audd.io)')
  fireEvent.click(box)
  expect(onLookup).toHaveBeenLastCalledWith({file:'C:/clips/song.wav',provider:'audd'})
  rerender(<Harness files={['C:/clips/song.wav']} song={{lookup:{file:'C:/clips/song.wav',provider:'audd'},onLookup}}/>)
  fireEvent.change(screen.getByRole('combobox',{name:'Song catalog'}),{target:{value:'acoustid'}})
  expect(onLookup).toHaveBeenLastCalledWith(null)
  expect(screen.getByRole('checkbox',{name:/Identify the song/}).closest('label')?.textContent).toContain('fingerprint')
 })
 it('has no song line without a WAV attachment',()=>{
  render(<Harness files={['C:/notes.txt']} song={{lookup:null,onLookup:vi.fn()}}/>)
  expect(screen.queryByText(/Identify the song/)).toBeNull()
 })
})

describe('the Identify-a-song dialog sends only with consent and a saved key',()=>{
 const status:SongStatus={enabled:true,file:'song.wav',duration_seconds:20,busy:false,audd_key:true,acoustid_key:false,fpcalc_found:false}
 it('needs the consent tick, a file or the recording tick, a key and a valid length',()=>{
  expect(readyToIdentify(status,'audd','file',true,false,12)).toBe(true)
  expect(readyToIdentify(status,'audd','file',false,false,12)).toBe(false)
  expect(readyToIdentify({...status,file:''},'audd','file',true,false,12)).toBe(false)
  expect(readyToIdentify({...status,file:''},'audd','mic',true,false,12)).toBe(false)
  expect(readyToIdentify({...status,file:''},'audd','mic',true,true,12)).toBe(true)
  expect(readyToIdentify(status,'acoustid','file',true,false,12)).toBe(false)
  expect(readyToIdentify(status,'audd','file',true,false,13)).toBe(false)
  expect(readyToIdentify({...status,enabled:false},'audd','file',true,false,12)).toBe(false)
  expect(readyToIdentify({...status,busy:true},'audd','file',true,false,12)).toBe(false)
 })
 it('names the third party and what it receives',()=>{
  expect(songDisclosure('audd',8)).toMatch(/Uploads a 8 s clip .* AudD/)
  expect(songDisclosure('acoustid')).toMatch(/fingerprint .* AcoustID .* stays on this PC/)
 })
})
