// @vitest-environment jsdom
import {describe,it,expect} from 'vitest'
import {canIdentify} from './MusicRecognition'

const status={
 selected:true,file:'sample.wav',duration_seconds:12,sha256:'a'.repeat(64),
 audd_configured:true,acoustid_configured:true,fpcalc_selected:true,busy:false,
}
const consent={upload:false,billing:false,fingerprint:false,noncommercial:false,mic:false}

describe('explicit owner consent for music identification',()=>{
 it('requires both audio-upload and billing acknowledgements',()=>{
  expect(canIdentify(status,'audd','file',consent,12,true)).toBe(false)
  expect(canIdentify(status,'audd','file',{...consent,upload:true},12,true)).toBe(false)
  expect(canIdentify(status,'audd','file',{...consent,upload:true,billing:true},12,true)).toBe(true)
 })
 it('requires noncommercial license and fingerprint permission separately',()=>{
  expect(canIdentify(status,'acoustid','file',{...consent,fingerprint:true},30,true)).toBe(false)
  expect(canIdentify(status,'acoustid','file',{...consent,fingerprint:true,noncommercial:true},30,false)).toBe(false)
  expect(canIdentify(status,'acoustid','file',{...consent,fingerprint:true,noncommercial:true},30,true)).toBe(true)
 })
 it('rejects absent audio, absent provider, wrong duration and a busy model',()=>{
  const approved={...consent,upload:true,billing:true}
  expect(canIdentify({...status,selected:false},'audd','file',approved,12,true)).toBe(false)
  expect(canIdentify({...status,audd_configured:false},'audd','file',approved,12,true)).toBe(false)
  expect(canIdentify({...status,busy:true},'audd','file',approved,12,true)).toBe(false)
  expect(canIdentify(status,'audd','file',approved,30,true)).toBe(false)
  expect(canIdentify(status,'audd','file',approved,2,true)).toBe(false)
  expect(canIdentify(status,'audd','file',approved,Number.NaN,true)).toBe(false)
 })
 it('mic requires a fresh explicit microphone acknowledgment',()=>{
  const approved={...consent,upload:true,billing:true}
  expect(canIdentify({...status,selected:false},'audd','mic',approved,12,true)).toBe(false)
  expect(canIdentify({...status,selected:false},'audd','mic',{...approved,mic:true},12,true)).toBe(true)
 })
})
