import type {CastId} from './cast'

/**
 * Scripted lines. Ember: bookish, warm, a little smug. Astra: cool, teasing, secretly soft.
 * Gemini: bubbly and competitive. Star: the cheerful host. Lines stay short enough for a bubble.
 */
export type Situation = 'greet' | 'working' | 'done' | 'error' | 'stopped' | 'night' | 'study' | 'studyNap'
  | 'tagStart' | 'tagged' | 'tired' | 'poke' | 'pickup' | 'drop' | 'kissAfter' | 'hugAfter' | 'update'

export type Line = { who: CastId; text: string }

export const SOLO: Readonly<Record<Situation, Readonly<Partial<Record<CastId, readonly string[]>>>>> = {
  greet: {
    star: ['Hi hi! Ready to make something?', 'Welcome back!', 'Everyone, look who it is!'],
    ember: ['Oh, good. You’re here.', 'I saved you a seat. And a footnote.'],
    astra: ['Hey. Took you long enough.', 'Oh. It’s you. ...Hi.'],
    gemini: ['Hiii! Today’s gonna be great!', 'You’re here! I win the bet!'],
  },
  working: {
    star: ['On it! Typing very fast!', 'Leave this one to me!', 'Thinking caps on!'],
    ember: ['Quiet, please. Star is working.', 'I’ll check the sources.'],
    astra: ['Go, Star. Don’t mess it up.', 'I’m watching. Casually.'],
    gemini: ['Go go go, Star!', 'Bet she finishes in record time!'],
  },
  done: {
    star: ['All done! Take a look!', 'Ta-da! Finished!', 'Done and dusted!'],
    ember: ['Neatly done. As expected.', 'Well argued, Star.'],
    astra: ['Not bad. Not bad at all.', 'Huh. That worked.'],
    gemini: ['Yaaay! New record!', 'We did it! High five!'],
  },
  error: {
    star: ['Oops. That didn’t work...', 'Uh oh. Let’s try that again?'],
    ember: ['Hm. Something went wrong.', 'Let’s read the error together.'],
    astra: ['...It broke. I didn’t touch it.', 'Rough one. You’ll get it.'],
    gemini: ['Nooo! Rematch!', 'That one doesn’t count!'],
  },
  stopped: {
    star: ['Okay, stopping!', 'Stopped. Change of plans?'],
    gemini: ['Whoa, brakes!'],
  },
  update: { star: ['Psst! An update is here!'], gemini: ['New stuff! New stuff!'] },
  night: {
    star: ['It’s late... one more?', 'Yawn... still here!'],
    ember: ['Midnight reading is the best reading.', 'Don’t stay up too late.'],
    astra: ['Night is my time.', 'The stars are out. Obviously.'],
    gemini: ['Not sleepy! ...Okay, a little.'],
  },
  study: {
    star: ['Study session! Let’s go!', 'Learning mode: on!'],
    ember: ['Finally, homework.', 'Page forty-two. Focus.'],
    astra: ['I’m only here for the snacks.', 'Fine. I’ll study. For you.'],
    gemini: ['First to finish wins!', 'I’m gonna ace this!'],
  },
  studyNap: {
    star: ['Zzz... more data...'], ember: ['Just resting my eyes...'], astra: ['I’m not asleep.'], gemini: ['Zzz... I win...'],
  },
  tagStart: {
    star: ['Tag! You’re it!'], gemini: ['Tag game! I’m it! Run!'], astra: ['Bet you can’t catch me.'], ember: ['A little exercise, then.'],
  },
  tagged: {
    star: ['Gotcha!'], ember: ['Tag. Elementary.'], astra: ['Too slow.'], gemini: ['Tag! Ha ha!'],
  },
  tired: {
    star: ['Phew... break time!'], ember: ['I need... a chair.'], astra: ['I let you win.'], gemini: ['I wasn’t tired! ...Okay.'],
  },
  poke: {
    star: ['Hehe! That tickles!', 'Yes? Need help?', 'Boop!'],
    ember: ['Ahem. I’m reading.', 'Careful with the glasses!', 'Yes, dear?'],
    astra: ['Hey. Paws off.', '...Do it again. I mean, don’t.', 'What?'],
    gemini: ['Hee! Again again!', 'Tag! You’re it!', 'Boop back!'],
  },
  pickup: {
    star: ['Whoa, up we go!'], ember: ['Put me down this instant!'], astra: ['Hey! Unhand me!'], gemini: ['Wheee! Higher!'],
  },
  drop: {
    star: ['Safe landing!'], ember: ['My dignity...'], astra: ['Ten out of ten. Obviously.'], gemini: ['Again! Again!'],
  },
  kissAfter: {
    star: ['Hehe~'], ember: ['...Ahem.'], astra: ['D-don’t look!'], gemini: ['Hee hee!'],
  },
  hugAfter: {
    star: ['Group hug next!'], ember: ['That was nice.'], astra: ['That didn’t happen.'], gemini: ['Best hug ever!'],
  },
}

