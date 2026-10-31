/**
 * Which chat messages are plain requests for a picture. Deliberately an order and not a guess: a message goes to
 * the picture engine only when it starts as one ("generate an image of ...", "draw a cat", "make me a logo for ...",
 * "show me a picture of ...", "I need a poster of ..."), never when it is a question about what STAR can do
 * ("Can you create images?"), mentions code or a diagram, or arrives with files that are not one picture.
 */
import type {ChatMessage} from './types'

export type ImageIntent={
  /** What the picture model gets. */
  prompt:string
  /** True when the request changes the picture STAR just showed ("make it brown"), not a new one. */
  followup:boolean
}

const TECHNICAL=/```|\b(?:code|script|luau|python|typescript|javascript|html|css|json|sql|regex|react|api|function|module|component|plugin|programmatically|in code|ImageLabel|ImageButton|Decal|SurfaceAppearance|diagram|flowchart|chart|graph|ascii|mermaid|uml|spreadsheet|schema|database|algorithm|repository|stack trace)\b/i
const NOUN=String.raw`(?:image|picture|photo|photograph|drawing|illustration|logo|icon|wallpaper|sprite|texture|artwork|poster|portrait|graphic|sketch|render)`
// "an image", "a logo", and the plural only when it is followed by what to show ("images of cats").
const ART=String.raw`(?=(?:an?\s+)?${NOUN}\b|${NOUN}s\s+(?:of|showing|depicting)\b)`
const LEAD=String.raw`^(?:(?:please|kindly|can you|could you|would you|will you|i want you to|i need you to|i would like you to|i'd like you to|go ahead and)\s+){0,2}`
// What the verb "draw" is also used for, none of it pictures ("draw a conclusion", "draw a line under it").
const NOT_A_PICTURE=String.raw`(?:conclusion|comparison|parallel|distinction|analogy|line|lesson|breath|plan|schedule|list|summary|table|timeline|outline)`
const COMMAND=new RegExp(String.raw`${LEAD}(?:generate|draw|make|create|render|paint|design|produce|sketch|illustrate|doodle)\s+(?:me\s+)?${ART}`,'i')
// "draw a cat", "paint a sunset", "sketch me a house": the thing itself is the subject, no picture word needed.
const DRAW=new RegExp(String.raw`${LEAD}(?:draw|paint|sketch|illustrate|doodle)\s+(?:me\s+)?(?=(?:an?|some)\s+(?!${NOT_A_PICTURE}\b)[a-z])`,'i')
// "generate me a real cow", "make me a dragon with three heads": the thing itself is the subject. Only with "me" and a
// thing, never text or code deliverables ("make me a list/plan/script/name ...").
const NOT_A_THING=String.raw`(?:list|plan|summary|story|poem|essay|email|letter|message|table|schedule|outline|joke|idea|song|recipe|report|document|post|caption|title|description|sentence|paragraph|query|password|name|names|prompt|template|checklist|budget|reply|response|answer|speech|bio|resume|cv|quiz|question|test)`
const MAKE_ME=new RegExp(String.raw`${LEAD}(?:generate|create|make|render|produce)\s+me\s+(?=(?:an?|some)\s+(?!${NOT_A_THING}s?\b)[a-z])`,'i')
// "show me an image of ...", "I need a poster of ...": these only count with the description after the picture word.
const SHOW=new RegExp(String.raw`${LEAD}(?:show|give|send|get)\s+me\s+${ART}`,'i')
const NEED=new RegExp(String.raw`^(?:(?:i|we)\s+(?:really\s+)?(?:need|want|would\s+like)|(?:i|we)'d\s+like|(?:can|could)\s+i\s+(?:have|get))\s+${ART}`,'i')
const DESCRIBED=new RegExp(String.raw`^(?:an?\s+)?${NOUN}s?\s+(?:of|showing|depicting|for|with|featuring|about)\b`,'i')
const JUST_THE_WORD=new RegExp(String.raw`^(?:an?\s+)?${NOUN}s?[\s.!?]*$`,'i')
const ASKS_ABILITY=/^(?:please\s+)?(?:can|could|would|will)\s+you\b/i
// "an image of a dog" -> "a dog"; "a logo for my game" keeps its noun, because the noun is the style.
const GENERIC=/^(?:an?\s+)?(?:images?|pictures?)\s+(?:of|showing|depicting)\s+/i
const EDIT_ATTACHED=/^(?:(?:please|can you)\s+)?(?:edit|change|modify|repaint|alter)\s+(?:this|the|attached)\s+(?:image|picture|photo|drawing)\b/i
const FOLLOW_UP=/^(?:make it |add (?:a|an|the) |same (?:but|image|picture) |change (?:it|the image) |remove (?:the|a) |turn it )/i

export function imageIntent(text:string,{hasImage=false,hasPreviousImage=false}:{hasImage?:boolean;hasPreviousImage?:boolean}={}):ImageIntent|null {
  const request=text.replace(/[‘’]/g,"'").trim()
  if(!request||request.length>1500||TECHNICAL.test(request))return null
  const ordered=(match:RegExpMatchArray,needsDescription=false):ImageIntent|null=>{
    const rest=request.slice(match[0].length).trim()
    if(needsDescription&&!DESCRIBED.test(rest))return null
    // "Can you make a logo?" and "Can you create an image?" ask what STAR can do; they do not say what to draw.
    if(ASKS_ABILITY.test(request)&&JUST_THE_WORD.test(rest))return null
    const subject=rest.replace(GENERIC,'').replace(/[\s.!?]+$/,'').trim()
    return {prompt:subject||rest||request,followup:false}
  }
  const command=request.match(COMMAND)||request.match(DRAW)||request.match(MAKE_ME)
  if(command)return ordered(command)
  const described=request.match(SHOW)||request.match(NEED)
  if(described)return ordered(described,true)
  if(hasImage&&EDIT_ATTACHED.test(request))return {prompt:request,followup:false}
  if(hasPreviousImage&&FOLLOW_UP.test(request))return {prompt:request,followup:true}
  return null
}

export const isPicturePath=(path:string)=>/\.(?:png|jpe?g|webp)$/i.test(path)

/**
 * "It" only means a picture when the newest answer is one. When retrying, the question being retried is
 * the last message and is looked past.
 */
export function endsWithPicture(messages:Pick<ChatMessage,'role'|'image'>[],retrying=false):boolean {
  const rows=messages.filter(m=>m.role!=='event')
  if(retrying&&rows.length&&rows[rows.length-1].role==='user')rows.pop()
  const last=rows[rows.length-1]
  return !!last&&last.role==='assistant'&&!!last.image
}

/**
 * The picture request hidden in an ordinary chat message, or null to send it to the text model.
 * At most one attachment, and it must be a picture: it is the one to change. (Masks and two-picture
 * edits stay in the Image tab, where the second file is clearly a mask.)
 */
export function chatImageRequest(text:string,attachments:string[],messages:Pick<ChatMessage,'role'|'image'>[],retrying=false):ImageIntent|null {
  if(attachments.length>1||!attachments.every(isPicturePath))return null
  return imageIntent(text,{hasImage:attachments.length===1,hasPreviousImage:attachments.length===0&&endsWithPicture(messages,retrying)})
}
