import {describe,expect,it} from 'vitest'
import {chatImageRequest,endsWithPicture,imageIntent} from './imageIntent'

const picture={role:'assistant' as const,image:'data:image/webp;base64,AA=='}
const answer={role:'assistant' as const}
const asked={role:'user' as const}
const failed={role:'event' as const}

describe('image intent',()=>{
 it.each([
  ['Generate an image of a dog','a dog'],
  ['draw a picture of a cat','a cat'],
  ['Please create a picture showing a red car','a red car'],
  ['make me an image of a castle','a castle'],
  ['create a logo for my game','a logo for my game'],
  ['render a wallpaper of a forest','a wallpaper of a forest'],
  ['draw a cat','a cat'],
  ['Generate me a real cow with no weird legs','a real cow with no weird legs'],
  ['create me a dragon with three heads','a dragon with three heads'],
  ['Draw me a cat.','a cat'],
  ['please draw a castle','a castle'],
  ['paint a sunset','a sunset'],
  ['sketch me a house on a hill','a house on a hill'],
  ['make me a logo','a logo'],
  ['Make me a logo for my game','a logo for my game'],
  ['show me an image of a castle','a castle'],
  ['Show me a picture of a sunset over the sea','a sunset over the sea'],
  ['I need a poster of a robot','a poster of a robot'],
  ["I'd like a picture of my dog",'my dog'],
  ['I want an image of a dragon.','a dragon'],
  ['Can you make an image of a robot?','a robot'],
  ['Could you please draw a cat?','a cat'],
  ['Can you create images of cats?','cats'],
 ])('routes %s as a new picture',(input,prompt)=>expect(imageIntent(input)).toEqual({prompt,followup:false}))

 it.each([
  'how do I generate an ImageLabel in Roblox','draw a UI layout in code','explain image formats',
  'write python code to create an image','make a Luau script that draws a sprite','create an icon component in react',
  'what is a good logo size?','Generate','',
  // questions about what STAR can do, and other uses of the same words
  'Can you create images?','Can you create an image?','Can you make a logo?','Can you draw?','Do you generate images?',
  'draw a conclusion from this','draw attention to the second point','draw a line under the total','draw a diagram of the architecture',
  'draw a flowchart for the login','show me the picture frame code','I need a picture frame','I need help with a logo',
  'make me a table of the results','generate me a list of names','Create me a plan for the week','make me a script for the intro','show me a list of images',
 ])('leaves %j in chat',input=>expect(imageIntent(input)).toBeNull())

 it('keeps an order that is only the command whole',()=>expect(imageIntent('Generate an image')).toEqual({prompt:'an image',followup:false}))

 it('only edits an attached picture when there is one',()=>{
  expect(imageIntent('edit this picture')).toBeNull()
  expect(imageIntent('edit this picture',{hasImage:true})).toEqual({prompt:'edit this picture',followup:false})
 })

 it('treats "make it brown" as a change to the last picture only when the newest answer was a picture',()=>{
  expect(imageIntent('make it brown')).toBeNull()
  expect(imageIntent('make it brown',{hasPreviousImage:true})).toEqual({prompt:'make it brown',followup:true})
 })

 it('never calls an explicit new picture a follow-up, even right after a picture',()=>{
  expect(imageIntent('Generate an image of a cat',{hasPreviousImage:true})).toEqual({prompt:'a cat',followup:false})
  expect(imageIntent('create a logo for my game',{hasPreviousImage:true})?.followup).toBe(false)
 })
})

describe('what "it" refers to',()=>{
 it('is a picture only when the newest answer is one',()=>{
  expect(endsWithPicture([asked,picture])).toBe(true)
  expect(endsWithPicture([picture,asked,answer])).toBe(false)
  expect(endsWithPicture([])).toBe(false)
 })
 it('ignores failure notices, and looks past the question being retried',()=>{
  expect(endsWithPicture([picture,asked,failed])).toBe(false)
  expect(endsWithPicture([picture,asked,failed],true)).toBe(true)
  expect(endsWithPicture([picture,asked,answer,asked,failed],true)).toBe(false)
 })
})

describe('chat requests with attachments',()=>{
 it('does not turn an old picture into the subject of an unrelated follow-up',()=>{
  expect(chatImageRequest('Add a comment to the function',[],[picture,asked,answer])).toBeNull()
  expect(chatImageRequest('Make it shorter',[],[picture,asked,answer])).toBeNull()
  expect(chatImageRequest('Make it shorter',[],[asked,picture])).toEqual({prompt:'Make it shorter',followup:true})
 })
 it('uses one attached picture as the one to change',()=>{
  expect(chatImageRequest('Generate an image of this as a watercolor',['C:/x/photo.PNG'],[])).toEqual({prompt:'this as a watercolor',followup:false})
  expect(chatImageRequest('edit this picture',['C:/x/photo.jpg'],[])).toEqual({prompt:'edit this picture',followup:false})
 })
 it('leaves the message in chat for a document, a video or more than one file',()=>{
  expect(chatImageRequest('Generate an image of a dog',['C:/x/notes.pdf'],[])).toBeNull()
  expect(chatImageRequest('Generate an image of a dog',['C:/x/clip.mp4'],[])).toBeNull()
  expect(chatImageRequest('Generate an image of a dog',['C:/x/a.png','C:/x/b.png'],[])).toBeNull()
 })
})