type PairKey = `${CastId}+${CastId}`
const pair = (a: CastId, b: CastId): PairKey => (a < b ? `${a}+${b}` : `${b}+${a}`) as PairKey

const BANTER: Readonly<Partial<Record<PairKey, readonly (readonly Line[])[]>>> = {
  'astra+ember': [
    [{who: 'ember', text: 'I read ahead. Chapter twelve has a twist.'}, {who: 'astra', text: 'Spoilers. Some friend you are.'}, {who: 'ember', text: 'A friend who’s right.'}],
    [{who: 'astra', text: 'Your glasses are crooked.'}, {who: 'ember', text: 'They are not.'}, {who: 'astra', text: '...They are now.'}],
    [{who: 'ember', text: 'You could read with me, you know.'}, {who: 'astra', text: 'Maybe. If you read the good parts out loud.'}],
  ],
  'astra+gemini': [
    [{who: 'gemini', text: 'Race you to the edge!'}, {who: 'astra', text: 'Fine. But I’m not trying.'}, {who: 'gemini', text: 'That’s what losers say!'}],
    [{who: 'astra', text: 'Is your hair two colours on purpose?'}, {who: 'gemini', text: 'It’s called style! Sky and sunset!'}],
    [{who: 'gemini', text: 'Bet I can blink faster than you.'}, {who: 'astra', text: 'Cats don’t compete. We win.'}],
  ],
  'ember+gemini': [
    [{who: 'gemini', text: 'Quiz me! Anything!'}, {who: 'ember', text: 'What’s the capital of Australia?'}, {who: 'gemini', text: 'Sydney! ...Wait.'}, {who: 'ember', text: 'Canberra, dear.'}],
    [{who: 'ember', text: 'You have glitter on your cape.'}, {who: 'gemini', text: 'I have glitter everywhere!'}],
  ],
  'ember+star': [
    [{who: 'star', text: 'Ember, what are you reading?'}, {who: 'ember', text: 'A book about you. Very dramatic.'}, {who: 'star', text: 'Ooh, do I win?'}],
    [{who: 'ember', text: 'You type too loudly, Star.'}, {who: 'star', text: 'That’s the sound of progress!'}],
  ],
  'astra+star': [
    [{who: 'star', text: 'Astra! Want to help?'}, {who: 'astra', text: 'Help? I’m supervising.'}, {who: 'star', text: 'Best supervisor ever!'}],
    [{who: 'astra', text: 'Your star clip is cute.'}, {who: 'star', text: 'Really?!'}, {who: 'astra', text: '...Forget I said that.'}],
  ],
  'gemini+star': [
    [{who: 'gemini', text: 'Star! Star! Look at my clip!'}, {who: 'star', text: 'We match! Star buddies!'}],
    [{who: 'star', text: 'Gemini, are you racing again?'}, {who: 'gemini', text: 'Always! I’m undefeated!'}, {who: 'star', text: 'Since this morning.'}],
  ],
}

const STUDY_BANTER: readonly (readonly Line[])[] = [
  [{who: 'gemini', text: 'Done! First!'}, {who: 'ember', text: 'You skipped page two.'}],
  [{who: 'astra', text: 'Can I copy your notes?'}, {who: 'ember', text: 'Absolutely not.'}],
  [{who: 'star', text: 'STAR is learning too!'}, {who: 'gemini', text: 'Go, Star! Get smarter!'}],
]

export function pickLine(situation: Situation, who: CastId, random: () => number): string | null {
  const options = SOLO[situation][who]
  if (!options?.length) return null
  return options[Math.floor(random() * options.length) % options.length]
}

/** A short scripted exchange for two cast members; study lines only when both are present. */
export function pickBanter(a: CastId, b: CastId, random: () => number, study = false): readonly Line[] {
  if (study) {
    const fits = STUDY_BANTER.filter(script => script.every(line => line.who === a || line.who === b))
    if (fits.length) return fits[Math.floor(random() * fits.length) % fits.length]
  }
  const scripts = BANTER[pair(a, b)] ?? []
  return scripts.length ? scripts[Math.floor(random() * scripts.length) % scripts.length] : []
}
