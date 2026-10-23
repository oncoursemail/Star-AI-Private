export const WEBSITE_REPO = 'https://github.com/oncoursemail/Star-AI'
export const WEBSITE_RELEASES = WEBSITE_REPO + '/releases/latest'
export const FALLBACK_VERSION = '2.0.0'
export const examples = [
 {title:'Build in Roblox',description:'Turn an idea into a working gameplay system.',prompt:'Inspect my Roblox Studio sandbox, then help me plan a polished and responsive inventory UI. Do not edit anything until you inspect the project.'},
 {title:'Understand a reference',description:'Analyze spacing, typography and visual hierarchy.',prompt:'Analyze an attached UI reference. Separate visible observations from guesses, and propose an editable Roblox GUI hierarchy.'},
 {title:'Design with intention',description:'Create a clean interface with a consistent system.',prompt:'Design a modern OLED dark UI for my Roblox game. Start with layout, typography, component states, and accessibility.'},
]
export const blankTrend=(days=14)=>Array.from({length:days},(_,index)=>{const date=new Date();date.setDate(date.getDate()-(days-1-index));return {date:date.toISOString().slice(0,10),runs:0}})
